"""
Migration OSINT Monitor

File:
export_dashboard_data.py

Description:
Exports dashboard-ready JSON data from the existing SQLite database.

The generated dashboard-data.json file is consumed by the
static GitHub Pages dashboard.

Exported sections:

- updated_at
- kpis
- live_events
- event_groups
- region_activity
- source_activity
- correlation
- operational_assessment
- high_confidence_events
"""

import json

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from database.database import get_session
from database.models import (
    Post,
    EventGroup,
    EventGroupSource,
)


# ==========================================================
# PATHS
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "dashboard-data.json"
)


# ==========================================================
# CONSTANTS
# ==========================================================

RECENT_HOURS = 24

LIVE_EVENT_LIMIT = 20

EVENT_GROUP_LIMIT = 10

HIGH_CONFIDENCE_LIMIT = 10

HIGH_CONFIDENCE_THRESHOLD = 0.75


# ==========================================================
# TIME HELPERS
# ==========================================================

def utc_now():
    """
    Returns current UTC time as naive datetime.

    The existing SQLite schema currently uses
    naive DateTime fields.
    """

    return (
        datetime.now(
            timezone.utc
        )
        .replace(
            tzinfo=None
        )
    )


def recent_cutoff(
    hours=RECENT_HOURS,
):
    """
    Returns the datetime cutoff used for recent statistics.
    """

    return (
        utc_now()
        - timedelta(
            hours=hours
        )
    )


# ==========================================================
# SAFE CONVERSION
# ==========================================================

def safe_int(
    value,
    default=0,
):
    """
    Safely converts a value to int.
    """

    if value is None:
        return default

    try:
        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_float(
    value,
    default=0.0,
):
    """
    Safely converts a value to float.
    """

    if value is None:
        return default

    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_percent(
    numerator,
    denominator,
):
    """
    Returns percentage safely.
    """

    numerator = safe_float(
        numerator
    )

    denominator = safe_float(
        denominator
    )

    if denominator <= 0:
        return 0.0

    return round(
        (
            numerator
            / denominator
        )
        * 100,
        2,
    )


# ==========================================================
# FORMAT HELPERS
# ==========================================================

def format_datetime(
    value,
):
    """
    Converts datetime values to a JSON-friendly UTC string.
    """

    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    return str(
        value
    )


def deserialize_source_types(
    value,
):
    """
    Reads JSON stored in EventGroup.source_types.
    """

    if not value:
        return []

    try:
        result = json.loads(
            value
        )

        if isinstance(
            result,
            list,
        ):
            return result

    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        pass

    return []


# ==========================================================
# KPI
# ==========================================================

