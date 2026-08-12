"""
Migration OSINT Monitor

File:
analysis/telegram_backfill.py

Purpose:
Telegram historical backfill / reprocess runner using the SAME Telegram
collector logic as the normal monitor run.

V2 speed optimization:
- one persistent Telegram client for the whole backfill;
- channel discovery + content validation cached once per query;
- no repeated reconnect/discovery/validation for every single day;
- analytical pipeline and search quality remain unchanged.

Default test window:
2026-07-15 -> 2026-08-05

Required secrets:
TELEGRAM_API_ID
TELEGRAM_API_HASH
TELEGRAM_SESSION
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as monitor_main
from collectors.telegram_collector import TelegramCollector
from database.database import get_session
from database.models import (
    CollectedPost,
    EventGroup,
    EventGroupSource,
    InfluenceSignal,
    MonitorRun,
    Post,
)

DEFAULT_START_DATE = "2026-07-15"
DEFAULT_END_DATE = "2026-08-05"
DEFAULT_MAX_POSTS_PER_DAY = 120
DEFAULT_MAX_TOTAL_POSTS = 2500


def env_text(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def env_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    raw = env_text(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer; received {raw!r}."
        ) from exc

    value = max(minimum, value)

    if maximum is not None:
        value = min(value, maximum)

    return value


def env_bool(
    name: str,
    default: bool = False,
) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return (
        raw.strip().lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def iter_days(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


class DisabledCollector:
    def __init__(self, *args, **kwargs):
        pass

    def is_configured(self) -> bool:
        return True

    def search_recent(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return []


class TelegramHistoricalCollector(TelegramCollector):
    last_instance = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.start_date = parse_iso_date(
            env_text(
                "TELEGRAM_BACKFILL_START_DATE",
                DEFAULT_START_DATE,
            )
        )
        self.end_date = parse_iso_date(
            env_text(
                "TELEGRAM_BACKFILL_END_DATE",
                DEFAULT_END_DATE,
            )
        )

        if self.end_date < self.start_date:
            raise ValueError(
                "TELEGRAM_BACKFILL_END_DATE must be on or after "
                "TELEGRAM_BACKFILL_START_DATE."
            )

        self.max_posts_per_day = env_int(
            "TELEGRAM_BACKFILL_MAX_POSTS_PER_DAY",
            DEFAULT_MAX_POSTS_PER_DAY,
            minimum=1,
            maximum=1000,
        )
        self.max_total_posts = env_int(
            "TELEGRAM_BACKFILL_MAX_TOTAL_POSTS",
            DEFAULT_MAX_TOTAL_POSTS,
            minimum=1,
            maximum=50000,
        )
        self.query_count = env_int(
            "TELEGRAM_BACKFILL_QUERY_COUNT",
            1,
            minimum=1,
            maximum=100,
        )
        self.per_query_daily_cap = max(
            1,
            self.max_posts_per_day // self.query_count,
        )

        self.total_returned = 0
        self.day_counts = defaultdict(int)

        # --------------------------------------------------
        # BACKFILL V2 PERFORMANCE CACHE
        # --------------------------------------------------
        # The old implementation delegated every day/query slice to the base
        # search_between(), which reconnects to Telegram and repeats channel
        # discovery + channel-content validation each time.
        #
        # For a 22-day window and 5 query groups that can mean ~110 repeated
        # setup cycles. V2 keeps one authorized client alive and validates
        # channels only once per distinct query. Daily message scanning remains
        # unchanged, so historical coverage / quality is preserved.
        self._backfill_client = None
        self._accepted_channels_cache: Dict[
            str,
            List[Dict[str, Any]],
        ] = {}

        self.channel_cache_hits = 0
        self.channel_cache_misses = 0
        self.telegram_client_connects = 0
        self.historical_message_scans = 0

        # Unique source post IDs actually returned during THIS backfill.
        # This lets the audit export describe the run itself rather than every
        # historical Telegram row that happens to exist in the database.
        self.audit_source_post_ids = set()

        TelegramHistoricalCollector.last_instance = self

        print("===================================")
        print(" TELEGRAM HISTORICAL COLLECTOR")
        print("===================================")
        print(f"Date range: {self.start_date} -> {self.end_date}")
        print(f"Max posts/day: {self.max_posts_per_day}")
        print(f"Max total posts: {self.max_total_posts}")
        print(f"Query groups: {self.query_count}")
        print(f"Fair share/query/day: {self.per_query_daily_cap}")

    def _get_backfill_client(self):
        """
        Return one persistent authorized Telegram client for the complete
        historical run.

        This removes repeated connect / authorize / disconnect cycles from
        every day/query slice.
        """

        if self._backfill_client is not None:
            return self._backfill_client

        client = self._build_client()
        client.connect()

        if not client.is_user_authorized():
            client.disconnect()
            raise RuntimeError(
                "TELEGRAM_SESSION is not authorized."
            )

        self._backfill_client = client
        self.telegram_client_connects += 1

        print(
            "Telegram backfill persistent client: CONNECTED"
        )

        return client

    def _accepted_channels_for_query(
        self,
        *,
        query: str,
        search_terms: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Discover + validate channels once per query, then cache the result.

        Channel validation is a source-quality test based on recent/current
        channel content. Re-running it for every historical day does not add
        historical coverage; it only repeats expensive Telegram calls.
        """

        cache_key = str(
            query
            or ""
        ).strip()

        cached = self._accepted_channels_cache.get(
            cache_key
        )

        if cached is not None:
            self.channel_cache_hits += 1
            return cached

        self.channel_cache_misses += 1

        client = self._get_backfill_client()

        discovery_terms = self._build_discovery_terms(
            query=query,
            search_terms=search_terms,
        )

        discovered = self._collect_candidate_channels(
            client=client,
            discovery_terms=discovery_terms,
        )

        validated = self._validate_candidate_channels(
            client=client,
            channels=discovered,
        )

        accepted_channels = [
            item["channel"]
            for item in validated
            if item.get("accepted")
        ]

        accepted_channels = accepted_channels[
            :self.MAX_VALIDATED_CHANNELS_PER_QUERY
        ]

        self._accepted_channels_cache[
            cache_key
        ] = accepted_channels

        print(
            "Telegram backfill channel cache built: "
            f"query={cache_key!r} | "
            f"discovered={len(discovered)} | "
            f"accepted={len(accepted_channels)}"
        )

        return accepted_channels

    def search_between(
        self,
        *,
        query: str,
        start_at: datetime,
        end_at: datetime,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Optimized historical query.

        IMPORTANT:
        Message scanning remains day-by-day and still uses the current
        TelegramCollector._search_channels() implementation. Therefore the
        post-level migration validation, topic matching, footer cleaning,
        query semantics and per-day limits remain unchanged.

        Only repeated connection + channel discovery/content validation are
        cached.
        """

        if not self.is_configured():
            return []

        start_utc = self._ensure_utc(
            start_at
        )
        end_utc = self._ensure_utc(
            end_at
        )

        if end_utc <= start_utc:
            return []

        search_terms = self._expand_query(
            query
        )

        if not search_terms:
            return []

        accepted_channels = self._accepted_channels_for_query(
            query=query,
            search_terms=search_terms,
        )

        if not accepted_channels:
            return []

        client = self._get_backfill_client()

        self.historical_message_scans += 1

        return self._search_channels(
            client=client,
            channels=accepted_channels,
            search_terms=search_terms,
            cutoff=start_utc,
            end_at=end_utc,
            max_results=max_results,
        )

    def close_backfill_client(self) -> None:
        """
        Cleanly close the persistent Telegram connection after monitor_main
        finishes.
        """

        client = self._backfill_client

        if client is None:
            return

        try:
            client.disconnect()
        finally:
            self._backfill_client = None

        print(
            "Telegram backfill persistent client: DISCONNECTED"
        )

    def search_recent(
        self,
        query: str,
        max_results: int = 10,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        del max_results
        del max_pages

        if self.total_returned >= self.max_total_posts:
            return []

        results: List[Dict[str, Any]] = []
        seen_ids = set()

        for day in iter_days(self.start_date, self.end_date):
            if self.total_returned >= self.max_total_posts:
                break

            day_key = day.isoformat()
            remaining_day = (
                self.max_posts_per_day - self.day_counts[day_key]
            )

            if remaining_day <= 0:
                continue

            limit = min(
                self.per_query_daily_cap,
                remaining_day,
                self.max_total_posts - self.total_returned,
            )

            start_at = datetime.combine(
                day,
                time.min,
                tzinfo=timezone.utc,
            )
            end_at = start_at + timedelta(days=1)

            day_posts = self.search_between(
                query=query,
                start_at=start_at,
                end_at=end_at,
                max_results=limit,
            )

            accepted_this_day = 0

            for post in day_posts:
                post_id = str(post.get("post_id") or "")
                if not post_id or post_id in seen_ids:
                    continue

                seen_ids.add(post_id)
                results.append(post)

                self.audit_source_post_ids.add(
                    post_id
                )

                self.day_counts[day_key] += 1
                self.total_returned += 1
                accepted_this_day += 1

                if self.total_returned >= self.max_total_posts:
                    break

            if accepted_this_day:
                print(
                    "Telegram backfill day: "
                    f"{day_key} | "
                    f"query posts={accepted_this_day} | "
                    f"day total={self.day_counts[day_key]}"
                )

        print(
            "TELEGRAM BACKFILL QUERY COMPLETE: "
            f"{len(results)} posts returned | "
            f"global total={self.total_returned}"
        )

        return results


def prepare_telegram_reprocess(
    *,
    start_date: date,
    end_date: date,
) -> Dict[str, int]:
    """
    Reset only Telegram-derived analytical products in the selected interval.

    CollectedPost rows are preserved. X / Reddit / Mastodon data is untouched.
    """

    start_dt = datetime.combine(
        start_date,
        time.min,
    )

    end_dt = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
    )

    session = get_session()

    counts = {
        "event_group_sources_deleted": 0,
        "posts_deleted": 0,
        "influence_signals_deleted": 0,
        "orphan_event_groups_deleted": 0,
        "collected_posts_reset": 0,
    }

    try:
        telegram_group_links = (
            session.query(EventGroupSource)
            .filter(
                EventGroupSource.source == "TELEGRAM",
                EventGroupSource.published_at >= start_dt,
                EventGroupSource.published_at < end_dt,
            )
            .all()
        )

        candidate_group_ids = {
            int(row.event_group_id)
            for row in telegram_group_links
            if row.event_group_id is not None
        }

        for row in telegram_group_links:
            session.delete(row)
            counts["event_group_sources_deleted"] += 1

        telegram_events = (
            session.query(Post)
            .filter(
                Post.source == "TELEGRAM",
                Post.published_at >= start_dt,
                Post.published_at < end_dt,
            )
            .all()
        )

        for row in telegram_events:
            session.delete(row)
            counts["posts_deleted"] += 1

        telegram_signals = (
            session.query(InfluenceSignal)
            .filter(
                InfluenceSignal.source == "TELEGRAM",
                InfluenceSignal.published_at >= start_dt,
                InfluenceSignal.published_at < end_dt,
            )
            .all()
        )

        for row in telegram_signals:
            session.delete(row)
            counts["influence_signals_deleted"] += 1

        telegram_collected_posts = (
            session.query(CollectedPost)
            .filter(
                CollectedPost.source == "TELEGRAM",
                CollectedPost.published_at >= start_dt,
                CollectedPost.published_at < end_dt,
            )
            .all()
        )

        for row in telegram_collected_posts:
            row.is_noise = False
            row.is_operational = False
            row.operational_confidence = 0.1
            row.influence_detected = False
            counts["collected_posts_reset"] += 1

        session.flush()

        for group_id in sorted(candidate_group_ids):
            remaining_source = (
                session.query(EventGroupSource.id)
                .filter(
                    EventGroupSource.event_group_id == group_id
                )
                .first()
            )

            if remaining_source is not None:
                continue

            group = session.get(EventGroup, group_id)

            if group is None:
                continue

            session.delete(group)
            counts["orphan_event_groups_deleted"] += 1

        session.commit()
        return counts

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def _json_safe(value):
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value.isoformat()

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    if isinstance(
        value,
        dict,
    ):
        return {
            str(key): _json_safe(item)
            for key, item
            in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        return [
            _json_safe(item)
            for item
            in value
        ]

    return str(
        value
    )


def _build_audit_pipeline():
    """
    Build the same analytical components used by the current main.py.

    The audit replays classification only. It performs NO database writes.
    """

    return {
        "noise_filter":
            monitor_main.NoiseFilter(),
        "influence_detector":
            monitor_main.InfluenceSignalDetector(),
        "early_warning_detector":
            monitor_main.EarlyWarningReviewDetector(),
        "operational_filter":
            monitor_main.OperationalEventFilter(),
        "event_assertion_filter":
            monitor_main.EventAssertionFilter(),
        "keyword_filter":
            monitor_main.KeywordFilter(),
        "classifier":
            monitor_main.SignalClassifier(),
        "location_extractor":
            monitor_main.LocationExtractor(),
        "time_extractor":
            monitor_main.TimeExtractor(),
        "scorer":
            monitor_main.RelevanceScorer(),
        "event_extractor":
            monitor_main.EventExtractor(),
        "region_resolver":
            monitor_main.RegionResolver(),
    }


def _audit_collected_post(
    row,
    *,
    pipeline: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Re-run the CURRENT analytical decision chain for one Telegram post.

    This is intentionally read-only and exists only to explain WHY a post was
    retained or rejected by the current rules.
    """

    post = {
        "source":
            row.source,
        "post_id":
            row.source_post_id,
        "author":
            row.author,
        "text":
            row.text
            or "",
        "language":
            row.language,
        "published_at":
            row.published_at,
        "url":
            row.url,
    }

    text_value = (
        row.text
        or ""
    )

    noise_result = (
        pipeline[
            "noise_filter"
        ]
        .analyze(
            text_value
        )
    )

    base = {
        "collected_post_id":
            int(
                row.id
            ),
        "source":
            row.source,
        "source_post_id":
            row.source_post_id,
        "author":
            row.author,
        "published_at":
            _json_safe(
                row.published_at
            ),
        "url":
            row.url,
        "language":
            row.language,
        "text":
            text_value,
        "database_state": {
            "is_noise":
                bool(
                    row.is_noise
                ),
            "is_operational":
                bool(
                    row.is_operational
                ),
            "operational_confidence":
                row.operational_confidence,
            "influence_detected":
                bool(
                    row.influence_detected
                ),
            "collection_count":
                int(
                    row.collection_count
                    or 0
                ),
        },
    }

    if noise_result.get(
        "is_noise"
    ):
        base.update(
            {
                "final_status":
                    "NOISE",
                "rejection_reason":
                    "NOISE_FILTER",
                "primary_signal":
                    None,
                "event_type":
                    None,
                "confidence":
                    None,
                "score":
                    None,
                "matched_groups":
                    [],
                "matched_phrases":
                    noise_result.get(
                        "matched_noise_phrases",
                        [],
                    ),
                "details": {
                    "noise_categories":
                        noise_result.get(
                            "noise_categories",
                            [],
                        ),
                },
            }
        )

        return base

    influence_result = (
        pipeline[
            "influence_detector"
        ]
        .detect(
            text_value
        )
    )

    operational_result = (
        pipeline[
            "operational_filter"
        ]
        .analyze(
            text_value
        )
    )

    if not operational_result.get(
        "is_operational"
    ):
        early_warning_result = {
            "detected":
                False,
        }

        if not influence_result.get(
            "detected"
        ):
            early_warning_result = (
                pipeline[
                    "early_warning_detector"
                ]
                .detect(
                    text_value
                )
            )

        selected_signal = None

        if influence_result.get(
            "detected"
        ):
            selected_signal = (
                influence_result
            )

        elif early_warning_result.get(
            "detected"
        ):
            selected_signal = (
                early_warning_result
            )

        if selected_signal is not None:
            base.update(
                {
                    "final_status":
                        "EARLY_WARNING",
                    "rejection_reason":
                        None,
                    "primary_signal":
                        selected_signal.get(
                            "primary_signal"
                        ),
                    "signal_mode":
                        selected_signal.get(
                            "signal_mode"
                        ),
                    "signal_intent":
                        selected_signal.get(
                            "signal_intent"
                        ),
                    "event_type":
                        None,
                    "confidence":
                        selected_signal.get(
                            "confidence"
                        ),
                    "score":
                        selected_signal.get(
                            "score"
                        ),
                    "matched_groups":
                        selected_signal.get(
                            "matched_groups",
                            [],
                        ),
                    "matched_phrases":
                        selected_signal.get(
                            "matched_phrases",
                            [],
                        ),
                    "details": {
                        "rules_version":
                            selected_signal.get(
                                "rules_version"
                            ),
                        "review_reason":
                            selected_signal.get(
                                "review_reason"
                            ),
                        "actuality_reason":
                            selected_signal.get(
                                "actuality_reason"
                            ),
                        "context_matches":
                            selected_signal.get(
                                "context_matches",
                                [],
                            ),
                        "operational_categories":
                            operational_result.get(
                                "operational_categories",
                                [],
                            ),
                        "matched_operational_phrases":
                            operational_result.get(
                                "matched_operational_phrases",
                                [],
                            ),
                        "non_operational_categories":
                            operational_result.get(
                                "non_operational_categories",
                                [],
                            ),
                        "matched_non_operational_phrases":
                            operational_result.get(
                                "matched_non_operational_phrases",
                                [],
                            ),
                    },
                }
            )

            return base

        base.update(
            {
                "final_status":
                    "NON_OPERATIONAL",
                "rejection_reason":
                    "OPERATIONAL_FILTER_REJECTED",
                "primary_signal":
                    None,
                "event_type":
                    None,
                "confidence":
                    operational_result.get(
                        "confidence"
                    ),
                "score":
                    None,
                "matched_groups":
                    [],
                "matched_phrases":
                    operational_result.get(
                        "matched_non_operational_phrases",
                        [],
                    ),
                "details": {
                    "operational_categories":
                        operational_result.get(
                            "operational_categories",
                            [],
                        ),
                    "matched_operational_phrases":
                        operational_result.get(
                            "matched_operational_phrases",
                            [],
                        ),
                    "non_operational_categories":
                        operational_result.get(
                            "non_operational_categories",
                            [],
                        ),
                    "matched_non_operational_phrases":
                        operational_result.get(
                            "matched_non_operational_phrases",
                            [],
                        ),
                    "influence_review_reason":
                        influence_result.get(
                            "review_reason"
                        ),
                    "early_warning_review_reason":
                        early_warning_result.get(
                            "review_reason"
                        ),
                    "early_warning_actuality_reason":
                        early_warning_result.get(
                            "actuality_reason"
                        ),
                },
            }
        )

        return base

    event = monitor_main.analyze_post(
        post=post,
        keyword_filter=pipeline[
            "keyword_filter"
        ],
        classifier=pipeline[
            "classifier"
        ],
        location_extractor=pipeline[
            "location_extractor"
        ],
        time_extractor=pipeline[
            "time_extractor"
        ],
        scorer=pipeline[
            "scorer"
        ],
        event_extractor=pipeline[
            "event_extractor"
        ],
        region_resolver=pipeline[
            "region_resolver"
        ],
    )

    if event.get(
        "historical_reference"
    ):
        base.update(
            {
                "final_status":
                    "HISTORICAL",
                "rejection_reason":
                    event.get(
                        "historical_reason"
                    )
                    or "HISTORICAL_REFERENCE",
                "primary_signal":
                    None,
                "event_type":
                    event.get(
                        "event_type"
                    ),
                "confidence":
                    event.get(
                        "confidence"
                    ),
                "score":
                    event.get(
                        "score"
                    ),
                "matched_groups":
                    [],
                "matched_phrases":
                    event.get(
                        "matched_phrases",
                        [],
                    ),
                "details": {
                    "historical_reference_time":
                        event.get(
                            "historical_reference_time"
                        ),
                    "matched_signals":
                        event.get(
                            "matched_signals",
                            [],
                        ),
                    "primary_region":
                        event.get(
                            "primary_region"
                        ),
                    "primary_location":
                        event.get(
                            "primary_location"
                        ),
                },
            }
        )

        return base

    assertion_result = (
        pipeline[
            "event_assertion_filter"
        ]
        .analyze(
            post=post,
            event=event,
            operational_result=operational_result,
        )
    )

    if not assertion_result.get(
        "accepted",
        True,
    ):
        base.update(
            {
                "final_status":
                    "NON_OPERATIONAL",
                "rejection_reason":
                    assertion_result.get(
                        "reason"
                    )
                    or "EVENT_ASSERTION_REJECTED",
                "primary_signal":
                    None,
                "event_type":
                    event.get(
                        "event_type"
                    ),
                "confidence":
                    event.get(
                        "confidence"
                    ),
                "score":
                    event.get(
                        "score"
                    ),
                "matched_groups":
                    [],
                "matched_phrases":
                    event.get(
                        "matched_phrases",
                        [],
                    ),
                "details": {
                    "operational_categories":
                        operational_result.get(
                            "operational_categories",
                            [],
                        ),
                    "matched_operational_phrases":
                        operational_result.get(
                            "matched_operational_phrases",
                            [],
                        ),
                    "analytical_cues":
                        assertion_result.get(
                            "analytical_cues",
                            [],
                        ),
                    "current_cues":
                        assertion_result.get(
                            "current_cues",
                            [],
                        ),
                    "non_assertive_cues":
                        assertion_result.get(
                            "non_assertive_cues",
                            [],
                        ),
                    "primary_region":
                        event.get(
                            "primary_region"
                        ),
                    "primary_location":
                        event.get(
                            "primary_location"
                        ),
                },
            }
        )

        return base

    base.update(
        {
            "final_status":
                "OPERATIONAL",
            "rejection_reason":
                None,
            "primary_signal":
                None,
            "event_type":
                event.get(
                    "event_type"
                ),
            "confidence":
                event.get(
                    "confidence"
                ),
            "score":
                event.get(
                    "score"
                ),
            "matched_groups":
                [],
            "matched_phrases":
                event.get(
                    "matched_phrases",
                    [],
                ),
            "details": {
                "matched_signals":
                    event.get(
                        "matched_signals",
                        [],
                    ),
                "operational_categories":
                    operational_result.get(
                        "operational_categories",
                        [],
                    ),
                "matched_operational_phrases":
                    operational_result.get(
                        "matched_operational_phrases",
                        [],
                    ),
                "primary_region":
                    event.get(
                        "primary_region"
                    ),
                "matched_regions":
                    event.get(
                        "matched_regions",
                        [],
                    ),
                "primary_location":
                    event.get(
                        "primary_location"
                    ),
                "country":
                    event.get(
                        "country"
                    ),
                "latitude":
                    event.get(
                        "latitude"
                    ),
                "longitude":
                    event.get(
                        "longitude"
                    ),
            },
        }
    )

    return base


def export_telegram_backfill_audit(
    *,
    source_post_ids,
    start_date: date,
    end_date: date,
    backfill_run_ids: List[int],
    reprocess_existing: bool,
    collector,
) -> Dict[str, Any]:
    """
    Export a standalone, human-auditable JSON for THIS Telegram backfill.

    Dashboard export is intentionally untouched.
    """

    audit_path = (
        REPO_ROOT
        / "data"
        / "telegram_backfill_audit.json"
    )

    audit_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    normalized_ids = {
        str(
            value
        )
        for value
        in (
            source_post_ids
            or []
        )
        if str(
            value
            or ""
        ).strip()
    }

    session = get_session()

    try:
        query = (
            session.query(
                CollectedPost
            )
            .filter(
                CollectedPost.source
                == "TELEGRAM",
            )
        )

        if normalized_ids:
            query = query.filter(
                CollectedPost.source_post_id.in_(
                    sorted(
                        normalized_ids
                    )
                )
            )

        else:
            start_dt = datetime.combine(
                start_date,
                time.min,
            )

            end_dt = datetime.combine(
                end_date
                + timedelta(
                    days=1
                ),
                time.min,
            )

            query = query.filter(
                CollectedPost.published_at
                >= start_dt,
                CollectedPost.published_at
                < end_dt,
            )

        rows = (
            query
            .order_by(
                CollectedPost.published_at.asc(),
                CollectedPost.id.asc(),
            )
            .all()
        )

        pipeline = (
            _build_audit_pipeline()
        )

        posts = [
            _audit_collected_post(
                row,
                pipeline=pipeline,
            )
            for row
            in rows
        ]

    finally:
        session.close()

    status_counts = defaultdict(
        int
    )

    signal_counts = defaultdict(
        int
    )

    rejection_counts = defaultdict(
        int
    )

    for item in posts:
        status = str(
            item.get(
                "final_status"
            )
            or "UNKNOWN"
        )

        status_counts[
            status
        ] += 1

        signal = item.get(
            "primary_signal"
        )

        if signal:
            signal_counts[
                str(
                    signal
                )
            ] += 1

        rejection = item.get(
            "rejection_reason"
        )

        if rejection:
            rejection_counts[
                str(
                    rejection
                )
            ] += 1

    payload = {
        "schema_version":
            "1.0",
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "audit_scope": {
            "source":
                "TELEGRAM",
            "start_date":
                start_date.isoformat(),
            "end_date":
                end_date.isoformat(),
            "backfill_run_ids":
                backfill_run_ids,
            "reprocess_existing":
                bool(
                    reprocess_existing
                ),
            "returned_post_count":
                (
                    int(
                        collector.total_returned
                    )
                    if collector
                    is not None
                    else None
                ),
            "unique_returned_post_ids":
                len(
                    normalized_ids
                ),
            "audited_database_rows":
                len(
                    posts
                ),
            "collector_speed_metrics": {
                "persistent_client_connects":
                    (
                        int(
                            collector.telegram_client_connects
                        )
                        if collector
                        is not None
                        else None
                    ),
                "channel_cache_builds":
                    (
                        int(
                            collector.channel_cache_misses
                        )
                        if collector
                        is not None
                        else None
                    ),
                "channel_cache_hits":
                    (
                        int(
                            collector.channel_cache_hits
                        )
                        if collector
                        is not None
                        else None
                    ),
                "historical_message_scans":
                    (
                        int(
                            collector.historical_message_scans
                        )
                        if collector
                        is not None
                        else None
                    ),
            },
        },
        "summary": {
            "status_counts":
                dict(
                    sorted(
                        status_counts.items()
                    )
                ),
            "signal_counts":
                dict(
                    sorted(
                        signal_counts.items()
                    )
                ),
            "rejection_reason_counts":
                dict(
                    sorted(
                        rejection_counts.items()
                    )
                ),
        },
        "posts":
            posts,
    }

    with audit_path.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            _json_safe(
                payload
            ),
            handle,
            ensure_ascii=False,
            indent=2,
        )

        handle.write(
            "\n"
        )

    print(
        "==================================="
    )
    print(
        " TELEGRAM BACKFILL AUDIT EXPORT"
    )
    print(
        "==================================="
    )
    print(
        "Audit file: "
        f"{audit_path}"
    )
    print(
        "Audited rows: "
        f"{len(posts)}"
    )
    print(
        "Status counts: "
        f"{dict(status_counts)}"
    )
    print(
        "Signal counts: "
        f"{dict(signal_counts)}"
    )
    print(
        "Top rejection reasons: "
        f"{dict(rejection_counts)}"
    )

    return payload


