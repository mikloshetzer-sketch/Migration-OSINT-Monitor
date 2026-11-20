"""Export daily dominant hotspots for the Migration OSINT Matrix map.

Uses the same dominant-region/location selection rules as index.html's
matrixResolvedHotspot(). No changes to the source database or dashboard.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = ROOT / "dashboard-data.json"
LOCATIONS_FILE = ROOT / "config" / "locations.json"
OUTPUT_FILE = ROOT / "hotspot-map.json"

# These are illustrative region markers, NOT event coordinates.
REGION_MARKERS = {
    "WESTERN_MEDITERRANEAN": (36.0, -4.0),
    "CENTRAL_MEDITERRANEAN": (35.7, 13.0),
    "EASTERN_MEDITERRANEAN": (35.0, 28.0),
    "SAHEL": (16.0, -2.0),
}
INVALID = {"", "-", "GLOBAL", "UNRESOLVED", "UNKNOWN", "NONE", "NULL"}


def clean(value):
    return str(value or "").strip()


def utc_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def location_lookup():
    if not LOCATIONS_FILE.exists():
        return {}
    with LOCATIONS_FILE.open(encoding="utf-8") as f:
        records = json.load(f)
    lookup = {}
    for loc in records if isinstance(records, list) else []:
        try:
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        for name in [loc.get("name"), *(loc.get("aliases") or [])]:
            if clean(name):
                lookup[clean(name).casefold()] = (lat, lon)
    return lookup


def dominant_hotspot(items):
    """Mirror matrixResolvedHotspot() in the dashboard's index.html."""
    if not items:
        return None
    analytical = [x for x in items if clean(x.get("layer")).upper() != "INFORMATION"]
    base = analytical if analytical else items

    region_counts = Counter()
    for item in base:
        region = clean(item.get("primary_region") or item.get("region"))
        upper = region.upper()
        if region and region != "-" and upper != "GLOBAL" and "UNRESOLVED" not in upper:
            region_counts[region] += 1
    # Python Counter preserves insertion order; ties follow first occurrence,
    # like the stable JavaScript sort used in the matrix.
    region = region_counts.most_common(1)[0][0] if region_counts else None
    selected = [x for x in base if clean(x.get("primary_region") or x.get("region")) == region] if region else base

    locations = Counter()
    sources = Counter()
    for item in selected:
        loc = clean(item.get("primary_location") or item.get("location"))
        if loc and loc != "-":
            locations[loc] += 1
        sources[clean(item.get("source") or "UNKNOWN").upper()] += 1

    return {
        "region": region or "Unresolved / Global",
        "location": locations.most_common(1)[0][0] if locations else None,
        "records": len(selected),
        "sources": dict(sources),
    }


def marker_for(hotspot, locations):
    name = hotspot["location"]
    if name and name.casefold() in locations:
        lat, lon = locations[name.casefold()]
        return {"latitude": lat, "longitude": lon, "precision": "configured_location"}
    region = hotspot["region"].upper().replace(" ", "_")
    if region in REGION_MARKERS:
        lat, lon = REGION_MARKERS[region]
        return {"latitude": lat, "longitude": lon, "precision": "illustrative_region"}
    return None


def build(data):
    timeline = data.get("signal_timeline") or {}
    items = timeline.get("items", []) if isinstance(timeline, dict) else timeline
    if not isinstance(items, list):
        raise ValueError("signal_timeline.items must be a list")

    grouped = defaultdict(list)
    for item in items:
        if isinstance(item, dict):
            day = utc_date(item.get("timestamp"))
            if day:
                grouped[day].append(item)

    lookup = location_lookup()
    daily = []
    for day in sorted(grouped):
        hotspot = dominant_hotspot(grouped[day])
        if hotspot is None:
            continue
        marker = marker_for(hotspot, lookup)
        daily.append({
            "date": day,
            **hotspot,
            "marker": marker,
            "total_timeline_items": len(grouped[day]),
        })

    # Pre-compute seven-day windows ending on each available day.
    # The UI can also select any 7-day range from `daily_hotspots`.
    weeks = []
    for end_day in sorted(grouped):
        end = datetime.strptime(end_day, "%Y-%m-%d").date()
        start = (end - timedelta(days=6)).isoformat()
        window = [x for x in daily if start <= x["date"] <= end_day]
        top = {}
        unresolved = 0
        for row in window:
            if row["region"] == "Unresolved / Global":
                unresolved += row["records"]
                continue
            key = (row["region"], row["location"] or "")
            if key not in top:
                top[key] = {
                    "region": row["region"],
                    "location": row["location"],
                    "records": 0,
                    "active_days": 0,
                    "dates": [],
                    "marker": row["marker"],
                }
            entry = top[key]
            entry["records"] += row["records"]
            entry["active_days"] += 1
            entry["dates"].append(row["date"])
            if entry["marker"] is None and row["marker"] is not None:
                entry["marker"] = row["marker"]
        top_list = sorted(top.values(), key=lambda x: (-x["records"], x["region"], x["location"] or ""))
        weeks.append({
            "start_date": start,
            "end_date": end_day,
            "hotspots": top_list,
            "unresolved_records": unresolved,
        })

    generated = datetime.now(timezone.utc)
    latest_end = generated.date().isoformat()
    latest_week = next((x for x in weeks if x["end_date"] == latest_end), None)
    if latest_week is None:
        # No timeline record for today: the most recent available window
        # remains accessible, but is not presented as current-week data.
        latest_week = {"start_date": (generated.date() - timedelta(days=6)).isoformat(),
                       "end_date": latest_end, "hotspots": [],
                       "unresolved_records": 0, "status": "no_data_for_today"}

    return {
        "schema_version": "2.0",
        "generated_at": generated.isoformat(),
        "source": "dashboard-data.json / signal_timeline.items",
        "date_basis": "UTC source publication date; dashboard uses browser local dates",
        "selection": "daily dominant hotspot, matching matrixResolvedHotspot",
        "coverage_note": "History is limited by the source timeline window and item limits",
        "daily_hotspots": daily,
        "seven_day_windows": weeks,
        "latest_window": latest_week,
        "summary": {"days_with_data": len(daily), "available_windows": len(weeks)},
    }


def main():
    with INPUT_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    result = build(data)
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("HOTSPOT MAP EXPORT COMPLETE")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Days with hotspot: {result['summary']['days_with_data']}")
    print(f"Available seven-day windows: {result['summary']['available_windows']}")


if __name__ == "__main__":
    main()
