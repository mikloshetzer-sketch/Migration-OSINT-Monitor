"""
Migration OSINT Monitor

File:
analysis/telegram_source_discovery.py

Purpose:
Independent Telegram public-channel discovery diagnostic.

IMPORTANT:
- Does NOT modify the existing Telegram collector.
- Does NOT write to the database.
- Does NOT join channels or groups.
- Does NOT read private chats/groups.
- Does NOT authorize paid Telegram Stars searches.
- Uses the existing TELEGRAM_API_ID / TELEGRAM_API_HASH /
  TELEGRAM_SESSION secrets.
- Optionally reuses the repository's analytical filters to evaluate
  discovered public posts.
- Writes one JSON file to the repository root:
    telegram-source-discovery.json

The script uses Telegram's global public-channel post search
(channels.searchPosts). It is intended as a diagnostic coverage test,
not as a replacement for the production collector.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CheckSearchPostsFloodRequest,
    SearchPostsRequest,
)
from telethon.tl.types import InputPeerEmpty

# Existing analytical layers are read-only dependencies here.
# If an import is unavailable, discovery still runs and records the error.
try:
    from analysis.noise_filter import NoiseFilter
except Exception:
    NoiseFilter = None

try:
    from analysis.operational_event_filter import OperationalEventFilter
except Exception:
    OperationalEventFilter = None

try:
    from analysis.early_warning_review_detector import EarlyWarningReviewDetector
except Exception:
    EarlyWarningReviewDetector = None

try:
    from analysis.event_assertion_filter import EventAssertionFilter
except Exception:
    EventAssertionFilter = None


OUTPUT_PATH = REPO_ROOT / "telegram-source-discovery.json"

DEFAULT_MAX_QUERIES = 8
DEFAULT_RESULTS_PER_QUERY = 25
DEFAULT_SAMPLE_POSTS_PER_CHANNEL = 3


# ---------------------------------------------------------------------
# Discovery queries
# ---------------------------------------------------------------------
# These are intentionally EVENT-STRUCTURE oriented and geographically
# generic. They are not tied to Ceuta, Morocco, Melilla, Lampedusa or
# another single route.
#
# First diagnostic pass:
# - broad enough to discover new sources;
# - compact enough not to burn Telegram's daily global-search quota.
# ---------------------------------------------------------------------

DISCOVERY_QUERIES: List[Dict[str, str]] = [
    {
        "id": "en_border_crossing",
        "language": "en",
        "family": "MOVEMENT",
        "query": "migrants border crossing",
    },
    {
        "id": "en_interception",
        "language": "en",
        "family": "INTERCEPTION",
        "query": "migrants intercepted",
    },
    {
        "id": "en_sea_movement",
        "language": "en",
        "family": "SEA_MOVEMENT",
        "query": "migrant boat coast",
    },
    {
        "id": "es_border_crossing",
        "language": "es",
        "family": "MOVEMENT",
        "query": "migrantes frontera cruce",
    },
    {
        "id": "ru_enforcement",
        "language": "ru",
        "family": "ENFORCEMENT",
        "query": "мигранты задержаны",
    },
    {
        "id": "ru_border",
        "language": "ru",
        "family": "MOVEMENT",
        "query": "мигранты граница",
    },
    {
        "id": "ar_border",
        "language": "ar",
        "family": "MOVEMENT",
        "query": "مهاجرين الحدود",
    },
    {
        "id": "ar_crossing",
        "language": "ar",
        "family": "MOVEMENT",
        "query": "عبور المهاجرين",
    },
    {
        "id": "fr_crossing",
        "language": "fr",
        "family": "MOVEMENT",
        "query": "migrants frontière passage",
    },
    {
        "id": "it_arrival",
        "language": "it",
        "family": "MOVEMENT",
        "query": "migranti arrivi costa",
    },
    {
        "id": "tr_border",
        "language": "tr",
        "family": "MOVEMENT",
        "query": "göçmen sınır geçişi",
    },
    {
        "id": "generic_smuggling",
        "language": "multi",
        "family": "FACILITATION",
        "query": "migrant smuggling route",
    },
]


def env_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    raw = str(os.getenv(name, default)).strip()

    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer; got {raw!r}"
        ) from exc

    value = max(minimum, value)

    if maximum is not None:
        value = min(maximum, value)

    return value


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_preview(
    value: str,
    limit: int = 700,
) -> str:
    clean = " ".join(
        str(value or "").split()
    )

    if len(clean) <= limit:
        return clean

    return clean[: limit - 1] + "…"


def safe_attr(
    obj: Any,
    name: str,
    default: Any = None,
) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def peer_channel_id(message: Any) -> Optional[int]:
    peer = safe_attr(message, "peer_id")

    if peer is None:
        return None

    channel_id = safe_attr(
        peer,
        "channel_id",
    )

    if channel_id is None:
        return None

    try:
        return int(channel_id)
    except (TypeError, ValueError):
        return None


def build_chat_lookup(
    chats: List[Any],
) -> Dict[int, Any]:
    result = {}

    for chat in chats or []:
        chat_id = safe_attr(
            chat,
            "id",
        )

        if chat_id is None:
            continue

        try:
            result[int(chat_id)] = chat
        except (TypeError, ValueError):
            continue

    return result


def channel_identity(
    chat: Any,
    channel_id: int,
) -> Dict[str, Any]:
    username = safe_attr(
        chat,
        "username",
    )

    title = safe_attr(
        chat,
        "title",
    )

    return {
        "channel_id": channel_id,
        "username": username,
        "title": title,
        "url": (
            f"https://t.me/{username}"
            if username
            else None
        ),
        "broadcast": bool(
            safe_attr(
                chat,
                "broadcast",
                False,
            )
        ),
        "megagroup": bool(
            safe_attr(
                chat,
                "megagroup",
                False,
            )
        ),
        "verified": bool(
            safe_attr(
                chat,
                "verified",
                False,
            )
        ),
    }


class FilterBundle:
    """
    Read-only wrapper around the repository's existing migration filters.
    """

    def __init__(self) -> None:
        self.noise_filter = (
            NoiseFilter()
            if NoiseFilter is not None
            else None
        )
        self.operational_filter = (
            OperationalEventFilter()
            if OperationalEventFilter is not None
            else None
        )
        self.early_warning_detector = (
            EarlyWarningReviewDetector()
            if EarlyWarningReviewDetector is not None
            else None
        )
        self.assertion_filter = (
            EventAssertionFilter()
            if EventAssertionFilter is not None
            else None
        )

    def availability(self) -> Dict[str, bool]:
        return {
            "NoiseFilter":
                self.noise_filter is not None,
            "OperationalEventFilter":
                self.operational_filter is not None,
            "EarlyWarningReviewDetector":
                self.early_warning_detector is not None,
            "EventAssertionFilter":
                self.assertion_filter is not None,
        }

    def analyze(
        self,
        text: str,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "noise": False,
            "operational": False,
            "operational_categories": [],
            "early_warning": False,
            "early_warning_signal": None,
            "analysis_error": None,
        }

        try:
            if self.noise_filter is not None:
                noise_result = (
                    self.noise_filter.analyze(
                        text
                    )
                )
                result["noise"] = bool(
                    noise_result.get(
                        "is_noise"
                    )
                )

            if (
                not result["noise"]
                and self.operational_filter
                is not None
            ):
                op_result = (
                    self.operational_filter.analyze(
                        text
                    )
                )

                result["operational"] = bool(
                    op_result.get(
                        "is_operational"
                    )
                )

                result[
                    "operational_categories"
                ] = list(
                    op_result.get(
                        "operational_categories",
                        [],
                    )
                    or []
                )

            if (
                not result["noise"]
                and not result["operational"]
                and self.early_warning_detector
                is not None
            ):
                ew_result = (
                    self.early_warning_detector.detect(
                        text
                    )
                )

                result["early_warning"] = bool(
                    ew_result.get(
                        "detected"
                    )
                )

                result[
                    "early_warning_signal"
                ] = ew_result.get(
                    "primary_signal"
                )

        except Exception as exc:
            result["analysis_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

        return result


def source_score(
    *,
    query_ids: set,
    post_count: int,
    operational_count: int,
    early_warning_count: int,
    noise_count: int,
) -> Tuple[int, str]:
    """
    Diagnostic source quality score.

    This score is deliberately transparent and conservative.
    It is NOT used to modify the production source list.
    """

    score = 0

    # Repeated discovery under independent query families is valuable.
    score += min(
        len(query_ids) * 2,
        8,
    )

    # Multiple matched public posts indicate source depth.
    score += min(
        post_count,
        4,
    )

    # Concrete operational hits are the strongest source-quality signal.
    score += min(
        operational_count * 4,
        12,
    )

    # Analyst-review early warnings are useful but weaker.
    score += min(
        early_warning_count * 2,
        6,
    )

    # Consistent noise should reduce ranking.
    score -= min(
        noise_count * 2,
        6,
    )

    score = max(
        0,
        score,
    )

    if score >= 12:
        label = "HIGH_VALUE"
    elif score >= 8:
        label = "REVIEW"
    elif score >= 4:
        label = "CANDIDATE"
    else:
        label = "LOW_VALUE"

    return score, label


async def quota_status(
    client: TelegramClient,
    query: str,
) -> Dict[str, Any]:
    """
    Read Telegram's global-post-search quota state.

    No paid authorization is performed here.
    """

    result = await client(
        CheckSearchPostsFloodRequest(
            query=query,
        )
    )

    return {
        "query_is_free": bool(
            safe_attr(
                result,
                "query_is_free",
                False,
            )
        ),
        "total_daily": safe_attr(
            result,
            "total_daily",
        ),
        "remains": safe_attr(
            result,
            "remains",
        ),
        "wait_till": safe_attr(
            result,
            "wait_till",
        ),
        "stars_amount": safe_attr(
            result,
            "stars_amount",
        ),
    }


def search_allowed_without_payment(
    status: Dict[str, Any],
) -> bool:
    """
    Only free/cached searches are allowed.

    If Telegram says no free slots remain, the diagnostic skips the query.
    """

    if status.get(
        "query_is_free"
    ):
        return True

    remains = status.get(
        "remains"
    )

    if remains is None:
        # Fail closed if Telegram did not provide quota information.
        return False

    try:
        return int(remains) > 0
    except (TypeError, ValueError):
        return False


async def search_public_posts(
    client: TelegramClient,
    query: str,
    limit: int,
) -> Any:
    """
    Execute exactly one first-page global public-channel post search.

    allow_paid_stars is intentionally left unset/None.
    """

    return await client(
        SearchPostsRequest(
            hashtag=None,
            query=query,
            offset_rate=0,
            offset_peer=InputPeerEmpty(),
            offset_id=0,
            limit=limit,
            allow_paid_stars=None,
        )
    )


async def run_discovery() -> Dict[str, Any]:
    api_id_raw = str(
        os.getenv(
            "TELEGRAM_API_ID",
            "",
        )
    ).strip()

    api_hash = str(
        os.getenv(
            "TELEGRAM_API_HASH",
            "",
        )
    ).strip()

    session_string = str(
        os.getenv(
            "TELEGRAM_SESSION",
            "",
        )
    ).strip()

    if not (
        api_id_raw
        and api_hash
        and session_string
    ):
        raise RuntimeError(
            "Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / "
            "TELEGRAM_SESSION."
        )

    try:
        api_id = int(
            api_id_raw
        )
    except ValueError as exc:
        raise RuntimeError(
            "TELEGRAM_API_ID must be an integer."
        ) from exc

    max_queries = env_int(
        "TELEGRAM_DISCOVERY_MAX_QUERIES",
        DEFAULT_MAX_QUERIES,
        minimum=1,
        maximum=len(
            DISCOVERY_QUERIES
        ),
    )

    results_per_query = env_int(
        "TELEGRAM_DISCOVERY_RESULTS_PER_QUERY",
        DEFAULT_RESULTS_PER_QUERY,
        minimum=1,
        maximum=100,
    )

    sample_limit = env_int(
        "TELEGRAM_DISCOVERY_SAMPLE_POSTS_PER_CHANNEL",
        DEFAULT_SAMPLE_POSTS_PER_CHANNEL,
        minimum=1,
        maximum=10,
    )

    filter_bundle = FilterBundle()

    query_plan = (
        DISCOVERY_QUERIES[
            :max_queries
        ]
    )

    started_at = utcnow_iso()

    channel_rows: Dict[
        int,
        Dict[str, Any],
    ] = {}

    query_audit = []

    seen_post_keys = set()

    summary = {
        "queries_planned":
            len(query_plan),
        "queries_completed":
            0,
        "queries_skipped_no_free_quota":
            0,
        "queries_failed":
            0,
        "raw_messages_returned":
            0,
        "unique_public_channel_posts":
            0,
        "unique_channels":
            0,
        "paid_search_used":
            False,
    }

    client = TelegramClient(
        StringSession(
            session_string
        ),
        api_id,
        api_hash,
    )

    await client.connect()

    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized."
            )

        for query_def in query_plan:
            query_id = query_def[
                "id"
            ]
            query_text = query_def[
                "query"
            ]

            query_record = {
                **query_def,
                "quota_before": None,
                "status": None,
                "messages_returned": 0,
                "public_channel_posts": 0,
                "error": None,
            }

            try:
                quota = await quota_status(
                    client,
                    query_text,
                )

                query_record[
                    "quota_before"
                ] = quota

                if not search_allowed_without_payment(
                    quota
                ):
                    query_record[
                        "status"
                    ] = "SKIPPED_NO_FREE_QUOTA"

                    summary[
                        "queries_skipped_no_free_quota"
                    ] += 1

                    query_audit.append(
                        query_record
                    )

                    # Stop here instead of burning through the remaining query plan.
                    break

                response = await search_public_posts(
                    client=client,
                    query=query_text,
                    limit=results_per_query,
                )

                messages = list(
                    safe_attr(
                        response,
                        "messages",
                        [],
                    )
                    or []
                )

                chats = list(
                    safe_attr(
                        response,
                        "chats",
                        [],
                    )
                    or []
                )

                summary[
                    "raw_messages_returned"
                ] += len(
                    messages
                )

                query_record[
                    "messages_returned"
                ] = len(
                    messages
                )

                chat_lookup = (
                    build_chat_lookup(
                        chats
                    )
                )

                local_public_count = 0

                for message in messages:
                    channel_id = peer_channel_id(
                        message
                    )

                    if channel_id is None:
                        continue

                    chat = chat_lookup.get(
                        channel_id
                    )

                    if chat is None:
                        continue

                    # Global source discovery is intentionally public-channel
                    # focused. Skip basic private chats and users.
                    is_broadcast = bool(
                        safe_attr(
                            chat,
                            "broadcast",
                            False,
                        )
                    )

                    is_megagroup = bool(
                        safe_attr(
                            chat,
                            "megagroup",
                            False,
                        )
                    )

                    if not (
                        is_broadcast
                        or is_megagroup
                    ):
                        continue

                    message_id = safe_attr(
                        message,
                        "id",
                    )

                    post_key = (
                        channel_id,
                        message_id,
                    )

                    if post_key in seen_post_keys:
                        continue

                    seen_post_keys.add(
                        post_key
                    )

                    text = str(
                        safe_attr(
                            message,
                            "message",
                            "",
                        )
                        or ""
                    ).strip()

                    if not text:
                        continue

                    local_public_count += 1

                    analysis = (
                        filter_bundle.analyze(
                            text
                        )
                    )

                    channel = (
                        channel_rows.get(
                            channel_id
                        )
                    )

                    if channel is None:
                        channel = {
                            **channel_identity(
                                chat,
                                channel_id,
                            ),
                            "query_ids": set(),
                            "query_families": set(),
                            "languages": set(),
                            "posts_matched": 0,
                            "operational_posts": 0,
                            "early_warning_posts": 0,
                            "noise_posts": 0,
                            "sample_posts": [],
                        }

                        channel_rows[
                            channel_id
                        ] = channel

                    channel[
                        "query_ids"
                    ].add(
                        query_id
                    )

                    channel[
                        "query_families"
                    ].add(
                        query_def[
                            "family"
                        ]
                    )

                    channel[
                        "languages"
                    ].add(
                        query_def[
                            "language"
                        ]
                    )

                    channel[
                        "posts_matched"
                    ] += 1

                    if analysis[
                        "operational"
                    ]:
                        channel[
                            "operational_posts"
                        ] += 1

                    if analysis[
                        "early_warning"
                    ]:
                        channel[
                            "early_warning_posts"
                        ] += 1

                    if analysis[
                        "noise"
                    ]:
                        channel[
                            "noise_posts"
                        ] += 1

                    if (
                        len(
                            channel[
                                "sample_posts"
                            ]
                        )
                        < sample_limit
                    ):
                        message_date = safe_attr(
                            message,
                            "date",
                        )

                        username = channel.get(
                            "username"
                        )

                        post_url = (
                            f"https://t.me/{username}/{message_id}"
                            if username
                            and message_id
                            else None
                        )

                        channel[
                            "sample_posts"
                        ].append(
                            {
                                "message_id":
                                    message_id,
                                "published_at": (
                                    message_date.isoformat()
                                    if message_date
                                    else None
                                ),
                                "query_id":
                                    query_id,
                                "query_family":
                                    query_def[
                                        "family"
                                    ],
                                "text":
                                    text_preview(
                                        text
                                    ),
                                "url":
                                    post_url,
                                "analysis":
                                    analysis,
                            }
                        )

                query_record[
                    "public_channel_posts"
                ] = local_public_count

                query_record[
                    "status"
                ] = "COMPLETED"

                summary[
                    "queries_completed"
                ] += 1

                query_audit.append(
                    query_record
                )

            except Exception as exc:
                query_record[
                    "status"
                ] = "FAILED"

                query_record[
                    "error"
                ] = (
                    f"{type(exc).__name__}: {exc}"
                )

                summary[
                    "queries_failed"
                ] += 1

                query_audit.append(
                    query_record
                )

        final_channels = []

        for channel in channel_rows.values():
            score, classification = source_score(
                query_ids=channel[
                    "query_ids"
                ],
                post_count=channel[
                    "posts_matched"
                ],
                operational_count=channel[
                    "operational_posts"
                ],
                early_warning_count=channel[
                    "early_warning_posts"
                ],
                noise_count=channel[
                    "noise_posts"
                ],
            )

            channel[
                "source_score"
            ] = score

            channel[
                "classification"
            ] = classification

            channel[
                "query_ids"
            ] = sorted(
                channel[
                    "query_ids"
                ]
            )

            channel[
                "query_families"
            ] = sorted(
                channel[
                    "query_families"
                ]
            )

            channel[
                "languages"
            ] = sorted(
                channel[
                    "languages"
                ]
            )

            final_channels.append(
                channel
            )

        final_channels.sort(
            key=lambda item: (
                item[
                    "source_score"
                ],
                item[
                    "operational_posts"
                ],
                item[
                    "early_warning_posts"
                ],
                item[
                    "posts_matched"
                ],
            ),
            reverse=True,
        )

        summary[
            "unique_public_channel_posts"
        ] = len(
            seen_post_keys
        )

        summary[
            "unique_channels"
        ] = len(
            final_channels
        )

        summary[
            "high_value_channels"
        ] = sum(
            1
            for item in final_channels
            if item[
                "classification"
            ] == "HIGH_VALUE"
        )

        summary[
            "review_channels"
        ] = sum(
            1
            for item in final_channels
            if item[
                "classification"
            ] == "REVIEW"
        )

        summary[
            "candidate_channels"
        ] = sum(
            1
            for item in final_channels
            if item[
                "classification"
            ] == "CANDIDATE"
        )

        return {
            "schema_version": "1.0",
            "run_type":
                "TELEGRAM_SOURCE_DISCOVERY_DIAGNOSTIC",
            "generated_at":
                utcnow_iso(),
            "started_at":
                started_at,
            "safety": {
                "database_writes":
                    False,
                "private_chats_accessed":
                    False,
                "channel_membership_changes":
                    False,
                "paid_search_allowed":
                    False,
                "paid_search_used":
                    False,
            },
            "configuration": {
                "max_queries":
                    max_queries,
                "results_per_query":
                    results_per_query,
                "sample_posts_per_channel":
                    sample_limit,
                "query_plan":
                    query_plan,
                "filter_availability":
                    filter_bundle.availability(),
            },
            "summary":
                summary,
            "query_audit":
                query_audit,
            "channels":
                final_channels,
        }

    finally:
        await client.disconnect()


def main() -> int:
    print(
        "==================================="
    )
    print(
        " TELEGRAM SOURCE DISCOVERY V1"
    )
    print(
        "==================================="
    )
    print(
        "Database writes: DISABLED"
    )
    print(
        "Private chats/groups: NOT ACCESSED"
    )
    print(
        "Paid Telegram Stars search: DISABLED"
    )
    print(
        "Production Telegram collector: NOT MODIFIED"
    )

    payload = asyncio.run(
        run_discovery()
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = payload[
        "summary"
    ]

    print(
        "-----------------------------------"
    )
    print(
        "Discovery complete."
    )
    print(
        f"Queries completed: "
        f"{summary['queries_completed']}"
    )
    print(
        f"Queries skipped (quota): "
        f"{summary['queries_skipped_no_free_quota']}"
    )
    print(
        f"Unique public posts: "
        f"{summary['unique_public_channel_posts']}"
    )
    print(
        f"Unique channels: "
        f"{summary['unique_channels']}"
    )
    print(
        f"High-value channels: "
        f"{summary.get('high_value_channels', 0)}"
    )
    print(
        f"Review channels: "
        f"{summary.get('review_channels', 0)}"
    )
    print(
        f"Candidate channels: "
        f"{summary.get('candidate_channels', 0)}"
    )
    print(
        f"JSON: {OUTPUT_PATH.name}"
    )

    top_channels = payload[
        "channels"
    ][:10]

    if top_channels:
        print(
            "-----------------------------------"
        )
        print(
            "Top discovered channels:"
        )

        for item in top_channels:
            name = (
                f"@{item['username']}"
                if item.get(
                    "username"
                )
                else item.get(
                    "title"
                )
                or str(
                    item.get(
                        "channel_id"
                    )
                )
            )

            print(
                f"{name} | "
                f"score={item['source_score']} | "
                f"class={item['classification']} | "
                f"posts={item['posts_matched']} | "
                f"operational={item['operational_posts']} | "
                f"early={item['early_warning_posts']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