def latest_monitor_run_snapshot():
    session = get_session()
    try:
        row = (
            session.query(MonitorRun)
            .order_by(MonitorRun.id.desc())
            .first()
        )

        if row is None:
            return {
                "max_id": 0,
                "started_at": None,
            }

        return {
            "max_id": int(row.id),
            "started_at": row.started_at,
        }
    finally:
        session.close()


def historical_run_timestamp(
    *,
    end_date: date,
    previous_latest_started_at: Optional[datetime],
) -> datetime:
    target = datetime.combine(
        end_date,
        time(23, 59, 0),
    )

    if previous_latest_started_at is None:
        return target

    previous = previous_latest_started_at

    if previous.tzinfo is not None:
        previous = (
            previous.astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

    if target >= previous:
        target = previous - timedelta(seconds=1)

    return target


def mark_new_runs_as_backfill(
    *,
    previous_max_id: int,
    previous_latest_started_at: Optional[datetime],
    end_date: date,
) -> List[int]:
    session = get_session()

    try:
        new_runs = (
            session.query(MonitorRun)
            .filter(MonitorRun.id > previous_max_id)
            .order_by(MonitorRun.id.asc())
            .all()
        )

        if not new_runs:
            raise RuntimeError(
                "No new MonitorRun row was created."
            )

        timestamp = historical_run_timestamp(
            end_date=end_date,
            previous_latest_started_at=previous_latest_started_at,
        )

        updated_ids = []

        for run in new_runs:
            run.started_at = timestamp
            run.completed_at = timestamp + timedelta(seconds=1)
            run.status = "BACKFILL_SUCCESS"
            updated_ids.append(int(run.id))

        session.commit()
        return updated_ids

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> int:
    start_date = parse_iso_date(
        env_text(
            "TELEGRAM_BACKFILL_START_DATE",
            DEFAULT_START_DATE,
        )
    )
    end_date = parse_iso_date(
        env_text(
            "TELEGRAM_BACKFILL_END_DATE",
            DEFAULT_END_DATE,
        )
    )

    if end_date < start_date:
        raise ValueError(
            "End date must not be before start date."
        )

    reprocess_existing = env_bool(
        "TELEGRAM_BACKFILL_REPROCESS_EXISTING",
        False,
    )

    query_engine = monitor_main.QueryEngine()
    queries = query_engine.load_queries()

    os.environ["TELEGRAM_BACKFILL_QUERY_COUNT"] = str(
        max(1, len(queries))
    )

    previous = latest_monitor_run_snapshot()

    original_x = monitor_main.XCollector
    original_reddit = monitor_main.RedditCollector
    original_mastodon = monitor_main.MastodonCollector
    original_telegram = monitor_main.TelegramCollector

    print("===================================")
    print(" TELEGRAM HISTORICAL BACKFILL")
    print("===================================")
    print(f"Start: {start_date}")
    print(f"End:   {end_date}")
    print("Sources: TELEGRAM ONLY")
    print("Telegram source logic: CURRENT collector")
    print("Analytical pipeline: CURRENT main.py")
    print("Database writes: ENABLED")
    print(
        "Reprocess existing Telegram history: "
        f"{reprocess_existing}"
    )
    print("Duplicate protection: EXISTING DATABASE LOGIC")

    reprocess_counts = None

    if reprocess_existing:
        print("===================================")
        print(" TELEGRAM REPROCESS PREPARATION")
        print("===================================")

        reprocess_counts = prepare_telegram_reprocess(
            start_date=start_date,
            end_date=end_date,
        )

        print(
            "Telegram EventGroupSource rows removed: "
            f"{reprocess_counts['event_group_sources_deleted']}"
        )
        print(
            "Telegram operational Post rows removed: "
            f"{reprocess_counts['posts_deleted']}"
        )
        print(
            "Telegram InfluenceSignal rows removed: "
            f"{reprocess_counts['influence_signals_deleted']}"
        )
        print(
            "Orphan EventGroups removed: "
            f"{reprocess_counts['orphan_event_groups_deleted']}"
        )
        print(
            "Telegram CollectedPost states reset: "
            f"{reprocess_counts['collected_posts_reset']}"
        )

    try:
        monitor_main.XCollector = DisabledCollector
        monitor_main.RedditCollector = DisabledCollector
        monitor_main.MastodonCollector = DisabledCollector
        monitor_main.TelegramCollector = TelegramHistoricalCollector

        monitor_main.main()

    finally:
        collector_instance = (
            TelegramHistoricalCollector.last_instance
        )

        if collector_instance is not None:
            collector_instance.close_backfill_client()

        monitor_main.XCollector = original_x
        monitor_main.RedditCollector = original_reddit
        monitor_main.MastodonCollector = original_mastodon
        monitor_main.TelegramCollector = original_telegram

    updated_ids = mark_new_runs_as_backfill(
        previous_max_id=previous["max_id"],
        previous_latest_started_at=previous["started_at"],
        end_date=end_date,
    )

    collector = TelegramHistoricalCollector.last_instance

    audit_payload = export_telegram_backfill_audit(
        source_post_ids=(
            collector.audit_source_post_ids
            if collector is not None
            else set()
        ),
        start_date=start_date,
        end_date=end_date,
        backfill_run_ids=updated_ids,
        reprocess_existing=reprocess_existing,
        collector=collector,
    )

    total_returned = (
        collector.total_returned
        if collector is not None
        else 0
    )

    day_counts = (
        dict(sorted(collector.day_counts.items()))
        if collector is not None
        else {}
    )

    print("===================================")
    print(" TELEGRAM BACKFILL COMPLETE")
    print("===================================")
    print(f"Telegram posts returned: {total_returned}")
    print(
        "Days with Telegram data: "
        f"{sum(1 for value in day_counts.values() if value)}"
    )
    print(f"Backfill MonitorRun IDs: {updated_ids}")
    print("Backfill status: BACKFILL_SUCCESS")
    print(
        "Reprocess mode: "
        f"{reprocess_existing}"
    )
    print("Current normal dashboard run preserved: YES")
    print(
        "Telegram audit JSON: "
        "data/telegram_backfill_audit.json"
    )
    print(
        "Telegram audit rows: "
        f"{len(audit_payload.get('posts', []))}"
    )

    if collector is not None:
        print(
            "Telegram persistent client connects: "
            f"{collector.telegram_client_connects}"
        )
        print(
            "Telegram channel cache builds: "
            f"{collector.channel_cache_misses}"
        )
        print(
            "Telegram channel cache hits: "
            f"{collector.channel_cache_hits}"
        )
        print(
            "Telegram historical day/query message scans: "
            f"{collector.historical_message_scans}"
        )

    if reprocess_counts is not None:
        print(
            "Reprocess cleanup summary: "
            f"{reprocess_counts}"
        )

    if day_counts:
        print("Backfill daily counts:")
        for day_key, count in day_counts.items():
            if count:
                print(f"  {day_key}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


