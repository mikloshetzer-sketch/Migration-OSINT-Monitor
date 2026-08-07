"""
Migration OSINT Monitor

File:
dashboard/app.py

Description:
Flask backend for the Migration OSINT analytical dashboard.

The dashboard reads directly from the existing SQLite database and
provides aggregated data from:

- posts
- event_groups
- event_group_sources

This module does not modify the monitoring pipeline or database schema.
It only reads and summarizes existing data.
"""

import json

from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template
from sqlalchemy import (
    func,
    select,
)

from database.database import get_session
from database.models import (
    Post,
    EventGroup,
    EventGroupSource,
)


# ---------------------------------------------------------
# FLASK APPLICATION
# ---------------------------------------------------------

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)


# ---------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------

HIGH_CONFIDENCE_THRESHOLD = 0.75
RECENT_HOURS = 24
LIVE_EVENT_LIMIT = 20
EVENT_GROUP_LIMIT = 10
HIGH_CONFIDENCE_LIMIT = 10


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def utc_now():
    """
    Returns current UTC datetime without timezone information.

    The current SQLite schema stores naive DateTime values.
    """

    return datetime.utcnow()


def recent_cutoff(
    hours=RECENT_HOURS,
):
    """
    Returns datetime cutoff for recent dashboard statistics.
    """

    return (
        utc_now()
        - timedelta(
            hours=hours
        )
    )


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


def deserialize_source_types(
    value,
):
    """
    Reads EventGroup.source_types JSON text.
    """

    if not value:
        return []

    try:
        data = json.loads(
            value
        )

        if isinstance(
            data,
            list,
        ):
            return data

    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        pass

    return []


def format_datetime(
    value,
):
    """
    Converts datetime to dashboard-friendly string.
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


def confidence_level(
    value,
):
    """
    Returns simplified dashboard confidence classification.
    """

    confidence = safe_float(
        value
    )

    if confidence >= 0.85:
        return "HIGH"

    if confidence >= 0.60:
        return "MEDIUM"

    return "LOW"


# ---------------------------------------------------------
# KPI DATA
# ---------------------------------------------------------

def get_dashboard_kpis(
    session,
):
    """
    Calculates the main dashboard KPI cards.
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
                Post.signal_type.is_not(
                    None
                )
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
                Post.signal_type.is_not(
                    None
                )
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
                .is_not(
                    None
                )
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
                .is_not(
                    None
                )
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
# LIVE EVENT FEED
# ---------------------------------------------------------

def get_live_events(
    session,
    limit=LIVE_EVENT_LIMIT,
):
    """
    Returns the most recent operational source events.
    """

    statement = (
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
            Post.signal_type.is_not(
                None
            )
        )
        .order_by(
            Post.published_at.desc()
        )
        .limit(
            limit
        )
    )

    rows = (
        session.execute(
            statement
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
                "event_group_id": event_group_id,
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
                "region": None,
                "country": None,
                "confidence": safe_float(
                    post.extraction_confidence
                ),
                "confidence_level": confidence_level(
                    post.extraction_confidence
                ),
                "source": post.source,
                "author": post.author,
                "text": post.text,
                "url": post.url,
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
# EVENT GROUP DATA
# ---------------------------------------------------------

def get_top_event_groups(
    session,
    limit=EVENT_GROUP_LIMIT,
):
    """
    Returns the most relevant / active event groups.
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
                limit
            )
        )
        .scalars()
        .all()
    )

    results = []

    for group in groups:

        source_types = (
            deserialize_source_types(
                group.source_types
            )
        )

        results.append(
            {
                "id": group.id,
                "event_type": group.event_type,
                "title": group.title,
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
                "source_types": source_types,
                "status": group.status,
                "confidence": safe_float(
                    group.confidence
                ),
                "confidence_level": confidence_level(
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
    Aggregates event groups by primary region.
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

    results = []

    for region, count in rows:

        region_name = (
            region
            or "GLOBAL"
        )

        results.append(
            {
                "region": region_name,
                "count": safe_int(
                    count
                ),
            }
        )

    return results


# ---------------------------------------------------------
# SOURCE ACTIVITY
# ---------------------------------------------------------

def get_source_activity(
    session,
):
    """
    Aggregates operational posts by source.
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
                Post.signal_type.is_not(
                    None
                )
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

    results = []

    for source, count in rows:

        results.append(
            {
                "source": (
                    source
                    or "UNKNOWN"
                ),
                "count": safe_int(
                    count
                ),
            }
        )

    return results


# ---------------------------------------------------------
# CORRELATION PERFORMANCE
# ---------------------------------------------------------

def get_correlation_performance(
    session,
):
    """
    Returns funnel-style correlation statistics.
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
                Post.signal_type.is_not(
                    None
                )
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
                .is_not(
                    None
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

    event_groups = safe_int(
        event_groups
    )

    conversion_rate = 0.0

    if operational_events > 0:
        conversion_rate = (
            event_groups
            / operational_events
        ) * 100

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
# HIGH CONFIDENCE EVENTS
# ---------------------------------------------------------

def get_high_confidence_events(
    session,
    limit=HIGH_CONFIDENCE_LIMIT,
):
    """
    Returns highest-confidence active event groups.
    """

    groups = (
        session.execute(
            select(
                EventGroup
            )
            .where(
                EventGroup.confidence
                .is_not(
                    None
                )
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
                limit
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
                "event_type": group.event_type,
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
# DASHBOARD DATA PACKAGE
# ---------------------------------------------------------

def build_dashboard_data(
    session,
):
    """
    Builds the complete dashboard context.
    """

    return {
        "updated_at": format_datetime(
            utc_now()
        ),
        "kpis": get_dashboard_kpis(
            session
        ),
        "live_events": get_live_events(
            session
        ),
        "event_groups": get_top_event_groups(
            session
        ),
        "region_activity": get_region_activity(
            session
        ),
        "source_activity": get_source_activity(
            session
        ),
        "correlation": get_correlation_performance(
            session
        ),
        "high_confidence_events": (
            get_high_confidence_events(
                session
            )
        ),
    }


# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------

@app.route("/")
def dashboard():
    """
    Main dashboard page.
    """

    session = get_session()

    try:
        dashboard_data = (
            build_dashboard_data(
                session
            )
        )

    finally:
        session.close()

    return render_template(
        "index.html",
        data=dashboard_data,
    )


@app.route("/health")
def health():
    """
    Simple service health endpoint.
    """

    return {
        "status": "ok",
        "service": (
            "Migration OSINT Dashboard"
        ),
        "updated_at": format_datetime(
            utc_now()
        ),
    }


# ---------------------------------------------------------
# LOCAL DEVELOPMENT
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
    )
