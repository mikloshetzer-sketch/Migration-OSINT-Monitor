
"""
Migration OSINT Monitor
Source Intelligence Exporter

Reads already collected posts from the existing SQLite database.
Classifies their publishers using the verified source registry.
Exports results to a separate JSON file.

Does not modify the existing database or dashboard.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.source_classifier import (
    classify_source,
    summarize_categories,
)

DATABASE_PATH = PROJECT_ROOT / "database" / "migration_osint_monitor.db"
REGISTRY_PATH = PROJECT_ROOT / "config" / "source_registry.json"
OUTPUT_PATH = PROJECT_ROOT / "source-intelligence.json"

CATEGORIES = (
    "PRIVATE_PERSON",
    "GOVERNMENT",
    "ORGANIZATION",
    "MEDIA",
    "UNKNOWN",
)


def load_registry():
    """Load the verified publisher registry."""
    with REGISTRY_PATH.open("r", encoding="utf-8") as file:
        registry = json.load(file)

    if not isinstance(registry, dict):
        raise ValueError("Source registry must be a JSON object.")

    return registry


def load_collected_posts():
    """Read existing posts without changing the database."""

    if not DATABASE_PATH.is_file():
        raise FileNotFoundError(
            f"Existing monitor database not found: {DATABASE_PATH}"
        )

    database_uri = (
        f"{DATABASE_PATH.resolve().as_uri()}?mode=ro"
    )

    connection = sqlite3.connect(
        database_uri,
        uri=True,
    )
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT
                source,
                source_post_id,
                author,
                published_at,
                first_collected_at,
                url
            FROM collected_posts
            ORDER BY first_collected_at ASC, id ASC
            """
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


def normalize_day(value):
    """Return the date portion of an existing timestamp."""

    if not value:
        return None

    try:
        normalized = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)

        return parsed.date().isoformat()

    except (ValueError, TypeError):
        return None


def build_daily_history(items):
    """Count unique collected posts by publication date."""

    daily = {}

    for item in items:
        day = item.get("published_day")

        if not day:
            continue

        if day not in daily:
            daily[day] = {
                category: 0
                for category in CATEGORIES
            }

        category = item["publisher_category"]
        daily[day][category] += 1

    return [
        {
            "date": day,
            "total": sum(counts.values()),
            "categories": counts,
        }
        for day, counts in sorted(daily.items())
    ]


def build_export(posts, registry):
    """Build the source intelligence output."""

    classifications = []

    for post in posts:
        classification = classify_source(
            post,
            registry=registry,
        )

        classification["published_at"] = (
            str(post.get("published_at") or "") or None
        )

        classification["published_day"] = normalize_day(
            post.get("published_at")
        )

        classification["first_collected_at"] = (
            str(post.get("first_collected_at") or "") or None
        )

        classifications.append(classification)

    return {
        "schema_version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_posts": len(classifications),
        "category_summary": summarize_categories(
            classifications
        ),
        "daily_history": build_daily_history(
            classifications
        ),
        "posts": classifications,
    }


def save_export(data):
    """Atomically replace only the separate export file."""

    temporary_path = OUTPUT_PATH.with_suffix(".json.tmp")

    try:
        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(temporary_path, OUTPUT_PATH)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main():
    registry = load_registry()
    posts = load_collected_posts()

    export_data = build_export(posts, registry)
    save_export(export_data)

    print("Source Intelligence export completed.")
    print(f"Existing posts processed: {len(posts)}")
    print(f"Output: {OUTPUT_PATH}")

    for category, count in export_data[
        "category_summary"
    ].items():
        print(f"{category}: {count}")


if __name__ == "__main__":
    main()
