"""
Migration OSINT Monitor

File:
export_dashboard_data.py

Description:
Exports dashboard-ready JSON data from the existing SQLite database.

The generated file is used by the static GitHub Pages dashboard.

Output:
dashboard-data.json
"""

import json

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from database.database import get_session
from database.models import (
    Post,
    EventGroup,
    EventGroupSource,
)


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------

RECENT_HOURS = 24

LIVE_EVENT_LIMIT = 20

EVENT_GROUP_LIMIT = 10

HIGH_CONFIDENCE_LIMIT = 10

HIGH_CONFIDENCE_THRESHOLD = 0.75


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def utc_now():
    """
    Returns current UTC time.
    """

    return datetime.utcnow()


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


def format_datetime(
    value,
):
    """
    Converts datetime values to ISO-like dashboard strings.
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


# ---------------------------------------------------------
# KPI
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# LIVE EVENTS
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# EVENT GROUPS
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# REGION ACTIVITY
# ---------------------------------------------------------

def get_region_activity(
    session,
):
    """
    Groups event groups by primary region.
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


# ---------------------------------------------------------
# SOURCE ACTIVITY
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# CORRELATION
# ---------------------------------------------------------

def get_correlation_performance(
    session,
):
    """
    Returns high-level event processing statistics.
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

    event_groups = safe_int(
        event_groups
    )

    conversion_rate = 0.0

    if operational_events > 0:
        conversion_rate = (
            event_groups
            / operational_events
            * 100
        )

    return {
        "total_posts": total_posts,
        "operational_events": operational_events,
        "correlated_sources": correlated_sources,
        "event_groups": event_groups,
        "conversion_rate": round(
            conversion_rate,
            2,
        ),
    }


# ---------------------------------------------------------
# HIGH CONFIDENCE
# ---------------------------------------------------------

def get_high_confidence_events(
    session,
):
    """
    Returns high-confidence event groups.
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


# ---------------------------------------------------------
# EXPORT
# ---------------------------------------------------------

def build_dashboard_data(
    session,
):
    """
    Builds the complete JSON structure.
    """

    return {
        "updated_at": format_datetime(
            utc_now()
        ),
        "kpis": get_kpis(
            session
        ),
        "live_events": get_live_events(
            session
        ),
        "event_groups": get_event_groups(
            session
        ),
        "region_activity": get_region_activity(
            session
        ),
        "source_activity": get_source_activity(
            session
        ),
        "correlation": (
            get_correlation_performance(
                session
            )
        ),
        "high_confidence_events": (
            get_high_confidence_events(
                session
            )
        ),
    }


def export_dashboard_data():
    """
    Exports dashboard data to the repository root.
    """

    session = get_session()

    try:

        data = build_dashboard_data(
            session
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
            f"Output: {OUTPUT_FILE}"
        )

        print(
            "Operational events: "
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
            "Dashboard data exported successfully."
        )

    finally:
        session.close()


if __name__ == "__main__":
    export_dashboard_data()