def get_kpis(
    session,
):
    """
    Builds top dashboard KPI values.
    """

    cutoff = recent_cutoff()

    operational_events = (
        session.execute(
            select(
                func.count(
                    Post.id
                )
            )
            .where(
                Post.signal_type
                .is_not(None)
            )
            .where(
                Post.collected_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    active_event_groups = (
        session.execute(
            select(
                func.count(
                    EventGroup.id
                )
            )
            .where(
                EventGroup.status
                == "ACTIVE"
            )
        )
        .scalar_one()
    )

    sources = (
        session.execute(
            select(
                func.count(
                    func.distinct(
                        Post.source
                    )
                )
            )
            .where(
                Post.signal_type
                .is_not(None)
            )
        )
        .scalar_one()
    )

    correlated_events = (
        session.execute(
            select(
                func.count(
                    EventGroupSource.id
                )
            )
            .where(
                EventGroupSource.correlation_score
                .is_not(None)
            )
            .where(
                EventGroupSource.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    grouped_sources = (
        session.execute(
            select(
                func.count(
                    EventGroupSource.id
                )
            )
            .where(
                EventGroupSource.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    new_events = max(
        safe_int(
            grouped_sources
        )
        - safe_int(
            correlated_events
        ),
        0,
    )

    region_values = (
        session.execute(
            select(
                EventGroup.primary_region
            )
            .where(
                EventGroup.primary_region
                .is_not(None)
            )
            .where(
                EventGroup.primary_region
                != "GLOBAL"
            )
        )
        .scalars()
        .all()
    )

    regions = len(
        set(
            region_values
        )
    )

    return {
        "operational_events": safe_int(
            operational_events
        ),
        "new_events": safe_int(
            new_events
        ),
        "correlated_events": safe_int(
            correlated_events
        ),
        "active_event_groups": safe_int(
            active_event_groups
        ),
        "sources": safe_int(
            sources
        ),
        "regions": safe_int(
            regions
        ),
    }


# ==========================================================
# LIVE EVENTS
# ==========================================================

def get_live_events(
    session,
):
    """
    Returns the latest operational posts.
    """

    rows = (
        session.execute(
            select(
                Post,
                EventGroupSource.event_group_id,
                EventGroupSource.correlation_score,
            )
            .outerjoin(
                EventGroupSource,
                (
                    EventGroupSource.source
                    == Post.source
                )
                & (
                    EventGroupSource.source_post_id
                    == Post.post_id
                ),
            )
            .where(
                Post.signal_type
                .is_not(None)
            )
            .order_by(
                Post.published_at.desc()
            )
            .limit(
                LIVE_EVENT_LIMIT
            )
        )
        .all()
    )

    results = []

    for (
        post,
        event_group_id,
        correlation_score,
    ) in rows:

        results.append(
            {
                "id": post.id,

                "event_group_id": (
                    event_group_id
                ),

                "published_at": format_datetime(
                    post.published_at
                ),

                "event_type": (
                    post.signal_type
                ),

                "location": (
                    post.locations
                    or "-"
                ),

                "confidence": safe_float(
                    post.extraction_confidence
                ),

                "source": (
                    post.source
                    or "UNKNOWN"
                ),

                "author": (
                    post.author
                    or "-"
                ),

                "text": (
                    post.text
                    or ""
                ),

                "url": (
                    post.url
                    or ""
                ),

                "correlation_score": (
                    safe_float(
                        correlation_score
                    )
                    if correlation_score
                    is not None
                    else None
                ),
            }
        )

    return results


# ==========================================================
# EVENT GROUPS
# ==========================================================

def get_event_groups(
    session,
):
    """
    Returns the most active event groups.
    """

    groups = (
        session.execute(
            select(
                EventGroup
            )
            .order_by(
                EventGroup.source_count.desc(),
                EventGroup.last_seen.desc(),
            )
            .limit(
                EVENT_GROUP_LIMIT
            )
        )
        .scalars()
        .all()
    )

    results = []

    for group in groups:

        results.append(
            {
                "id": group.id,

                "event_type": (
                    group.event_type
                ),

                "title": (
                    group.title
                    or ""
                ),

                "primary_region": (
                    group.primary_region
                    or "GLOBAL"
                ),

                "primary_location": (
                    group.primary_location
                    or "-"
                ),

                "country": (
                    group.country
                    or "-"
                ),

                "first_seen": format_datetime(
                    group.first_seen
                ),

                "last_seen": format_datetime(
                    group.last_seen
                ),

                "source_count": safe_int(
                    group.source_count
                ),

                "source_types": (
                    deserialize_source_types(
                        group.source_types
                    )
                ),

                "status": (
                    group.status
                    or "ACTIVE"
                ),

                "confidence": safe_float(
                    group.confidence
                ),

                "representative_text": (
                    group.representative_text
                    or ""
                ),
            }
        )

    return results


# ==========================================================
# REGION ACTIVITY
# ==========================================================

def get_region_activity(
    session,
):
    """
    Groups EventGroups by primary region.
    """

    rows = (
        session.execute(
            select(
                EventGroup.primary_region,
                func.count(
                    EventGroup.id
                ),
            )
            .group_by(
                EventGroup.primary_region
            )
            .order_by(
                func.count(
                    EventGroup.id
                ).desc()
            )
        )
        .all()
    )

    return [
        {
            "region": (
                region
                or "GLOBAL"
            ),
            "count": safe_int(
                count
            ),
        }
        for region, count in rows
    ]


# ==========================================================
# SOURCE ACTIVITY
# ==========================================================

def get_source_activity(
    session,
):
    """
    Groups operational posts by source.
    """

    rows = (
        session.execute(
            select(
                Post.source,
                func.count(
                    Post.id
                ),
            )
            .where(
                Post.signal_type
                .is_not(None)
            )
            .group_by(
                Post.source
            )
            .order_by(
                func.count(
                    Post.id
                ).desc()
            )
        )
        .all()
    )

    return [
        {
            "source": (
                source
                or "UNKNOWN"
            ),
            "count": safe_int(
                count
            ),
        }
        for source, count in rows
    ]


# ==========================================================
# CORRELATION PERFORMANCE
# ==========================================================

def get_correlation_performance(
    session,
):
    """
    Returns high-level event processing statistics
    and derived efficiency metrics.
    """

    total_posts = (
        session.execute(
            select(
                func.count(
                    Post.id
                )
            )
        )
        .scalar_one()
    )

    operational_events = (
        session.execute(
            select(
                func.count(
                    Post.id
                )
            )
            .where(
                Post.signal_type
                .is_not(None)
            )
        )
        .scalar_one()
    )

    correlated_sources = (
        session.execute(
            select(
                func.count(
                    EventGroupSource.id
                )
            )
            .where(
                EventGroupSource.correlation_score
                .is_not(None)
            )
        )
        .scalar_one()
    )

    grouped_sources = (
        session.execute(
            select(
                func.count(
                    EventGroupSource.id
                )
            )
        )
        .scalar_one()
    )

    event_groups = (
        session.execute(
            select(
                func.count(
                    EventGroup.id
                )
            )
        )
        .scalar_one()
    )

    total_posts = safe_int(
        total_posts
    )

    operational_events = safe_int(
        operational_events
    )

    correlated_sources = safe_int(
        correlated_sources
    )

    grouped_sources = safe_int(
        grouped_sources
    )

    event_groups = safe_int(
        event_groups
    )

    filtered_posts = max(
        total_posts
        - operational_events,
        0,
    )

    filtering_efficiency = (
        safe_percent(
            filtered_posts,
            total_posts,
        )
    )

    operational_rate = (
        safe_percent(
            operational_events,
            total_posts,
        )
    )

    correlation_rate = (
        safe_percent(
            correlated_sources,
            operational_events,
        )
    )

    grouping_rate = (
        safe_percent(
            event_groups,
            operational_events,
        )
    )

    multi_source_rate = (
        safe_percent(
            correlated_sources,
            grouped_sources,
        )
    )

    conversion_rate = (
        safe_percent(
            event_groups,
            operational_events,
        )
    )

    return {
        "total_posts": total_posts,

        "filtered_posts": filtered_posts,

        "operational_events": (
            operational_events
        ),

        "correlated_sources": (
            correlated_sources
        ),

        "grouped_sources": (
            grouped_sources
        ),

        "event_groups": (
            event_groups
        ),

        "filtering_efficiency": (
            filtering_efficiency
        ),

        "operational_rate": (
            operational_rate
        ),

        "correlation_rate": (
            correlation_rate
        ),

        "grouping_rate": (
            grouping_rate
        ),

        "multi_source_rate": (
            multi_source_rate
        ),

        "conversion_rate": (
            conversion_rate
        ),
    }


# ==========================================================
# HIGH CONFIDENCE
# ==========================================================

def get_high_confidence_events(
    session,
):
    """
    Returns high-confidence EventGroups.
    """

    groups = (
        session.execute(
            select(
                EventGroup
            )
            .where(
                EventGroup.confidence
                .is_not(None)
            )
            .where(
                EventGroup.confidence
                >= HIGH_CONFIDENCE_THRESHOLD
            )
            .order_by(
                EventGroup.confidence.desc(),
                EventGroup.last_seen.desc(),
            )
            .limit(
                HIGH_CONFIDENCE_LIMIT
            )
        )
        .scalars()
        .all()
    )

    results = []

    for group in groups:

        results.append(
            {
                "id": group.id,

                "event_type": (
                    group.event_type
                ),

                "primary_location": (
                    group.primary_location
                    or "-"
                ),

                "country": (
                    group.country
                    or "-"
                ),

                "region": (
                    group.primary_region
                    or "GLOBAL"
                ),

                "confidence": safe_float(
                    group.confidence
                ),

                "source_count": safe_int(
                    group.source_count
                ),

                "last_seen": format_datetime(
                    group.last_seen
                ),

                "representative_text": (
                    group.representative_text
                    or ""
                ),
            }
        )

    return results


# ==========================================================
# OPERATIONAL ASSESSMENT
# ==========================================================

def get_operational_assessment(
    session,
    kpis,
    region_activity,
    source_activity,
    correlation,
):
    """
    Builds deterministic rule-based analytical assessment.

    This is intentionally not AI-generated.

    It summarizes:
    - operational activity
    - active event groups
    - dominant region
    - dominant event type
    - primary source
    - average confidence
    - correlation performance
    - system assessment
    """

    dominant_region = (
        get_dominant_region(
            region_activity
        )
    )

    dominant_source = (
        get_dominant_source(
            source_activity
        )
    )

    dominant_event = (
        get_dominant_event_type(
            session
        )
    )

    average_confidence = (
        get_average_confidence(
            session
        )
    )

    active_groups = safe_int(
        kpis.get(
            "active_event_groups"
        )
    )

    recent_operational = safe_int(
        kpis.get(
            "operational_events"
        )
    )

    recent_correlated = safe_int(
        kpis.get(
            "correlated_events"
        )
    )

    correlation_rate = safe_float(
        correlation.get(
            "correlation_rate"
        )
    )

    system_health = (
        determine_system_health(
            operational_events=(
                recent_operational
            ),
            active_groups=(
                active_groups
            ),
            average_confidence=(
                average_confidence
            ),
        )
    )

    activity_level = (
        determine_activity_level(
            recent_operational
        )
    )

    confidence_level = (
        determine_confidence_level(
            average_confidence
        )
    )

    summary = (
        build_assessment_summary(
            operational_events=(
                recent_operational
            ),
            correlated_events=(
                recent_correlated
            ),
            active_groups=(
                active_groups
            ),
            dominant_region=(
                dominant_region
            ),
            dominant_event=(
                dominant_event
            ),
            dominant_source=(
                dominant_source
            ),
            average_confidence=(
                average_confidence
            ),
            activity_level=(
                activity_level
            ),
        )
    )

    return {
        "operational_events_24h": (
            recent_operational
        ),

        "correlated_events_24h": (
            recent_correlated
        ),

        "active_event_groups": (
            active_groups
        ),

        "dominant_region": (
            dominant_region
        ),

        "dominant_event_type": (
            dominant_event
        ),

        "dominant_source": (
            dominant_source
        ),

        "average_confidence": round(
            average_confidence,
            3,
        ),

        "confidence_level": (
            confidence_level
        ),

        "correlation_rate": round(
            correlation_rate,
            2,
        ),

        "activity_level": (
            activity_level
        ),

        "system_health": (
            system_health
        ),

        "summary": (
            summary
        ),
    }


# ==========================================================
# ASSESSMENT HELPERS
# ==========================================================

def get_dominant_region(
    region_activity,
):
    """
    Returns the most active meaningful region.

    GLOBAL is ignored when a real region exists.
    """

    if not region_activity:
        return "N/A"

    meaningful_regions = [
        item
        for item in region_activity
        if (
            item.get(
                "region"
            )
            not in {
                None,
                "",
                "GLOBAL",
            }
        )
    ]

    candidates = (
        meaningful_regions
        if meaningful_regions
        else region_activity
    )

    if not candidates:
        return "N/A"

    dominant = max(
        candidates,
        key=lambda item: safe_int(
            item.get(
                "count"
            )
        ),
    )

    return (
        dominant.get(
            "region"
        )
        or "N/A"
    )


def get_dominant_source(
    source_activity,
):
    """
    Returns the most active source type.
    """

    if not source_activity:
        return "N/A"

    dominant = max(
        source_activity,
        key=lambda item: safe_int(
            item.get(
                "count"
            )
        ),
    )

    return (
        dominant.get(
            "source"
        )
        or "N/A"
    )


def get_dominant_event_type(
    session,
):
    """
    Finds the dominant operational event type
    in the last 24 hours.
    """

    cutoff = recent_cutoff()

    event_types = (
        session.execute(
            select(
                Post.signal_type
            )
            .where(
                Post.signal_type
                .is_not(None)
            )
            .where(
                Post.collected_at
                >= cutoff
            )
        )
        .scalars()
        .all()
    )

    normalized = [
        event_type
        for event_type in event_types
        if event_type
    ]

    if not normalized:
        return "N/A"

    counts = Counter(
        normalized
    )

    return (
        counts
        .most_common(1)[0][0]
    )


def get_average_confidence(
    session,
):
    """
    Calculates average EventGroup confidence.
    """

    result = (
        session.execute(
            select(
                func.avg(
                    EventGroup.confidence
                )
            )
            .where(
                EventGroup.confidence
                .is_not(None)
            )
            .where(
                EventGroup.status
                == "ACTIVE"
            )
        )
        .scalar_one_or_none()
    )

    return safe_float(
        result
    )


def determine_activity_level(
    operational_events,
):
    """
    Simple rule-based 24h activity classification.

    Thresholds are intentionally conservative
    and can later be calibrated from historical data.
    """

    value = safe_int(
        operational_events
    )

    if value >= 30:
        return "HIGH"

    if value >= 10:
        return "ELEVATED"

    if value >= 3:
        return "MODERATE"

    return "LOW"


def determine_confidence_level(
    confidence,
):
    """
    Human-readable confidence level.
    """

    value = safe_float(
        confidence
    )

    if value >= 0.75:
        return "HIGH"

    if value >= 0.50:
        return "MEDIUM"

    return "LOW"


def determine_system_health(
    operational_events,
    active_groups,
    average_confidence,
):
    """
    Provides a dashboard analytical state.

    This is not infrastructure health.
    It represents the current analytical signal state.
    """

    operational_events = safe_int(
        operational_events
    )

    active_groups = safe_int(
        active_groups
    )

    average_confidence = safe_float(
        average_confidence
    )

    if (
        operational_events >= 30
        and active_groups >= 10
    ):
        return "HIGH ACTIVITY"

    if (
        operational_events >= 10
        or active_groups >= 5
    ):
        return "ELEVATED"

    if (
        operational_events == 0
        and active_groups == 0
    ):
        return "LOW ACTIVITY"

    if average_confidence < 0.40:
        return "LOW CONFIDENCE"

    return "NORMAL"


def humanize_token(
    value,
):
    """
    Converts internal constant names into readable text.

    Example:
    WESTERN_MEDITERRANEAN
        ->
    Western Mediterranean
    """

    if not value:
        return "N/A"

    return (
        str(value)
        .replace(
            "_",
            " "
        )
        .title()
    )


def build_assessment_summary(
    operational_events,
    correlated_events,
    active_groups,
    dominant_region,
    dominant_event,
    dominant_source,
    average_confidence,
    activity_level,
):
    """
    Creates a deterministic short dashboard assessment.

    This is deliberately factual and avoids
    interpretation beyond available system data.
    """

    region_text = (
        humanize_token(
            dominant_region
        )
    )

    event_text = (
        humanize_token(
            dominant_event
        )
    )

    source_text = (
        humanize_token(
            dominant_source
        )
    )

    return (
        f"Az elmúlt 24 órában a rendszer "
        f"{operational_events} operatív migrációs eseményt "
        f"azonosított, amelyek közül "
        f"{correlated_events} esemény korábbi vagy párhuzamos "
        f"forrással korrelált. "
        f"Jelenleg {active_groups} aktív eseménycsoport szerepel "
        f"az adatbázisban. "
        f"A legerősebb regionális aktivitás: {region_text}. "
        f"A domináns eseménytípus: {event_text}. "
        f"A legaktívabb adatforrás: {source_text}. "
        f"Az aktív eseménycsoportok átlagos konfidenciája "
        f"{average_confidence:.2f}. "
        f"A jelenlegi aktivitási szint: {activity_level}."
    )


# ==========================================================
# COMPLETE DASHBOARD DATA
# ==========================================================

def build_dashboard_data(
    session,
):
    """
    Builds the complete dashboard JSON structure.
    """

    kpis = get_kpis(
        session
    )

    live_events = get_live_events(
        session
    )

    event_groups = get_event_groups(
        session
    )

    region_activity = (
        get_region_activity(
            session
        )
    )

    source_activity = (
        get_source_activity(
            session
        )
    )

    correlation = (
        get_correlation_performance(
            session
        )
    )

    operational_assessment = (
        get_operational_assessment(
            session=session,
            kpis=kpis,
            region_activity=region_activity,
            source_activity=source_activity,
            correlation=correlation,
        )
    )

    high_confidence_events = (
        get_high_confidence_events(
            session
        )
    )

    return {
        "updated_at": format_datetime(
            utc_now()
        ),

        "kpis": (
            kpis
        ),

        "live_events": (
            live_events
        ),

        "event_groups": (
            event_groups
        ),

        "region_activity": (
            region_activity
        ),

        "source_activity": (
            source_activity
        ),

        "correlation": (
            correlation
        ),

        "operational_assessment": (
            operational_assessment
        ),

        "high_confidence_events": (
            high_confidence_events
        ),
    }


# ==========================================================
# EXPORT
# ==========================================================

def export_dashboard_data():
    """
    Exports dashboard data to dashboard-data.json
    in the repository root.
    """

    session = get_session()

    try:

        data = (
            build_dashboard_data(
                session
            )
        )

        with OUTPUT_FILE.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(
            "==================================="
        )

        print(
            "DASHBOARD DATA EXPORT"
        )

        print(
            "==================================="
        )

        print(
            f"Output: "
            f"{OUTPUT_FILE}"
        )

        print(
            "Operational events (24h): "
            f"{data['kpis']['operational_events']}"
        )

        print(
            "Active event groups: "
            f"{data['kpis']['active_event_groups']}"
        )

        print(
            "Live events exported: "
            f"{len(data['live_events'])}"
        )

        print(
            "Event groups exported: "
            f"{len(data['event_groups'])}"
        )

        print(
            "Dominant region: "
            f"{data['operational_assessment']['dominant_region']}"
        )

        print(
            "Dominant event type: "
            f"{data['operational_assessment']['dominant_event_type']}"
        )

        print(
            "Dominant source: "
            f"{data['operational_assessment']['dominant_source']}"
        )

        print(
            "Average confidence: "
            f"{data['operational_assessment']['average_confidence']}"
        )

        print(
            "Activity level: "
            f"{data['operational_assessment']['activity_level']}"
        )

        print(
            "System health: "
            f"{data['operational_assessment']['system_health']}"
        )

        print(
            "Dashboard data exported successfully."
        )

    finally:

        session.close()


if __name__ == "__main__":
    export_dashboard_data()
