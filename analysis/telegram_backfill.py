"""
Migration OSINT Monitor

File:
analysis/telegram_backfill.py

Purpose:
One-time Telegram historical backfill using the SAME Telegram collector logic
as the normal monitor run.

Default test window:
2026-07-15 -> 2026-08-05

Required secrets:
TELEGRAM_API_ID
TELEGRAM_API_HASH
TELEGRAM_SESSION
"""

from __future__ import annotations

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
from database.models import MonitorRun

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

        TelegramHistoricalCollector.last_instance = self

        print("===================================")
        print(" TELEGRAM HISTORICAL COLLECTOR")
        print("===================================")
        print(f"Date range: {self.start_date} -> {self.end_date}")
        print(f"Max posts/day: {self.max_posts_per_day}")
        print(f"Max total posts: {self.max_total_posts}")
        print(f"Query groups: {self.query_count}")
        print(f"Fair share/query/day: {self.per_query_daily_cap}")

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
    print("Duplicate protection: EXISTING DATABASE LOGIC")

    try:
        monitor_main.XCollector = DisabledCollector
        monitor_main.RedditCollector = DisabledCollector
        monitor_main.MastodonCollector = DisabledCollector
        monitor_main.TelegramCollector = TelegramHistoricalCollector

        monitor_main.main()

    finally:
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
    print("Current normal dashboard run preserved: YES")

    if day_counts:
        print("Backfill daily counts:")
        for day_key, count in day_counts.items():
            if count:
                print(f"  {day_key}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
