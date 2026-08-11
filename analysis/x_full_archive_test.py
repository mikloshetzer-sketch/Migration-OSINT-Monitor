"""
Migration OSINT Monitor

File:
analysis/x_full_archive_test.py

Description:
X-only historical backfill runner.

This file intentionally reuses the existing Migration OSINT Monitor
pipeline in main.py instead of duplicating the analytical logic.

It replaces the normal collectors only for this process:

- XCollector       -> full-archive X collector
- RedditCollector  -> disabled collector
- MastodonCollector -> disabled collector (when present)

The collected X posts then pass through the same current pipeline used by
main.py: query definitions, noise filtering, influence detection,
operational filtering, classification, assertion filtering, event extraction,
region resolution, correlation, EventGroup processing and database storage.

Safety:
- X only
- inclusive date inputs
- shared per-day post cap
- shared total post cap
- per-query fair-share cap
- pagination cap
- existing database duplicate protection remains active
- the backfill MonitorRun is re-dated and marked BACKFILL_SUCCESS so it does
  not replace the latest normal monitor run on the dashboard
"""

from __future__ import annotations

import builtins
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


# ---------------------------------------------------------------------------
# Make repository root importable when this script is executed as:
# python analysis/x_full_archive_test.py
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(REPO_ROOT),
    )


import main as monitor_main  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models import MonitorRun  # noqa: E402


API_URL = "https://api.x.com/2/tweets/search/all"

DEFAULT_START_DATE = "2026-06-15"
DEFAULT_END_DATE = "2026-06-15"

DEFAULT_MAX_POSTS_PER_DAY = 100
DEFAULT_MAX_TOTAL_POSTS = 500
DEFAULT_MAX_PAGES_PER_QUERY_DAY = 3
DEFAULT_REQUEST_PAGE_SIZE = 100

MIN_X_PAGE_SIZE = 10
MAX_X_PAGE_SIZE = 500


def env_text(
    name: str,
    default: str,
) -> str:
    value = os.getenv(
        name,
    )

    if value is None:
        return default

    value = value.strip()

    return (
        value
        or default
    )


def env_int(
    name: str,
    default: int,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    raw = env_text(
        name,
        str(default),
    )

    try:
        value = int(
            raw
        )
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer; received {raw!r}."
        ) from exc

    value = max(
        minimum,
        value,
    )

    if maximum is not None:
        value = min(
            maximum,
            value,
        )

    return value


def env_bool(
    name: str,
    default: bool = False,
) -> bool:
    raw = os.getenv(
        name,
    )

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


def parse_iso_date(
    value: str,
) -> date:
    try:
        return date.fromisoformat(
            value
        )
    except ValueError as exc:
        raise ValueError(
            f"Invalid ISO date {value!r}. Expected YYYY-MM-DD."
        ) from exc


