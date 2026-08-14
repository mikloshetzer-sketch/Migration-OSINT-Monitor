"""
Offline rescoring utility for Telegram Source Discovery V2.

Use this to test the V2 scoring logic on an existing V1 discovery JSON
without consuming Telegram global-search quota.

Usage:
    python analysis/telegram_source_discovery_v2_rescore.py \
        telegram-source-discovery.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from telegram_source_discovery_v2 import (
    FilterBundle,
    score_source,
)

OUTPUT_PATH = Path("telegram-source-discovery-v2-rescore.json")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: telegram_source_discovery_v2_rescore.py "
            "<telegram-source-discovery.json>"
        )

    source_path = Path(sys.argv[1])
    data = json.loads(source_path.read_text(encoding="utf-8"))

    filters = FilterBundle()
    rescored = []

    for channel in data.get("channels", []):
        row = {
            "channel_id": channel.get("channel_id"),
            "username": channel.get("username"),
            "title": channel.get("title"),
            "url": channel.get("url"),
            "query_ids": set(channel.get("query_ids", []) or []),
            "query_families": set(channel.get("query_families", []) or []),
            "languages": set(channel.get("languages", []) or []),
            "posts_matched": 0,
            "migration_relevant_posts": 0,
            "geographic_posts": 0,
            "operational_posts": 0,
            "early_warning_posts": 0,
            "precursor_posts": 0,
            "useful_posts": 0,
            "noise_posts": 0,
            "inaccessible_posts": 0,
            "sample_posts": [],
        }

        for sample in channel.get("sample_posts", []) or []:
            text = str(sample.get("text") or "")
            if not text:
                continue

            analysis = filters.analyze(text)

            row["posts_matched"] += 1
            if analysis["migration_relevance"]:
                row["migration_relevant_posts"] += 1
            if analysis["geographic_specificity"]:
                row["geographic_posts"] += 1
            if analysis["operational"]:
                row["operational_posts"] += 1
            if analysis["early_warning"]:
                row["early_warning_posts"] += 1
            if analysis["precursor"]:
                row["precursor_posts"] += 1
            if analysis["noise"]:
                row["noise_posts"] += 1
            if analysis["inaccessible_placeholder"]:
                row["inaccessible_posts"] += 1

            if (
                analysis["operational"]
                or analysis["early_warning"]
                or analysis["precursor"]
            ):
                row["useful_posts"] += 1

            row["sample_posts"].append(
                {
                    **sample,
                    "analysis_v2": analysis,
                }
            )

        score, classification, components, reasons = score_source(row)

        row["source_score"] = score
        row["classification"] = classification
        row["score_components"] = components
        row["classification_reasons"] = reasons
        row["query_ids"] = sorted(row["query_ids"])
        row["query_families"] = sorted(row["query_families"])
        row["languages"] = sorted(row["languages"])

        rescored.append(row)

    rescored.sort(
        key=lambda item: (
            item["source_score"],
            item["precursor_posts"],
            item["operational_posts"],
            item["early_warning_posts"],
        ),
        reverse=True,
    )

    summary = {
        "channels_rescored": len(rescored),
        "high_value_channels": sum(
            1 for row in rescored if row["classification"] == "HIGH_VALUE"
        ),
        "watch_channels": sum(
            1 for row in rescored if row["classification"] == "WATCH"
        ),
        "candidate_channels": sum(
            1 for row in rescored if row["classification"] == "CANDIDATE"
        ),
        "reject_channels": sum(
            1 for row in rescored if row["classification"] == "REJECT"
        ),
        "channels_with_precursor_posts": sum(
            1 for row in rescored if row["precursor_posts"] > 0
        ),
    }

    payload = {
        "schema_version": "2.0-offline-rescore",
        "source_file": str(source_path),
        "summary": summary,
        "channels": rescored,
    }

    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("V2 offline rescore complete.")
    print(summary)
    print("JSON:", OUTPUT_PATH)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
