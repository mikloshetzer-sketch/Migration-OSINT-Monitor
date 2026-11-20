
"""
Migration OSINT Monitor
Hotspot Map Exporter - V1

Creates hotspot-map.json from dashboard-data.json.

The output supports:
- Seven-day map windows
- Previous / next week navigation
- Latest seven days for blog embedding
- Geographic hotspot markers
- Separate counts for unresolved locations

Only verified coordinates from the exported data
are plotted. Unknown locations are not geocoded
or assigned invented coordinates.

V1 uses the existing signal_timeline export.
Historical completeness is limited by that export.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = ROOT / "dashboard-data.json"
OUTPUT_FILE = ROOT / "hotspot-map.json"

VALID_LAYERS = {
    "INFORMATION",
    "EARLY_WARNING",
    "OPERATIONAL",
    "CORRELATED",
}

INVALID_LOCATIONS = {
    "",
    "-",
    "unknown",
    "unresolved",
    "global",
    "none",
    "null",
}


def parse_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).date()
    except (TypeError, ValueError):
        return None


def valid_coordinates(item):
    lat = item.get("latitude")
    lon = item.get("longitude")

    if lat is None or lon is None:
        return None

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    if not (-90 <= lat <= 90):
        return None

    if not (-180 <= lon <= 180):
        return None

    # Reject default placeholder coordinates.
    if lat == 0 and lon == 0:
        return None

    return [lat, lon]


def clean_text(value):
    return str(value or "").strip()


def build_hotspot_map(data):
    timeline = data.get("signal_timeline", {})

    if isinstance(timeline, dict):
        items = timeline.get("items", [])
    elif isinstance(timeline, list):
        items = timeline
    else:
        items = []

    if not isinstance(items, list):
        items = []

    points = []
    unresolved = defaultdict(int)
    daily = defaultdict(lambda: {
        "total": 0,
        "mapped": 0,
        "unresolved": 0,
        "layers": defaultdict(int),
    })

    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        layer = clean_text(
            item.get("layer")
        ).upper()

        if layer not in VALID_LAYERS:
            continue

        date = parse_date(item.get("timestamp"))

        if date is None:
            continue

        day = date.isoformat()

        timeline_id = clean_text(
            item.get("timeline_id")
        )

        if timeline_id:
            if timeline_id in seen:
                continue
            seen.add(timeline_id)

        daily[day]["total"] += 1
        daily[day]["layers"][layer] += 1

        location = clean_text(
            item.get("primary_location")
            or item.get("location")
        )

        country = clean_text(
            item.get("country")
        )

        region = clean_text(
            item.get("primary_region")
            or item.get("region")
        )

        coordinates = valid_coordinates(item)

        if coordinates is None:
            daily[day]["unresolved"] += 1
            unresolved[day] += 1
            continue

        if location.lower() in INVALID_LOCATIONS:
            location = country or region or "Unnamed location"

        points.append({
            "id": timeline_id,
            "date": day,
            "timestamp": item.get("timestamp"),
            "latitude": coordinates[0],
            "longitude": coordinates[1],
            "location": location,
            "country": country,
            "region": region,
            "layer": layer,
            "event_type": (
                item.get("event_type")
                or item.get("signal_type")
                or item.get("type")
            ),
            "confidence": item.get("confidence"),
            "source": item.get("source"),
            "source_url": (
                item.get("source_url")
                or item.get("url")
            ),
        })

        daily[day]["mapped"] += 1

    points.sort(
        key=lambda x: (x["date"], x["id"]),
        reverse=True,
    )

    daily_output = []

    for day in sorted(daily):
        stats = daily[day]

        daily_output.append({
            "date": day,
            "total": stats["total"],
            "mapped": stats["mapped"],
            "unresolved": stats["unresolved"],
            "layers": dict(stats["layers"]),
        })

    today = datetime.now(timezone.utc).date()

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "source": "dashboard-data.json",
        "date_basis": "source_post_timestamp_utc",
        "latest_date": today.isoformat(),
        "window_days": 7,
        "historical_completeness": (
            "limited_by_signal_timeline_export"
        ),
        "points": points,
        "daily": daily_output,
        "unresolved_by_day": dict(unresolved),
        "summary": {
            "total_items": sum(
                x["total"] for x in daily_output
            ),
            "mapped_items": len(points),
            "unresolved_items": sum(
                unresolved.values()
            ),
            "days_with_data": len(daily_output),
        },
    }


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Missing input: {INPUT_FILE}"
        )

    with INPUT_FILE.open(
        "r", encoding="utf-8"
    ) as file:
        data = json.load(file)

    result = build_hotspot_map(data)

    with OUTPUT_FILE.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("HOTSPOT MAP EXPORT COMPLETE")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Mapped items: {result['summary']['mapped_items']}")
    print(
        "Unresolved items: "
        f"{result['summary']['unresolved_items']}"
    )


if __name__ == "__main__":
    main()