def utc_iso(
    value: datetime,
) -> str:
    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc,
        )

    return (
        value.astimezone(
            timezone.utc
        )
        .isoformat(
            timespec="seconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def iter_days(
    start_date: date,
    end_date: date,
) -> Iterable[date]:
    current = start_date

    while current <= end_date:
        yield current

        current += timedelta(
            days=1
        )


def historical_run_timestamp(
    end_date: date,
    previous_latest_started_at: Optional[datetime],
) -> datetime:
    """
    Returns a naive UTC timestamp for the backfill MonitorRun.

    dashboard/export_dashboard_data.py selects the newest MonitorRun by
    started_at. Backfill processing happens today, but it must not become the
    dashboard's "Current Run". We therefore move the bookkeeping timestamp
    into the historical range after main.py completes.
    """

    target = datetime.combine(
        end_date,
        time(
            23,
            59,
            0,
        ),
    )

    if previous_latest_started_at is None:
        return target

    previous = previous_latest_started_at

    if previous.tzinfo is not None:
        previous = (
            previous.astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

    if target >= previous:
        target = (
            previous
            - timedelta(
                seconds=1
            )
        )

    return target


class DisabledCollector:
    """
    Drop-in no-op collector for Reddit and Mastodon during X backfill.
    """

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        pass

    def is_configured(
        self,
    ) -> bool:
        return True

    def search_recent(
        self,
        *args,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        return []


class XFullArchiveBackfillCollector:
    """
    Drop-in XCollector replacement for main.py.

    main.py still calls search_recent(query=..., max_results=10, max_pages=1).
    For backfill we intentionally ignore those recent-search limits and use
    the separately configured historical safety budgets below.
    """

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        self.bearer_token = os.getenv(
            "X_BEARER_TOKEN",
            "",
        ).strip()

        if not self.bearer_token:
            raise RuntimeError(
                "X_BEARER_TOKEN is missing."
            )

        self.start_date = parse_iso_date(
            env_text(
                "X_BACKFILL_START_DATE",
                DEFAULT_START_DATE,
            )
        )

        self.end_date = parse_iso_date(
            env_text(
                "X_BACKFILL_END_DATE",
                DEFAULT_END_DATE,
            )
        )

        if self.end_date < self.start_date:
            raise ValueError(
                "X_BACKFILL_END_DATE must be on or after "
                "X_BACKFILL_START_DATE."
            )

        self.max_posts_per_day = env_int(
            "X_BACKFILL_MAX_POSTS_PER_DAY",
            DEFAULT_MAX_POSTS_PER_DAY,
            minimum=1,
        )

        self.max_total_posts = env_int(
            "X_BACKFILL_MAX_TOTAL_POSTS",
            DEFAULT_MAX_TOTAL_POSTS,
            minimum=1,
        )

        self.max_pages_per_query_day = env_int(
            "X_BACKFILL_MAX_PAGES_PER_QUERY_DAY",
            DEFAULT_MAX_PAGES_PER_QUERY_DAY,
            minimum=1,
            maximum=50,
        )

        self.request_page_size = env_int(
            "X_BACKFILL_REQUEST_PAGE_SIZE",
            DEFAULT_REQUEST_PAGE_SIZE,
            minimum=MIN_X_PAGE_SIZE,
            maximum=MAX_X_PAGE_SIZE,
        )

        self.query_count = env_int(
            "X_BACKFILL_QUERY_COUNT",
            1,
            minimum=1,
            maximum=100,
        )

        # Fair share prevents the first broad query from consuming the whole
        # daily budget before the more specific current query groups run.
        self.per_query_daily_cap = max(
            1,
            self.max_posts_per_day
            // self.query_count,
        )

        self.total_returned = 0
        self.day_counts = defaultdict(
            int
        )

        self.seen_post_ids = set()

        self.session = requests.Session()

        self.session.headers.update(
            {
                "Authorization":
                    f"Bearer {self.bearer_token}",
                "User-Agent":
                    (
                        "Migration-OSINT-Monitor/"
                        "X-Historical-Backfill"
                    ),
            }
        )

        print(
            "==================================="
        )
        print(
            " X FULL-ARCHIVE BACKFILL COLLECTOR"
        )
        print(
            "==================================="
        )
        print(
            f"Date range: {self.start_date} -> {self.end_date}"
        )
        print(
            f"Max posts/day: {self.max_posts_per_day}"
        )
        print(
            f"Query groups: {self.query_count}"
        )
        print(
            f"Fair-share posts/query/day: {self.per_query_daily_cap}"
        )
        print(
            f"Max total posts: {self.max_total_posts}"
        )
        print(
            "Reddit/Mastodon: DISABLED"
        )

    def is_configured(
        self,
    ) -> bool:
        return bool(
            self.bearer_token
        )

    def search_recent(
        self,
        query: str,
        max_results: int = 10,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Historical full-archive collection for one existing query group.
        """

        del max_results
        del max_pages

        if self.total_returned >= self.max_total_posts:
            print(
                "X BACKFILL GLOBAL LIMIT REACHED: "
                f"{self.max_total_posts}"
            )
            return []

        results: List[
            Dict[str, Any]
        ] = []

        for day in iter_days(
            self.start_date,
            self.end_date,
        ):
            if (
                self.total_returned
                >= self.max_total_posts
            ):
                break

            day_key = (
                day.isoformat()
            )

            remaining_day_budget = (
                self.max_posts_per_day
                - self.day_counts[
                    day_key
                ]
            )

            if remaining_day_budget <= 0:
                continue

            query_day_cap = min(
                self.per_query_daily_cap,
                remaining_day_budget,
                (
                    self.max_total_posts
                    - self.total_returned
                ),
            )

            if query_day_cap <= 0:
                continue

            day_results = (
                self._search_one_day(
                    query=query,
                    day=day,
                    limit=query_day_cap,
                )
            )

            for post in day_results:
                post_id = str(
                    post.get(
                        "post_id"
                    )
                    or ""
                )

                if (
                    not post_id
                    or post_id
                    in self.seen_post_ids
                ):
                    continue

                self.seen_post_ids.add(
                    post_id
                )

                results.append(
                    post
                )

                self.day_counts[
                    day_key
                ] += 1

                self.total_returned += 1

                if (
                    self.total_returned
                    >= self.max_total_posts
                ):
                    break

                if (
                    self.day_counts[
                        day_key
                    ]
                    >= self.max_posts_per_day
                ):
                    break

        print(
            "X BACKFILL QUERY COMPLETE: "
            f"{len(results)} unique posts returned "
            f"(global total={self.total_returned})"
        )

        return results

    def _search_one_day(
        self,
        *,
        query: str,
        day: date,
        limit: int,
    ) -> List[Dict[str, Any]]:
        start_dt = datetime.combine(
            day,
            time.min,
            tzinfo=timezone.utc,
        )

        end_dt = (
            start_dt
            + timedelta(
                days=1
            )
        )

        posts: List[
            Dict[str, Any]
        ] = []

        next_token = None
        page = 0

        while (
            len(posts) < limit
            and page
            < self.max_pages_per_query_day
        ):
            remaining = (
                limit
                - len(posts)
            )

            # X requires max_results >= 10. We may receive more than the
            # remaining local quota, but only the local quota is returned
            # into the analysis pipeline.
            page_size = min(
                self.request_page_size,
                max(
                    MIN_X_PAGE_SIZE,
                    remaining,
                ),
            )

            params = {
                "query":
                    query,
                "start_time":
                    utc_iso(
                        start_dt
                    ),
                "end_time":
                    utc_iso(
                        end_dt
                    ),
                "max_results":
                    page_size,
                "sort_order":
                    "recency",
                "tweet.fields":
                    (
                        "id,text,author_id,"
                        "created_at,lang,"
                        "conversation_id,"
                        "public_metrics"
                    ),
                "expansions":
                    "author_id",
                "user.fields":
                    (
                        "id,name,username,"
                        "verified,location"
                    ),
            }

            if next_token:
                params[
                    "next_token"
                ] = next_token

            response = (
                self.session.get(
                    API_URL,
                    params=params,
                    timeout=45,
                )
            )

            if (
                response.status_code
                != 200
            ):
                self._raise_api_error(
                    response=response,
                    day=day,
                    query=query,
                )

            payload = (
                response.json()
            )

            data = (
                payload.get(
                    "data",
                    [],
                )
                or []
            )

            includes = (
                payload.get(
                    "includes",
                    {},
                )
                or {}
            )

            users = {
                str(
                    user.get(
                        "id"
                    )
                ): user
                for user
                in (
                    includes.get(
                        "users",
                        [],
                    )
                    or []
                )
                if isinstance(
                    user,
                    dict,
                )
            }

            for tweet in data:
                normalized = (
                    self._normalize_tweet(
                        tweet=tweet,
                        users=users,
                    )
                )

                if normalized is None:
                    continue

                post_id = str(
                    normalized.get(
                        "post_id"
                    )
                    or ""
                )

                if (
                    not post_id
                    or post_id
                    in self.seen_post_ids
                ):
                    continue

                if any(
                    str(
                        item.get(
                            "post_id"
                        )
                        or ""
                    )
                    == post_id
                    for item
                    in posts
                ):
                    continue

                posts.append(
                    normalized
                )

                if (
                    len(posts)
                    >= limit
                ):
                    break

            meta = (
                payload.get(
                    "meta",
                    {},
                )
                or {}
            )

            next_token = (
                meta.get(
                    "next_token"
                )
            )

            page += 1

            if not next_token:
                break

        return posts[
            :limit
        ]

    def _normalize_tweet(
        self,
        *,
        tweet: Dict[str, Any],
        users: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        post_id = str(
            tweet.get(
                "id"
            )
            or ""
        ).strip()

        text_value = str(
            tweet.get(
                "text"
            )
            or ""
        ).strip()

        if (
            not post_id
            or not text_value
        ):
            return None

        author_id = str(
            tweet.get(
                "author_id"
            )
            or ""
        )

        user = (
            users.get(
                author_id,
                {},
            )
            or {}
        )

        username = (
            user.get(
                "username"
            )
        )

        author = (
            username
            or user.get(
                "name"
            )
            or author_id
            or None
        )

        url = (
            f"https://x.com/{username}/status/{post_id}"
            if username
            else f"https://x.com/i/web/status/{post_id}"
        )

        return {
            "source":
                "X",
            "post_id":
                post_id,
            "author_id":
                author_id
                or None,
            "author":
                author,
            "author_name":
                user.get(
                    "name"
                )
                or author,
            "author_location":
                user.get(
                    "location"
                ),
            "author_verified":
                user.get(
                    "verified"
                ),
            "text":
                text_value,
            "language":
                tweet.get(
                    "lang"
                ),
            "published_at":
                tweet.get(
                    "created_at"
                ),
            "conversation_id":
                tweet.get(
                    "conversation_id"
                )
                or post_id,
            "public_metrics":
                tweet.get(
                    "public_metrics"
                )
                or {},
            "url":
                url,
        }

    @staticmethod
    def _raise_api_error(
        *,
        response: requests.Response,
        day: date,
        query: str,
    ) -> None:
        try:
            payload = (
                response.json()
            )
        except ValueError:
            payload = {
                "raw":
                    response.text[
                        :2000
                    ],
            }

        raise RuntimeError(
            "X full-archive request failed. "
            f"HTTP={response.status_code}; "
            f"day={day}; "
            f"query={query!r}; "
            f"response={payload}"
        )


class QuietBackfillPrinter:
    """
    Optional reduced logging for large backfills.

    main.py is deliberately reused unchanged, but its normal per-post output
    can become extremely large during a multi-week historical run. In quiet
    mode we keep progress, warnings, summary values and X backfill messages.
    """

    KEEP_TERMS = (
        "===================================",
        "Migration OSINT Monitor",
        "Monitor run ID",
        "Monitor run UUID",
        "Loaded queries",
        "Historical correlation",
        "Correlation lookback",
        "Query group:",
        "Query ID:",
        "X posts found:",
        "X BACKFILL",
        "COLLECTOR WARNING",
        "WARNING:",
        "ERROR:",
        "RUN SUMMARY",
        "Posts returned by queries:",
        "Unique posts collected:",
        "X posts returned:",
        "Unique X posts:",
        "Noise filtered:",
        "Non-operational filtered:",
        "Historical references filtered:",
        "Influence signals detected:",
        "Operational events analyzed:",
        "New correlation groups:",
        "Events correlated with existing groups:",
        "New events saved to database:",
        "Events already in database:",
        "New EventGroups created:",
        "EventGroups updated:",
        "Existing EventGroups reused:",
        "EventGroup sources linked:",
        "System run completed successfully.",
    )

    def __init__(
        self,
        original_print,
    ):
        self.original_print = (
            original_print
        )

    def __call__(
        self,
        *args,
        **kwargs,
    ):
        text_value = " ".join(
            str(
                item
            )
            for item
            in args
        )

        if any(
            term
            in text_value
            for term
            in self.KEEP_TERMS
        ):
            self.original_print(
                *args,
                **kwargs,
            )


def latest_monitor_run_snapshot():
    session = get_session()

    try:
        row = (
            session.query(
                MonitorRun
            )
            .order_by(
                MonitorRun.id.desc()
            )
            .first()
        )

        if row is None:
            return {
                "max_id": 0,
                "started_at": None,
            }

        return {
            "max_id":
                int(
                    row.id
                ),
            "started_at":
                row.started_at,
        }

    finally:
        session.close()


def mark_new_runs_as_backfill(
    *,
    previous_max_id: int,
    previous_latest_started_at: Optional[datetime],
    end_date: date,
) -> List[int]:
    session = get_session()

    try:
        new_runs = (
            session.query(
                MonitorRun
            )
            .filter(
                MonitorRun.id
                > previous_max_id
            )
            .order_by(
                MonitorRun.id.asc()
            )
            .all()
        )

        if not new_runs:
            raise RuntimeError(
                "Backfill completed but no new MonitorRun row was found."
            )

        timestamp = (
            historical_run_timestamp(
                end_date=end_date,
                previous_latest_started_at=(
                    previous_latest_started_at
                ),
            )
        )

        updated_ids = []

        for run in new_runs:
            run.started_at = (
                timestamp
            )

            run.completed_at = (
                timestamp
                + timedelta(
                    seconds=1
                )
            )

            run.status = (
                "BACKFILL_SUCCESS"
            )

            updated_ids.append(
                int(
                    run.id
                )
            )

        session.commit()

        return updated_ids

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()



def verify_backfill_database(
    *,
    start_date: date,
    end_date: date,
) -> Dict[str, Any]:
    """
    Read-only database audit for the requested historical window.
    """

    db_path = (
        REPO_ROOT
        / "database"
        / "migration_osint_monitor.db"
    )

    print("===================================")
    print(" BACKFILL DATABASE VERIFICATION")
    print("===================================")
    print(f"Database: {db_path}")
    print(f"Historical window: {start_date} -> {end_date}")

    if not db_path.exists():
        print("ERROR: database file not found.")
        return {
            "database_found": False,
            "tables": {},
        }

    connection = sqlite3.connect(
        str(db_path)
    )

    report = {
        "database_found": True,
        "tables": {},
    }

    start_text = start_date.isoformat()
    end_exclusive = (
        end_date
        + timedelta(days=1)
    ).isoformat()

    date_columns = (
        "published_at",
        "event_time",
        "timestamp",
        "observed_at",
        "detected_at",
        "created_at",
        "first_detected_at",
        "last_detected_at",
        "first_seen_at",
        "last_seen_at",
    )

    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name "
                "FROM sqlite_master "
                "WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        ]

        print(
            "Tables: "
            + ", ".join(tables)
        )

        for table_name in tables:
            safe_table = (
                str(table_name)
                .replace('"', '""')
            )

            columns = [
                row[1]
                for row in connection.execute(
                    f'PRAGMA table_info("{safe_table}")'
                ).fetchall()
            ]

            table_report = {}

            for column_name in date_columns:
                if column_name not in columns:
                    continue

                safe_column = (
                    column_name
                    .replace('"', '""')
                )

                sql = (
                    f'SELECT COUNT(*), '
                    f'MIN("{safe_column}"), '
                    f'MAX("{safe_column}") '
                    f'FROM "{safe_table}" '
                    f'WHERE "{safe_column}" IS NOT NULL '
                    f'AND datetime("{safe_column}") >= datetime(?) '
                    f'AND datetime("{safe_column}") < datetime(?)'
                )

                try:
                    row = connection.execute(
                        sql,
                        (
                            start_text,
                            end_exclusive,
                        ),
                    ).fetchone()
                except sqlite3.Error as error:
                    table_report[column_name] = {
                        "error": str(error),
                    }
                    continue

                count = int(
                    row[0]
                    if row
                    else 0
                )

                if count <= 0:
                    continue

                table_report[column_name] = {
                    "count": count,
                    "oldest": row[1],
                    "newest": row[2],
                }

            if table_report:
                report["tables"][table_name] = table_report

        if not report["tables"]:
            print(
                "RESULT: ZERO historical rows found "
                "inside the requested date range."
            )
        else:
            for table_name, table_report in report["tables"].items():
                print("-----------------------------------")
                print(f"Table: {table_name}")

                for column_name, values in table_report.items():
                    if "count" not in values:
                        print(
                            f"  {column_name}: ERROR "
                            f"{values.get('error')}"
                        )
                        continue

                    print(
                        f"  {column_name}: "
                        f"{values['count']} rows"
                    )
                    print(
                        f"    oldest: "
                        f"{values['oldest']}"
                    )
                    print(
                        f"    newest: "
                        f"{values['newest']}"
                    )

        likely_collected = [
            name
            for name in (
                "collected_posts",
                "collected_post",
            )
            if name in report["tables"]
        ]

        likely_signals = [
            name
            for name in (
                "influence_signals",
                "influence_signal",
            )
            if name in report["tables"]
        ]

        likely_events = [
            name
            for name in (
                "posts",
                "events",
            )
            if name in report["tables"]
        ]

        print("-----------------------------------")
        print("INTERPRETATION")

        if not likely_collected:
            print(
                "No historical CollectedPost rows were found. "
                "The problem is in X collection or persistence."
            )
        else:
            print(
                "Historical CollectedPost rows exist."
            )

            if (
                likely_signals
                or likely_events
            ):
                print(
                    "Historical signal/event rows also exist. "
                    "If the dashboard is still empty, "
                    "the next target is the exporter."
                )
            else:
                print(
                    "No historical signal/event rows were found "
                    "under the canonical table names. "
                    "The analytical filters may have rejected all "
                    "historical posts, or the event table has another name."
                )

        return report

    finally:
        connection.close()



def main() -> int:
    start_date = parse_iso_date(
        env_text(
            "X_BACKFILL_START_DATE",
            DEFAULT_START_DATE,
        )
    )

    end_date = parse_iso_date(
        env_text(
            "X_BACKFILL_END_DATE",
            DEFAULT_END_DATE,
        )
    )

    if end_date < start_date:
        raise ValueError(
            "End date must be on or after start date."
        )

    # Read the current query count before the collectors are replaced.
    query_engine = (
        monitor_main.QueryEngine()
    )

    query_definitions = (
        query_engine.load_queries()
    )

    query_count = max(
        1,
        len(
            query_definitions
        ),
    )

    os.environ[
        "X_BACKFILL_QUERY_COUNT"
    ] = str(
        query_count
    )

    previous = (
        latest_monitor_run_snapshot()
    )

    original_x_collector = (
        monitor_main.XCollector
    )

    original_reddit_collector = getattr(
        monitor_main,
        "RedditCollector",
        None,
    )

    original_mastodon_collector = getattr(
        monitor_main,
        "MastodonCollector",
        None,
    )

    original_module_print = getattr(
        monitor_main,
        "print",
        None,
    )

    quiet = env_bool(
        "X_BACKFILL_QUIET",
        False,
    )

    print(
        "==================================="
    )
    print(
        " X HISTORICAL BACKFILL"
    )
    print(
        "==================================="
    )
    print(
        f"Start date: {start_date}"
    )
    print(
        f"End date:   {end_date}"
    )
    print(
        f"Existing query groups reused: {query_count}"
    )
    print(
        "Analytical pipeline: CURRENT main.py"
    )
    print(
        "Sources: X ONLY"
    )
    print(
        "Database writes: ENABLED"
    )
    print(
        "Duplicate protection: EXISTING DATABASE LOGIC"
    )
    print(
        f"Quiet log mode: {quiet}"
    )

    try:
        # Monkeypatch only this Python process. Repository source files and
        # normal workflow behavior remain unchanged.
        monitor_main.XCollector = (
            XFullArchiveBackfillCollector
        )

        if (
            original_reddit_collector
            is not None
        ):
            monitor_main.RedditCollector = (
                DisabledCollector
            )

        if (
            original_mastodon_collector
            is not None
        ):
            monitor_main.MastodonCollector = (
                DisabledCollector
            )

        if quiet:
            monitor_main.print = (
                QuietBackfillPrinter(
                    builtins.print
                )
            )

        monitor_main.main()

    finally:
        monitor_main.XCollector = (
            original_x_collector
        )

        if (
            original_reddit_collector
            is not None
        ):
            monitor_main.RedditCollector = (
                original_reddit_collector
            )

        if (
            original_mastodon_collector
            is not None
        ):
            monitor_main.MastodonCollector = (
                original_mastodon_collector
            )

        if (
            original_module_print
            is None
        ):
            try:
                delattr(
                    monitor_main,
                    "print",
                )
            except AttributeError:
                pass
        else:
            monitor_main.print = (
                original_module_print
            )

    updated_ids = (
        mark_new_runs_as_backfill(
            previous_max_id=(
                previous[
                    "max_id"
                ]
            ),
            previous_latest_started_at=(
                previous[
                    "started_at"
                ]
            ),
            end_date=end_date,
        )
    )

    verify_backfill_database(
        start_date=start_date,
        end_date=end_date,
    )

    print(
        "==================================="
    )
    print(
        " BACKFILL COMPLETE"
    )
    print(
        "==================================="
    )
    print(
        "Backfill MonitorRun IDs: "
        f"{updated_ids}"
    )
    print(
        "Backfill run status: BACKFILL_SUCCESS"
    )
    print(
        "Current normal dashboard run preserved: YES"
    )
    print(
        "Next step: export dashboard-data.json."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
