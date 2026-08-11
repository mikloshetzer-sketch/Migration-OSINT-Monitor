"""
Migration OSINT Monitor

File:
dashboard/export_dashboard_data.py

Description:
Exports dashboard-ready JSON data from the persistent SQLite database.

V3 dashboard sections:
- updated_at
- current_run
- kpis
- live_events
- event_groups
- regions / region_activity
- sources / source_activity
- correlation
- operational_assessment
- technical_health
- high_confidence_events
- influence_signals
- crossing_access_signals
- top_crossing_access_posts
- information_activity_weekly
- information_activity_summary
- signal_timeline

The exporter preserves the existing operational dashboard data while adding
the persistent history / influence layer introduced by:
- MonitorRun
- CollectedPost
- InfluenceSignal
"""

import json
import re

from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from database.database import get_session
from database.models import (
    Post,
    EventGroup,
    EventGroupSource,
    MonitorRun,
    CollectedPost,
    InfluenceSignal,
)


# ==========================================================
# PATHS / CONSTANTS
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

RECENT_HOURS = 24
LIVE_EVENT_LIMIT = 20
EVENT_GROUP_LIMIT = 10
HIGH_CONFIDENCE_LIMIT = 10
INFLUENCE_LIMIT = 20
TOP_ACCESS_POST_LIMIT = 3
WEEK_HISTORY_COUNT = 8

# Signal Timeline V1
TIMELINE_WINDOW_HOURS = 24 * 7
TIMELINE_ITEM_LIMIT = 150

# INFORMATION layer:
# Do not use operational_confidence as the primary gate. In the current
# pipeline most rejected posts receive 0.1, so a 0.20-0.49 window produces
# an empty INFORMATION layer. Instead, select a small number of filtered
# posts using migration-operational context cues.
TIMELINE_INFORMATION_CANDIDATE_LIMIT = 300
TIMELINE_INFORMATION_LIMIT = 30
TIMELINE_INFORMATION_MIN_SCORE = 2

HIGH_CONFIDENCE_THRESHOLD = 0.75

ACCESS_SIGNAL_TYPES = {
    "CROSSING_FACILITATION",
    "DECISION_INFLUENCE",
    "MOBILIZATION_COORDINATION",
    "MOBILIZATION_REPORT",
    "LEGAL_MIGRATION_SIGNAL",
    "ONLINE_INFLUENCE_REPORT",
}


PRIORITY_SIGNAL_WEIGHTS = {
    "MOBILIZATION_COORDINATION": 30,
    "MOBILIZATION_REPORT": 28,
    "CROSSING_FACILITATION": 26,
    "RECRUITMENT_COORDINATION": 24,
    "DECISION_INFLUENCE": 20,
    "ONLINE_INFLUENCE_REPORT": 18,
    "LEGAL_MIGRATION_SIGNAL": 16,
    "POLICY_SIGNAL": 8,
}

TOP_POST_SIMILARITY_THRESHOLD = 0.72
TOP_POST_TOKEN_OVERLAP_THRESHOLD = 0.68


# ==========================================================
# TIME HELPERS
# ==========================================================

def utc_now():
    """
    Returns current UTC time as a naive datetime.

    Existing SQLite DateTime columns are stored as naive UTC.
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
    Returns the UTC cutoff for recent dashboard statistics.
    """
    return (
        utc_now()
        - timedelta(
            hours=hours
        )
    )


def format_datetime(
    value,
):
    """
    Converts datetime values to dashboard-friendly ISO UTC strings.
    """
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return (
            value.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )

    return str(
        value
    )


def start_of_iso_week(
    value,
):
    """
    Returns Monday 00:00:00 for the ISO week containing value.
    """
    return (
        value
        - timedelta(
            days=value.weekday()
        )
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


# ==========================================================
# SAFE CONVERSION / JSON
# ==========================================================

def safe_int(
    value,
    default=0,
):
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


def deserialize_json_text(
    value,
    default=None,
):
    """
    Reads JSON serialized into Text columns.
    """
    if default is None:
        default = []

    if value is None:
        return default

    if isinstance(
        value,
        (
            list,
            dict,
        ),
    ):
        return value

    try:
        return json.loads(
            value
        )
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return default


def humanize_token(
    value,
):
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


# ==========================================================
# PRIORITY / DEDUPLICATION HELPERS
# ==========================================================

def normalize_post_text_for_similarity(
    value,
):
    """
    Normalizes social-media text for near-duplicate detection.

    Removes:
    - URLs
    - leading @mentions
    - repeated whitespace
    - punctuation noise

    The purpose is dashboard presentation only. It does not alter
    stored source text or detector decisions.
    """
    if not value:
        return ""

    text = str(
        value
    ).lower()

    text = re.sub(
        r"https?://\S+",
        " ",
        text,
    )

    text = re.sub(
        r"(?:^|\s)@\w+",
        " ",
        text,
    )

    text = re.sub(
        r"[^a-z0-9áéíóöőúüűà-ÿ\s]",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text


def similarity_ratio(
    left,
    right,
):
    """
    Returns a 0..1 similarity ratio for normalized post text.
    """
    if not left or not right:
        return 0.0

    return SequenceMatcher(
        None,
        left,
        right,
    ).ratio()


def token_overlap_ratio(
    left,
    right,
):
    """
    Jaccard-style token overlap for repost / quote-post detection.
    """
    if not left or not right:
        return 0.0

    left_tokens = {
        token
        for token in left.split()
        if len(token) >= 3
    }

    right_tokens = {
        token
        for token in right.split()
        if len(token) >= 3
    }

    if not left_tokens or not right_tokens:
        return 0.0

    union = len(
        left_tokens
        | right_tokens
    )

    if union <= 0:
        return 0.0

    return (
        len(
            left_tokens
            & right_tokens
        )
        / union
    )


def independent_confirmation_count(
    item,
):
    authors = item.get(
        "related_authors"
    ) or []

    if isinstance(
        authors,
        list,
    ):
        return len(
            {
                str(author).strip().lower()
                for author in authors
                if author
            }
        )

    return 0


def platform_diversity_count(
    item,
):
    platforms = item.get(
        "related_sources"
    ) or []

    if isinstance(
        platforms,
        list,
    ):
        return len(
            {
                str(source).strip().upper()
                for source in platforms
                if source
            }
        )

    return 1 if item.get("source") else 0


def calculate_priority_score(
    item,
):
    """
    Analyst-review score.

    Classification confidence is not truth confidence.
    Repetition increases information significance, while cross-platform
    and distinct-author reinforcement increase verification value.
    """
    signal_type = str(
        item.get("primary_signal")
        or item.get("signal_type")
        or item.get("event_type")
        or ""
    ).upper()

    confidence = safe_float(
        item.get("confidence")
        or item.get("event_confidence")
        or item.get("average_confidence")
    )

    score = confidence * 35.0
    score += PRIORITY_SIGNAL_WEIGHTS.get(signal_type, 0)

    location = (
        item.get("primary_location")
        or item.get("location")
    )

    if location and str(location).strip().upper() not in {"", "-", "GLOBAL", "UNKNOWN"}:
        score += 7.0

    region = (
        item.get("primary_region")
        or item.get("region")
    )

    if region and str(region).strip().upper() not in {"", "GLOBAL", "UNKNOWN"}:
        score += 4.0

    related_posts_count = safe_int(
        item.get("related_posts_count"),
        1,
    )

    author_count = independent_confirmation_count(item)
    platform_count = platform_diversity_count(item)

    if related_posts_count >= 8:
        score += 8.0
    elif related_posts_count >= 4:
        score += 6.0
    elif related_posts_count >= 2:
        score += 3.0

    if author_count >= 5:
        score += 7.0
    elif author_count >= 2:
        score += 4.0

    if platform_count >= 3:
        score += 12.0
    elif platform_count >= 2:
        score += 9.0

    return round(
        min(score, 100.0),
        2,
    )


def priority_level_from_score(
    score,
    *,
    related_posts_count=1,
    independent_authors=0,
    platform_count=1,
):
    value = safe_float(score)

    # CRITICAL requires reinforcement beyond one single-platform post.
    if (
        value >= 82
        and (
            platform_count >= 2
            or independent_authors >= 3
        )
    ):
        return "CRITICAL"

    if value >= 62:
        return "HIGH"

    if value >= 42:
        return "MEDIUM"

    return "LOW"


# ==========================================================
# TECHNICAL HEALTH
# ==========================================================

def get_latest_monitor_run(
    session,
):
    """
    Returns the latest MonitorRun regardless of status.
    """
    return (
        session.execute(
            select(
                MonitorRun
            )
            .order_by(
                MonitorRun.started_at.desc(),
                MonitorRun.id.desc(),
            )
            .limit(1)
        )
        .scalars()
        .first()
    )


def get_current_run(
    session,
):
    """
    Dashboard representation of the latest monitor execution.
    """
    run = get_latest_monitor_run(
        session
    )

    if run is None:
        return {
            "available": False,
            "status": "UNKNOWN",
        }

    return {
        "available": True,
        "id": run.id,
        "run_uuid": run.run_uuid,
        "started_at": format_datetime(
            run.started_at
        ),
        "completed_at": format_datetime(
            run.completed_at
        ),
        "status": run.status,

        "posts_returned": safe_int(
            run.posts_returned
        ),
        "unique_posts_collected": safe_int(
            run.unique_posts_collected
        ),

        "x_posts_returned": safe_int(
            run.x_posts_returned
        ),
        "reddit_posts_returned": safe_int(
            run.reddit_posts_returned
        ),
        "mastodon_posts_returned": safe_int(
            run.mastodon_posts_returned
        ),

        "unique_x_posts": safe_int(
            run.unique_x_posts
        ),
        "unique_reddit_posts": safe_int(
            run.unique_reddit_posts
        ),
        "unique_mastodon_posts": safe_int(
            run.unique_mastodon_posts
        ),

        "noise_filtered": safe_int(
            run.noise_filtered
        ),
        "non_operational_filtered": safe_int(
            run.non_operational_filtered
        ),
        "historical_references_filtered": safe_int(
            run.historical_references_filtered
        ),

        "influence_signals": safe_int(
            run.influence_signals_detected
        ),
        "influence_signals_detected": safe_int(
            run.influence_signals_detected
        ),

        "crossing_facilitation_signals": safe_int(
            run.crossing_facilitation_signals
        ),
        "legal_migration_signals": safe_int(
            run.legal_migration_signals
        ),
        "policy_signals": safe_int(
            run.policy_signals
        ),
        "recruitment_coordination_signals": safe_int(
            run.recruitment_coordination_signals
        ),
        "mobilization_coordination_signals": safe_int(
            run.mobilization_coordination_signals
        ),
        "mobilization_report_signals": safe_int(
            run.mobilization_report_signals
        ),
        "decision_influence_signals": safe_int(
            run.decision_influence_signals
        ),
        "online_influence_report_signals": safe_int(
            run.online_influence_report_signals
        ),

        "operational_events": safe_int(
            run.operational_events_analyzed
        ),
        "operational_events_analyzed": safe_int(
            run.operational_events_analyzed
        ),

        "historical_events_available": safe_int(
            run.historical_events_available
        ),

        "new_correlations": (
            safe_int(
                run.events_correlated_existing
            )
        ),
        "correlated_events": (
            safe_int(
                run.events_correlated_existing
            )
        ),

        "new_correlation_groups": safe_int(
            run.new_correlation_groups
        ),
        "database_correlations": safe_int(
            run.database_correlations
        ),
        "current_run_correlations": safe_int(
            run.current_run_correlations
        ),

        "new_events": safe_int(
            run.new_events_saved
        ),
        "new_events_saved": safe_int(
            run.new_events_saved
        ),
        "events_already_existing": safe_int(
            run.events_already_existing
        ),

        "new_event_groups": safe_int(
            run.new_event_groups
        ),
        "updated_event_groups": safe_int(
            run.updated_event_groups
        ),
        "bootstrapped_event_groups": safe_int(
            run.bootstrapped_event_groups
        ),
        "existing_event_groups_reused": safe_int(
            run.existing_event_groups_reused
        ),
        "event_group_sources_linked": safe_int(
            run.event_group_sources_linked
        ),

        "x_collector_errors": safe_int(
            run.x_collector_errors
        ),
        "reddit_collector_errors": safe_int(
            run.reddit_collector_errors
        ),
        "mastodon_collector_errors": safe_int(
            run.mastodon_collector_errors
        ),

        "error_message": run.error_message,
    }


def get_technical_health(
    session,
):
    """
    Technical system health, intentionally separate from activity level.
    """
    run = get_latest_monitor_run(
        session
    )

    if run is None:
        return {
            "status": "UNKNOWN",
            "healthy": False,
            "collector_errors": None,
            "database": "AVAILABLE",
        }

    collector_errors = (
        safe_int(
            run.x_collector_errors
        )
        + safe_int(
            run.reddit_collector_errors
        )
        + safe_int(
            run.mastodon_collector_errors
        )
    )

    status = str(
        run.status
        or "UNKNOWN"
    ).upper()

    healthy = (
        status == "SUCCESS"
        and collector_errors == 0
    )

    if healthy:
        health_status = "HEALTHY"
    elif status == "SUCCESS":
        health_status = "DEGRADED"
    elif status == "RUNNING":
        health_status = "RUNNING"
    else:
        health_status = "ERROR"

    return {
        "status": health_status,
        "healthy": healthy,
        "run_status": status,
        "collector_errors": collector_errors,
        "x_collector_errors": safe_int(
            run.x_collector_errors
        ),
        "reddit_collector_errors": safe_int(
            run.reddit_collector_errors
        ),
        "mastodon_collector_errors": safe_int(
            run.mastodon_collector_errors
        ),
        "database": "AVAILABLE",
        "last_run_id": run.id,
        "last_completed_at": format_datetime(
            run.completed_at
        ),
    }


# ==========================================================
# KPI
# ==========================================================

def get_kpis(
    session,
):
    """
    Existing 24h operational KPI block, plus V3 history/influence KPIs.
    """
    cutoff = recent_cutoff()

    operational_events = safe_int(
        session.execute(
            select(
                func.count(
                    Post.id
                )
            )
            .where(
                Post.published_at
                .is_not(None)
            )
            .where(
                Post.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    active_event_groups = safe_int(
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

    correlated_events = safe_int(
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
                .is_not(None)
            )
            .where(
                EventGroupSource.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    influence_signals = safe_int(
        session.execute(
            select(
                func.count(
                    InfluenceSignal.id
                )
            )
            .where(
                InfluenceSignal.published_at
                .is_not(None)
            )
            .where(
                InfluenceSignal.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    access_signals = safe_int(
        session.execute(
            select(
                func.count(
                    InfluenceSignal.id
                )
            )
            .where(
                InfluenceSignal.primary_signal
                .in_(
                    ACCESS_SIGNAL_TYPES
                )
            )
            .where(
                InfluenceSignal.published_at
                .is_not(None)
            )
            .where(
                InfluenceSignal.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    collected_posts_24h = safe_int(
        session.execute(
            select(
                func.count(
                    CollectedPost.id
                )
            )
            .where(
                CollectedPost.published_at
                .is_not(None)
            )
            .where(
                CollectedPost.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    source_count = safe_int(
        session.execute(
            select(
                func.count(
                    func.distinct(
                        CollectedPost.source
                    )
                )
            )
            .where(
                CollectedPost.published_at
                .is_not(None)
            )
            .where(
                CollectedPost.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    region_count = safe_int(
        session.execute(
            select(
                func.count(
                    func.distinct(
                        EventGroup.primary_region
                    )
                )
            )
            .where(
                EventGroup.primary_region
                .is_not(None)
            )
            .where(
                EventGroup.last_seen
                .is_not(None)
            )
            .where(
                EventGroup.last_seen
                >= cutoff
            )
        )
        .scalar_one()
    )

    current_run = get_current_run(
        session
    )

    return {
        # Legacy names
        "operational_events": operational_events,
        "new_events": safe_int(
            current_run.get(
                "new_events_saved"
            )
        ),
        "correlated_events": correlated_events,
        "active_event_groups": active_event_groups,
        "sources": source_count,
        "regions": region_count,

        # V3 additions
        "collected_posts_24h": collected_posts_24h,
        "influence_signals": influence_signals,
        "access_signals": access_signals,
        "high_priority": safe_int(
            session.execute(
                select(
                    func.count(
                        InfluenceSignal.id
                    )
                )
                .where(
                    InfluenceSignal.published_at
                    .is_not(None)
                )
                .where(
                    InfluenceSignal.published_at
                    >= cutoff
                )
                .where(
                    InfluenceSignal.priority
                    .in_(
                        [
                            "HIGH",
                            "CRITICAL",
                        ]
                    )
                )
            )
            .scalar_one()
        ),
        "current_run_operational_events": safe_int(
            current_run.get(
                "operational_events_analyzed"
            )
        ),
        "current_run_unique_posts": safe_int(
            current_run.get(
                "unique_posts_collected"
            )
        ),
    }


# ==========================================================
# LIVE EVENTS
# ==========================================================

def get_live_events(
    session,
):
    """
    Returns latest operational Post records.
    """
    rows = (
        session.execute(
            select(
                Post
            )
            .order_by(
                Post.published_at.desc(),
                Post.id.desc(),
            )
            .limit(
                LIVE_EVENT_LIMIT
            )
        )
        .scalars()
        .all()
    )

    results = []

    for post in rows:
        locations = (
            deserialize_json_text(
                post.locations,
                default=[],
            )
        )

        primary_location = None

        if (
            isinstance(
                locations,
                list,
            )
            and locations
            and isinstance(
                locations[0],
                dict,
            )
        ):
            primary_location = (
                locations[0]
            )

        location_name = (
            primary_location.get(
                "name"
            )
            if primary_location
            else None
        )

        country = (
            primary_location.get(
                "country"
            )
            if primary_location
            else None
        )

        results.append(
            {
                "id": post.id,
                "event_id": post.id,
                "source": post.source,
                "source_post_id": post.post_id,
                "author": post.author,
                "published_at": format_datetime(
                    post.published_at
                ),
                "collected_at": format_datetime(
                    post.collected_at
                ),
                "event_type": (
                    post.signal_type
                    or "GENERAL_DISCUSSION"
                ),
                "signal_type": (
                    post.signal_type
                    or "GENERAL_DISCUSSION"
                ),
                "primary_location": (
                    location_name
                    or "-"
                ),
                "location": (
                    location_name
                    or "-"
                ),
                "country": (
                    country
                    or "-"
                ),
                "latitude": post.latitude,
                "longitude": post.longitude,
                "confidence": safe_float(
                    post.extraction_confidence
                ),
                "event_confidence": safe_float(
                    post.extraction_confidence
                ),
                "relevance_score": safe_float(
                    post.relevance_score
                ),
                "text": post.text or "",
                "url": post.url,
                "source_url": post.url,
            }
        )

    return results


# ==========================================================
# EVENT GROUPS
# ==========================================================

def deserialize_source_types(
    value,
):
    result = deserialize_json_text(
        value,
        default=[],
    )

    if isinstance(
        result,
        list,
    ):
        return result

    return []


def get_event_groups(
    session,
):
    """
    Returns highest-priority active EventGroups.
    """
    groups = (
        session.execute(
            select(
                EventGroup
            )
            .where(
                EventGroup.status
                == "ACTIVE"
            )
            .order_by(
                EventGroup.last_seen.desc(),
                EventGroup.source_count.desc(),
                EventGroup.confidence.desc(),
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
        source_types = (
            deserialize_source_types(
                group.source_types
            )
        )

        results.append(
            {
                "id": group.id,
                "group_id": group.id,
                "event_type": group.event_type,
                "dominant_event_type": group.event_type,
                "title": group.title,
                "representative_text": (
                    group.representative_text
                    or ""
                ),
                "region": (
                    group.primary_region
                    or "GLOBAL"
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
                "latitude": group.latitude,
                "longitude": group.longitude,
                "first_seen": format_datetime(
                    group.first_seen
                ),
                "last_seen": format_datetime(
                    group.last_seen
                ),
                "source_count": safe_int(
                    group.source_count,
                    1,
                ),
                "sources_count": safe_int(
                    group.source_count,
                    1,
                ),
                "source_types": source_types,
                "sources": source_types,
                "status": (
                    group.status
                    or "ACTIVE"
                ),
                "confidence": safe_float(
                    group.confidence
                ),
                "average_confidence": safe_float(
                    group.confidence
                ),
                "created_at": format_datetime(
                    group.created_at
                ),
                "updated_at": format_datetime(
                    group.updated_at
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
    Returns recent EventGroup activity by region.
    """
    cutoff = recent_cutoff()

    rows = (
        session.execute(
            select(
                EventGroup.primary_region,
                func.count(
                    EventGroup.id
                ),
            )
            .where(
                EventGroup.last_seen
                .is_not(None)
            )
            .where(
                EventGroup.last_seen
                >= cutoff
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

    total = sum(
        safe_int(
            count
        )
        for _region, count
        in rows
    )

    results = []

    for region, count in rows:
        count = safe_int(
            count
        )

        results.append(
            {
                "name": (
                    region
                    or "GLOBAL"
                ),
                "region": (
                    region
                    or "GLOBAL"
                ),
                "count": count,
                "events": count,
                "percentage": safe_percent(
                    count,
                    total,
                ),
            }
        )

    return results


# ==========================================================
# SOURCE ACTIVITY
# ==========================================================

def get_source_activity(
    session,
):
    """
    Returns unique collected social posts by source in last 24h.

    This uses CollectedPost instead of operational Post, so it measures
    the information environment rather than only operational events.
    """
    cutoff = recent_cutoff()

    rows = (
        session.execute(
            select(
                CollectedPost.source,
                func.count(
                    CollectedPost.id
                ),
            )
            .where(
                CollectedPost.published_at
                .is_not(None)
            )
            .where(
                CollectedPost.published_at
                >= cutoff
            )
            .group_by(
                CollectedPost.source
            )
            .order_by(
                func.count(
                    CollectedPost.id
                ).desc()
            )
        )
        .all()
    )

    total = sum(
        safe_int(
            count
        )
        for _source, count
        in rows
    )

    results = []

    for source, count in rows:
        count = safe_int(
            count
        )

        results.append(
            {
                "source": (
                    source
                    or "UNKNOWN"
                ),
                "name": (
                    source
                    or "UNKNOWN"
                ),
                "count": count,
                "posts": count,
                "percentage": safe_percent(
                    count,
                    total,
                ),
            }
        )

    return results


# ==========================================================
# INFLUENCE SIGNALS
# ==========================================================

def serialize_influence_signal(
    signal,
):
    """
    Converts one persistent InfluenceSignal into dashboard JSON.
    """
    item = {
        "id": signal.id,
        "source": signal.source,
        "source_post_id": signal.source_post_id,
        "author": signal.author,
        "language": signal.language,
        "published_at": format_datetime(
            signal.published_at
        ),
        "first_detected_at": format_datetime(
            signal.first_detected_at
        ),
        "last_detected_at": format_datetime(
            signal.last_detected_at
        ),
        "detection_count": safe_int(
            signal.detection_count,
            1,
        ),

        "text": signal.text or "",
        "text_excerpt": (
            (signal.text or "")[:700]
        ),
        "url": signal.source_url,
        "source_url": signal.source_url,

        "primary_signal": signal.primary_signal,
        "signal_type": signal.primary_signal,
        "signal_mode": signal.signal_mode,
        "signal_intent": signal.signal_intent,
        "priority": (
            signal.priority
            or "LOW"
        ),
        "confidence": safe_float(
            signal.confidence
        ),
        "score": safe_float(
            signal.score
        ),

        "matched_signals": deserialize_json_text(
            signal.matched_signals,
            default=[],
        ),
        "matched_phrases": deserialize_json_text(
            signal.matched_phrases,
            default=[],
        ),
        "matched_groups": deserialize_json_text(
            signal.matched_groups,
            default=[],
        ),
        "context_matches": deserialize_json_text(
            signal.context_matches,
            default=[],
        ),
        "high_value_matches": deserialize_json_text(
            signal.high_value_matches,
            default=[],
        ),
        "signal_context_rejections": deserialize_json_text(
            signal.signal_context_rejections,
            default={},
        ),

        "migration_context": signal.migration_context,
        "human_migration_context": (
            signal.human_migration_context
        ),

        "historical_reference": bool(
            signal.historical_reference
        ),
        "historical_reason": signal.historical_reason,
        "historical_reference_text": (
            signal.historical_reference_text
        ),

        "location": (
            signal.primary_location
            or "-"
        ),
        "primary_location": (
            signal.primary_location
            or "-"
        ),
        "country": (
            signal.country
            or "-"
        ),
        "region": (
            signal.primary_region
            or "GLOBAL"
        ),
        "primary_region": (
            signal.primary_region
            or "GLOBAL"
        ),
        "latitude": signal.latitude,
        "longitude": signal.longitude,

        "rules_version": signal.rules_version,
    }

    item[
        "priority_score"
    ] = calculate_priority_score(
        item
    )

    # Keep the stored detector-derived priority available, but expose
    # a separate analyst-review level based on the composite score.
    item[
        "analyst_priority"
    ] = priority_level_from_score(
        item[
            "priority_score"
        ],
        related_posts_count=1,
        independent_authors=0,
        platform_count=1,
    )

    return item


def influence_priority_rank(
    value,
):
    ranking = {
        "CRITICAL": 4,
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
    }

    return ranking.get(
        str(
            value
            or ""
        ).upper(),
        0,
    )


def get_influence_signals(
    session,
):
    """
    Returns recent persistent influence / early-warning signals.
    """
    cutoff = recent_cutoff()

    signals = (
        session.execute(
            select(
                InfluenceSignal
            )
            .where(
                InfluenceSignal.published_at
                .is_not(None)
            )
            .where(
                InfluenceSignal.published_at
                >= cutoff
            )
            .order_by(
                InfluenceSignal.published_at.desc(),
                InfluenceSignal.confidence.desc(),
            )
            .limit(
                INFLUENCE_LIMIT
            )
        )
        .scalars()
        .all()
    )

    results = [
        serialize_influence_signal(
            signal
        )
        for signal in signals
    ]

    results.sort(
        key=lambda item: (
            influence_priority_rank(
                item.get(
                    "priority"
                )
            ),
            safe_float(
                item.get(
                    "confidence"
                )
            ),
            item.get(
                "published_at"
            )
            or "",
        ),
        reverse=True,
    )

    return results


def get_crossing_access_signals(
    session,
):
    """
    Returns recent signals relevant to crossing/access intelligence.
    """
    cutoff = recent_cutoff()

    signals = (
        session.execute(
            select(
                InfluenceSignal
            )
            .where(
                InfluenceSignal.primary_signal
                .in_(
                    ACCESS_SIGNAL_TYPES
                )
            )
            .where(
                InfluenceSignal.published_at
                .is_not(None)
            )
            .where(
                InfluenceSignal.published_at
                >= cutoff
            )
        )
        .scalars()
        .all()
    )

    results = [
        serialize_influence_signal(
            signal
        )
        for signal in signals
    ]

    results.sort(
        key=lambda item: (
            influence_priority_rank(
                item.get(
                    "priority"
                )
            ),
            safe_float(
                item.get(
                    "confidence"
                )
            ),
            item.get(
                "published_at"
            )
            or "",
        ),
        reverse=True,
    )

    return results


def get_top_crossing_access_posts(
    crossing_access_signals,
):
    """
    Returns TOP 3 DISTINCT crossing/access intelligence items.

    Near-identical reposts / quote-post variants are clustered so the
    dashboard does not waste all three cards on the same information.

    Each representative receives:
    - related_posts_count
    - related_post_ids
    - related_authors
    - related_urls
    - priority_score
    - analyst_priority
    """
    if not crossing_access_signals:
        return []

    clusters = []

    for item in crossing_access_signals:
        normalized_text = (
            normalize_post_text_for_similarity(
                item.get(
                    "text"
                )
                or item.get(
                    "text_excerpt"
                )
                or ""
            )
        )

        signal_type = str(
            item.get(
                "primary_signal"
            )
            or item.get(
                "signal_type"
            )
            or ""
        ).upper()

        location = str(
            item.get(
                "primary_location"
            )
            or item.get(
                "location"
            )
            or ""
        ).strip().lower()

        matched_cluster = None

        for cluster in clusters:
            same_signal = (
                cluster[
                    "signal_type"
                ]
                == signal_type
            )

            same_location = (
                not location
                or not cluster[
                    "location"
                ]
                or cluster[
                    "location"
                ]
                == location
            )

            similarity = (
                similarity_ratio(
                    normalized_text,
                    cluster[
                        "normalized_text"
                    ],
                )
            )

            token_overlap = (
                token_overlap_ratio(
                    normalized_text,
                    cluster[
                        "normalized_text"
                    ],
                )
            )

            if (
                same_signal
                and same_location
                and (
                    similarity
                    >= TOP_POST_SIMILARITY_THRESHOLD
                    or token_overlap
                    >= TOP_POST_TOKEN_OVERLAP_THRESHOLD
                )
            ):
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append(
                {
                    "signal_type": signal_type,
                    "location": location,
                    "normalized_text": normalized_text,
                    "items": [
                        item
                    ],
                }
            )

            continue

        matched_cluster[
            "items"
        ].append(
            item
        )

    representatives = []

    for cluster in clusters:
        cluster_items = cluster[
            "items"
        ]

        cluster_items.sort(
            key=lambda item: (
                influence_priority_rank(
                    item.get(
                        "analyst_priority"
                    )
                    or item.get(
                        "priority"
                    )
                ),
                safe_float(
                    item.get(
                        "priority_score"
                    )
                ),
                safe_float(
                    item.get(
                        "confidence"
                    )
                ),
                item.get(
                    "published_at"
                )
                or "",
            ),
            reverse=True,
        )

        representative = dict(
            cluster_items[
                0
            ]
        )

        representative[
            "related_posts_count"
        ] = len(
            cluster_items
        )

        representative[
            "related_post_ids"
        ] = [
            item.get(
                "source_post_id"
            )
            for item in cluster_items
            if item.get(
                "source_post_id"
            )
        ]

        representative[
            "related_authors"
        ] = sorted(
            {
                item.get(
                    "author"
                )
                for item in cluster_items
                if item.get(
                    "author"
                )
            }
        )

        representative[
            "related_urls"
        ] = [
            item.get(
                "source_url"
            )
            or item.get(
                "url"
            )
            for item in cluster_items
            if (
                item.get(
                    "source_url"
                )
                or item.get(
                    "url"
                )
            )
        ]

        representative[
            "related_sources"
        ] = sorted(
            {
                str(
                    item.get("source")
                    or ""
                ).upper()
                for item in cluster_items
                if item.get("source")
            }
        )

        representative[
            "independent_author_count"
        ] = len(
            representative[
                "related_authors"
            ]
        )

        representative[
            "platform_count"
        ] = len(
            representative[
                "related_sources"
            ]
        )

        representative[
            "priority_score"
        ] = calculate_priority_score(
            representative
        )

        representative[
            "analyst_priority"
        ] = priority_level_from_score(
            representative[
                "priority_score"
            ],
            related_posts_count=representative[
                "related_posts_count"
            ],
            independent_authors=representative[
                "independent_author_count"
            ],
            platform_count=representative[
                "platform_count"
            ],
        )

        representatives.append(
            representative
        )

    representatives.sort(
        key=lambda item: (
            safe_float(
                item.get(
                    "priority_score"
                )
            ),
            safe_float(
                item.get(
                    "confidence"
                )
            ),
            safe_int(
                item.get(
                    "related_posts_count"
                ),
                1,
            ),
            item.get(
                "published_at"
            )
            or "",
        ),
        reverse=True,
    )

    return representatives[
        :TOP_ACCESS_POST_LIMIT
    ]


# ==========================================================
# WEEKLY INFORMATION ACTIVITY
# ==========================================================

def get_information_activity_weekly(
    session,
    week_count=WEEK_HISTORY_COUNT,
):
    """
    Returns unique collected-post volume for the last N ISO weeks.

    Important:
    - counts unique CollectedPost records
    - uses published_at
    - repeated manual workflow runs do not inflate the trend
    """
    now = utc_now()

    current_week_start = (
        start_of_iso_week(
            now
        )
    )

    oldest_week_start = (
        current_week_start
        - timedelta(
            weeks=week_count - 1
        )
    )

    posts = (
        session.execute(
            select(
                CollectedPost.published_at,
                CollectedPost.source,
                CollectedPost.influence_detected,
                CollectedPost.is_operational,
            )
            .where(
                CollectedPost.published_at
                .is_not(None)
            )
            .where(
                CollectedPost.published_at
                >= oldest_week_start
            )
        )
        .all()
    )

    influence_rows = (
        session.execute(
            select(
                InfluenceSignal.published_at
            )
            .where(
                InfluenceSignal.published_at
                .is_not(None)
            )
            .where(
                InfluenceSignal.published_at
                >= oldest_week_start
            )
        )
        .scalars()
        .all()
    )

    buckets = {}

    for offset in range(
        week_count
    ):
        week_start = (
            oldest_week_start
            + timedelta(
                weeks=offset
            )
        )

        iso_year, iso_week, _ = (
            week_start.isocalendar()
        )

        key = (
            iso_year,
            iso_week,
        )

        buckets[
            key
        ] = {
            "week_start": week_start,
            "posts": 0,
            "operational_posts": 0,
            "influence_posts": 0,
            "sources": Counter(),
        }

    for (
        published_at,
        source,
        influence_detected,
        is_operational,
    ) in posts:

        iso_year, iso_week, _ = (
            published_at.isocalendar()
        )

        key = (
            iso_year,
            iso_week,
        )

        if key not in buckets:
            continue

        bucket = buckets[
            key
        ]

        bucket[
            "posts"
        ] += 1

        if is_operational:
            bucket[
                "operational_posts"
            ] += 1

        if influence_detected:
            bucket[
                "influence_posts"
            ] += 1

        bucket[
            "sources"
        ][
            source
            or "UNKNOWN"
        ] += 1

    # InfluenceSignal is the authoritative persistent signal history.
    # Replace the collected-post flag count with the exact stored count.
    authoritative_influence = Counter()

    for published_at in influence_rows:
        iso_year, iso_week, _ = (
            published_at.isocalendar()
        )

        authoritative_influence[
            (
                iso_year,
                iso_week,
            )
        ] += 1

    output = []

    for key in sorted(
        buckets.keys()
    ):
        bucket = buckets[
            key
        ]

        iso_year, iso_week = key

        source_counts = dict(
            bucket[
                "sources"
            ]
        )

        output.append(
            {
                "year": iso_year,
                "week": iso_week,
                "label": f"W{iso_week:02d}",
                "week_label": f"W{iso_week:02d}",
                "week_start": format_datetime(
                    bucket[
                        "week_start"
                    ]
                ),
                "posts": safe_int(
                    bucket[
                        "posts"
                    ]
                ),
                "post_count": safe_int(
                    bucket[
                        "posts"
                    ]
                ),
                "operational_posts": safe_int(
                    bucket[
                        "operational_posts"
                    ]
                ),
                "influence_signals": safe_int(
                    authoritative_influence.get(
                        key,
                        0,
                    )
                ),
                "source_counts": source_counts,
            }
        )

    return output


def get_information_activity_summary(
    session,
    weekly_activity,
):
    """
    Like-for-like WTD comparison.

    A partial current week is compared with the same elapsed period of the
    previous week, rather than with the previous complete week.
    """

    now = utc_now()
    current_week_start = (
        start_of_iso_week(
            now
        )
    )

    elapsed = (
        now
        - current_week_start
    )

    previous_week_start = (
        current_week_start
        - timedelta(
            weeks=1
        )
    )

    previous_same_period_end = (
        previous_week_start
        + elapsed
    )

    current = safe_int(
        session.execute(
            select(
                func.count(
                    CollectedPost.id
                )
            )
            .where(
                CollectedPost.published_at
                .is_not(None)
            )
            .where(
                CollectedPost.published_at
                >= current_week_start
            )
            .where(
                CollectedPost.published_at
                <= now
            )
        )
        .scalar_one()
    )

    previous_same_period = safe_int(
        session.execute(
            select(
                func.count(
                    CollectedPost.id
                )
            )
            .where(
                CollectedPost.published_at
                .is_not(None)
            )
            .where(
                CollectedPost.published_at
                >= previous_week_start
            )
            .where(
                CollectedPost.published_at
                <= previous_same_period_end
            )
        )
        .scalar_one()
    )

    previous_full = 0

    if len(weekly_activity) >= 2:
        previous_full = safe_int(
            weekly_activity[-2].get(
                "posts"
            )
        )

    if previous_same_period > 0:
        change = round(
            (
                (
                    current
                    - previous_same_period
                )
                / previous_same_period
            )
            * 100,
            2,
        )

        if change > 0:
            direction = "UP"
        elif change < 0:
            direction = "DOWN"
        else:
            direction = "FLAT"

        change_label = (
            f"{change:+.1f}%"
        )
        comparable = True

    elif current > 0:
        change = None
        direction = "BASELINE"
        change_label = "NEW BASELINE"
        comparable = False

    else:
        change = 0.0
        direction = "FLAT"
        change_label = "0.0%"
        comparable = False

    return {
        # Backward-compatible frontend fields:
        "current_week": current,
        "previous_week": previous_same_period,

        # Explicit methodology fields:
        "current_week_to_date": current,
        "previous_week_same_period": previous_same_period,
        "previous_week_full": previous_full,
        "comparison_basis": "WEEK_TO_DATE_SAME_PERIOD",

        "change_percent": change,
        "change_label": change_label,
        "direction": direction,
        "comparable": comparable,

        "elapsed_hours": round(
            elapsed.total_seconds()
            / 3600,
            1,
        ),
        "current_period_start": format_datetime(
            current_week_start
        ),
        "previous_period_start": format_datetime(
            previous_week_start
        ),
        "previous_period_end": format_datetime(
            previous_same_period_end
        ),
    }


# ==========================================================
# CORRELATION PERFORMANCE
# ==========================================================

def get_correlation_performance(
    session,
):
    """
    Correlation metrics for the current persistent dataset.
    """
    cutoff = recent_cutoff()

    correlated_sources = safe_int(
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
                .is_not(None)
            )
            .where(
                EventGroupSource.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    grouped_sources = safe_int(
        session.execute(
            select(
                func.count(
                    EventGroupSource.id
                )
            )
            .where(
                EventGroupSource.published_at
                .is_not(None)
            )
            .where(
                EventGroupSource.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    event_groups = safe_int(
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

    multi_source_groups = safe_int(
        session.execute(
            select(
                func.count(
                    EventGroup.id
                )
            )
            .where(
                EventGroup.source_count
                >= 2
            )
            .where(
                EventGroup.status
                == "ACTIVE"
            )
        )
        .scalar_one()
    )

    strongest_match = safe_float(
        session.execute(
            select(
                func.max(
                    EventGroupSource.correlation_score
                )
            )
        )
        .scalar_one()
    )

    operational_events = safe_int(
        session.execute(
            select(
                func.count(
                    Post.id
                )
            )
            .where(
                Post.published_at
                .is_not(None)
            )
            .where(
                Post.published_at
                >= cutoff
            )
        )
        .scalar_one()
    )

    return {
        "correlated_events": correlated_sources,
        "correlated_sources": correlated_sources,
        "grouped_sources": grouped_sources,
        "event_groups": event_groups,
        "active_groups": event_groups,
        "multi_source_groups": multi_source_groups,
        "strongest_match": round(
            strongest_match,
            3,
        ),
        "correlation_rate": safe_percent(
            correlated_sources,
            operational_events,
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
                "group_id": group.id,
                "event_type": group.event_type,
                "primary_location": (
                    group.primary_location
                    or "-"
                ),
                "location": (
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
                "primary_region": (
                    group.primary_region
                    or "GLOBAL"
                ),
                "confidence": safe_float(
                    group.confidence
                ),
                "average_confidence": safe_float(
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
                "text": (
                    group.representative_text
                    or ""
                ),
            }
        )

    return results


# ==========================================================
# ASSESSMENT
# ==========================================================

def determine_activity_level(
    operational_events,
):
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


def build_assessment_summary(
    *,
    operational_events,
    influence_signals,
    access_signals,
    correlated_events,
    active_groups,
    dominant_region,
    dominant_event,
    dominant_source,
    average_confidence,
    activity_level,
):
    """
    Deterministic dashboard summary. No generated claims are added.
    """
    return (
        f"Az elmúlt 24 órában a rendszer "
        f"{operational_events} operatív migrációs eseményt, "
        f"{influence_signals} influence/early-warning jelzést és "
        f"{access_signals} átkelési vagy bejutási jelzést tart nyilván. "
        f"{correlated_events} friss eseményforrás korrelált más forrással. "
        f"Jelenleg {active_groups} aktív eseménycsoport szerepel az adatbázisban. "
        f"A legerősebb regionális aktivitás: "
        f"{humanize_token(dominant_region)}. "
        f"A domináns operatív eseménytípus: "
        f"{humanize_token(dominant_event)}. "
        f"A legaktívabb adatforrás: "
        f"{humanize_token(dominant_source)}. "
        f"Az aktív eseménycsoportok átlagos konfidenciája "
        f"{average_confidence:.2f}. "
        f"A jelenlegi aktivitási szint: {activity_level}."
    )


def get_operational_assessment(
    session,
    *,
    kpis,
    region_activity,
    source_activity,
    correlation,
    influence_signals,
    crossing_access_signals,
):
    """
    Builds the analytical state shown on the dashboard.
    """
    operational_events = safe_int(
        kpis.get(
            "operational_events"
        )
    )

    active_groups = safe_int(
        kpis.get(
            "active_event_groups"
        )
    )

    correlated_events = safe_int(
        correlation.get(
            "correlated_events"
        )
    )

    geographic_regions = [
        row
        for row in region_activity
        if str(
            row.get(
                "region"
            )
            or ""
        ).upper()
        not in {
            "",
            "GLOBAL",
            "UNKNOWN",
            "N/A",
        }
    ]

    dominant_region = (
        geographic_regions[
            0
        ].get(
            "region"
        )
        if geographic_regions
        else (
            region_activity[
                0
            ].get(
                "region"
            )
            if region_activity
            else "GLOBAL"
        )
    )

    dominant_source = (
        source_activity[
            0
        ].get(
            "source"
        )
        if source_activity
        else "UNKNOWN"
    )

    event_type_rows = (
        session.execute(
            select(
                Post.signal_type,
                func.count(
                    Post.id
                ),
            )
            .where(
                Post.published_at
                .is_not(None)
            )
            .where(
                Post.published_at
                >= recent_cutoff()
            )
            .group_by(
                Post.signal_type
            )
            .order_by(
                func.count(
                    Post.id
                ).desc()
            )
        )
        .all()
    )

    dominant_event = (
        event_type_rows[
            0
        ][
            0
        ]
        if event_type_rows
        else "GENERAL_DISCUSSION"
    )

    average_confidence = safe_float(
        session.execute(
            select(
                func.avg(
                    EventGroup.confidence
                )
            )
            .where(
                EventGroup.status
                == "ACTIVE"
            )
            .where(
                EventGroup.confidence
                .is_not(None)
            )
        )
        .scalar_one()
    )

    activity_level = (
        determine_activity_level(
            operational_events
        )
    )

    technical_health = (
        get_technical_health(
            session
        )
    )

    summary = build_assessment_summary(
        operational_events=operational_events,
        influence_signals=len(
            influence_signals
        ),
        access_signals=len(
            crossing_access_signals
        ),
        correlated_events=correlated_events,
        active_groups=active_groups,
        dominant_region=dominant_region,
        dominant_event=dominant_event,
        dominant_source=dominant_source,
        average_confidence=average_confidence,
        activity_level=activity_level,
    )

    return {
        "operational_events_24h": operational_events,
        "influence_signals_24h": len(
            influence_signals
        ),
        "access_signals_24h": len(
            crossing_access_signals
        ),
        "correlated_events_24h": correlated_events,
        "active_event_groups": active_groups,

        "dominant_region": dominant_region,
        "hotspot": dominant_region,
        "dominant_event_type": dominant_event,
        "dominant_source": dominant_source,

        "average_confidence": round(
            average_confidence,
            3,
        ),

        "confidence_level": (
            "HIGH"
            if average_confidence >= 0.75
            else (
                "MEDIUM"
                if average_confidence >= 0.50
                else "LOW"
            )
        ),

        "correlation_rate": safe_float(
            correlation.get(
                "correlation_rate"
            )
        ),

        "activity_level": activity_level,

        # Legacy field retained, but now correctly technical.
        "system_health": technical_health.get(
            "status"
        ),

        "summary": summary,
    }


# ==========================================================
# HIGH PRIORITY ANALYST QUEUE
# ==========================================================

def get_high_priority_intelligence(
    *,
    influence_signals,
    crossing_access_signals,
    high_confidence_events,
    limit=12,
):
    """
    Narrative-level analyst-review queue.
    Repeated social posts are collapsed before ranking.
    """
    candidates = []

    narrative_signals = get_top_crossing_access_posts(
        list(influence_signals)
    )

    for item in narrative_signals:
        candidate = dict(item)

        candidate["priority_score"] = calculate_priority_score(
            candidate
        )

        candidate["analyst_priority"] = priority_level_from_score(
            candidate["priority_score"],
            related_posts_count=safe_int(
                candidate.get("related_posts_count"),
                1,
            ),
            independent_authors=safe_int(
                candidate.get("independent_author_count"),
                0,
            ),
            platform_count=safe_int(
                candidate.get("platform_count"),
                1,
            ),
        )

        candidates.append(candidate)

    for item in high_confidence_events:
        candidate = dict(item)

        candidate["priority_score"] = calculate_priority_score(
            candidate
        )

        candidate["analyst_priority"] = priority_level_from_score(
            candidate["priority_score"],
            related_posts_count=safe_int(
                candidate.get("source_count"),
                1,
            ),
            independent_authors=0,
            platform_count=1,
        )

        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            safe_float(item.get("priority_score")),
            safe_float(
                item.get("confidence")
                or item.get("average_confidence")
            ),
            item.get("published_at")
            or item.get("last_seen")
            or "",
        ),
        reverse=True,
    )

    return candidates[:limit]



# ==========================================================
# SIGNAL TIMELINE V1
# ==========================================================

def timeline_timestamp_value(
    item,
):
    """
    Returns a sortable datetime-like string value.
    """
    return (
        item.get("timestamp")
        or ""
    )


def timeline_excerpt(
    value,
    limit=420,
):
    """
    Compact text excerpt for timeline presentation.
    """
    text = str(
        value
        or ""
    ).strip()

    if len(text) <= limit:
        return text

    return (
        text[:limit].rstrip()
        + "…"
    )


TIMELINE_INFORMATION_PATTERNS = [
    # Physical border / crossing context
    (
        "border",
        r"\bborder(?:s)?\b",
        1,
    ),
    (
        "crossing",
        r"\bcross(?:ing|ings|ed|es)?\b",
        1,
    ),
    (
        "channel",
        r"\bchannel\b",
        1,
    ),
    (
        "route",
        r"\broute(?:s)?\b",
        1,
    ),
    (
        "checkpoint",
        r"\bcheckpoint(?:s)?\b",
        1,
    ),
    (
        "tunnel",
        r"\btunnel(?:s)?\b",
        1,
    ),

    # Sea movement
    (
        "boat",
        r"\bboat(?:s)?\b",
        1,
    ),
    (
        "dinghy",
        r"\bdingh(?:y|ies)\b",
        1,
    ),
    (
        "vessel",
        r"\bvessel(?:s)?\b",
        1,
    ),
    (
        "sea",
        r"\bsea\b",
        1,
    ),
    (
        "coast_guard",
        r"\bcoast\s+guard\b",
        1,
    ),

    # Enforcement / rescue
    (
        "interception",
        r"\bintercept(?:ed|ion|ions|ing)?\b",
        1,
    ),
    (
        "rescue",
        r"\brescu(?:e|ed|es|ing)\b",
        1,
    ),
    (
        "detention",
        r"\bdetain(?:ed|ing)?\b|\bdetention\b",
        1,
    ),
    (
        "deportation",
        r"\bdeport(?:ed|ation|ations|ing)?\b",
        1,
    ),

    # Smuggling / facilitation
    (
        "smuggling",
        r"\bsmuggl(?:e|er|ers|ing)\b",
        1,
    ),
    (
        "trafficking",
        r"\btraffick(?:er|ers|ing)\b",
        1,
    ),

    # Reception / camp infrastructure
    (
        "reception_centre",
        r"\breception\s+cent(?:er|re)s?\b",
        1,
    ),
    (
        "refugee_camp",
        r"\brefugee\s+camp(?:s)?\b",
        1,
    ),
    (
        "migrant_camp",
        r"\bmigrant\s+camp(?:s)?\b",
        1,
    ),

    # Concrete movement / arrival wording
    (
        "arrival",
        r"\barriv(?:e|ed|al|als|ing)\b",
        1,
    ),
    (
        "landing",
        r"\bland(?:ed|ing|ings)\b",
        1,
    ),
    (
        "departure",
        r"\bdepart(?:ed|ure|ures|ing)\b",
        1,
    ),
]

TIMELINE_INFORMATION_FRESHNESS_PATTERNS = [
    (
        "today",
        r"\btoday\b",
    ),
    (
        "tonight",
        r"\btonight\b",
    ),
    (
        "yesterday",
        r"\byesterday\b",
    ),
    (
        "breaking",
        r"\bbreaking\b",
    ),
    (
        "latest",
        r"\blatest\b",
    ),
    (
        "now",
        r"\bnow\b",
    ),
    (
        "hours_ago",
        r"\bhours?\s+ago\b",
    ),
]


def score_information_candidate(
    post,
):
    """
    Scores a filtered CollectedPost for the INFORMATION layer.

    The INFORMATION layer is not a second event detector. It is a compact
    analyst-context layer for posts that were rejected by the operational
    pipeline but still contain multiple concrete migration-operational cues.

    Returns:
        {
            "score": int,
            "matched_cues": list[str],
            "freshness_cues": list[str],
        }
    """

    text = str(
        post.text
        or ""
    ).strip()

    if not text:
        return {
            "score": 0,
            "matched_cues": [],
            "freshness_cues": [],
        }

    matched_cues = []
    score = 0

    for (
        cue_name,
        pattern,
        weight,
    ) in TIMELINE_INFORMATION_PATTERNS:

        if not re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            continue

        matched_cues.append(
            cue_name
        )

        score += weight

    freshness_cues = []

    for (
        cue_name,
        pattern,
    ) in TIMELINE_INFORMATION_FRESHNESS_PATTERNS:

        if not re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            continue

        freshness_cues.append(
            cue_name
        )

    # Freshness helps ranking but cannot make a generic post eligible by
    # itself. At least two migration-operational context cues are still
    # required below.
    if freshness_cues:
        score += 1

    # Repeated collection across runs/queries is weak supporting evidence that
    # a post is persistent in the monitored information space.
    collection_count = safe_int(
        post.collection_count,
        1,
    )

    if collection_count >= 2:
        score += 1

    return {
        "score": score,
        "matched_cues": matched_cues,
        "freshness_cues": freshness_cues,
    }


def get_signal_timeline(
    session,
    hours=TIMELINE_WINDOW_HOURS,
):
    """
    Builds one unified timeline from the existing persistent database.

    Layers:
        INFORMATION
            Selected non-operational, non-noise CollectedPost records that
            were close enough to the operational threshold to remain useful
            for analyst context.

        EARLY_WARNING
            Persistent InfluenceSignal records.

        OPERATIONAL
            Operational Post records.

        CORRELATED
            EventGroupSource records that were linked to an EventGroup with
            a non-null correlation score.

    No new database table is required. This function is an export/view layer
    only and does not mutate the analytical pipeline.
    """

    cutoff = (
        utc_now()
        - timedelta(
            hours=hours
        )
    )

    items = []

    # ------------------------------------------------------
    # INFORMATION LAYER
    # ------------------------------------------------------
    #
    # The full filtered-post history remains stored in CollectedPost.
    # Timeline V1.1 does NOT expose every rejected post. Instead it ranks
    # recent non-operational, non-noise, non-influence posts by concrete
    # migration-operational context cues and keeps only a small analyst-
    # useful subset.
    # ------------------------------------------------------

    information_candidates = (
        session.execute(
            select(
                CollectedPost
            )
            .where(
                CollectedPost.published_at
                .is_not(None)
            )
            .where(
                CollectedPost.published_at
                >= cutoff
            )
            .where(
                CollectedPost.is_noise
                == False  # noqa: E712
            )
            .where(
                CollectedPost.is_operational
                == False  # noqa: E712
            )
            .where(
                CollectedPost.influence_detected
                == False  # noqa: E712
            )
            .order_by(
                CollectedPost.published_at.desc(),
                CollectedPost.id.desc(),
            )
            .limit(
                TIMELINE_INFORMATION_CANDIDATE_LIMIT
            )
        )
        .scalars()
        .all()
    )

    scored_information = []

    for post in information_candidates:
        score_result = (
            score_information_candidate(
                post
            )
        )

        # Require at least two distinct migration-operational cues.
        # This prevents generic political discussion containing one word
        # such as "migration" or "refugee" from filling the timeline.
        if (
            len(
                score_result.get(
                    "matched_cues",
                    [],
                )
            )
            < 2
        ):
            continue

        if (
            safe_int(
                score_result.get(
                    "score"
                )
            )
            < TIMELINE_INFORMATION_MIN_SCORE
        ):
            continue

        scored_information.append(
            (
                safe_int(
                    score_result.get(
                        "score"
                    )
                ),
                post.published_at,
                post,
                score_result,
            )
        )

    scored_information.sort(
        key=lambda row: (
            row[0],
            row[1]
            or datetime.min,
        ),
        reverse=True,
    )

    scored_information = (
        scored_information[
            :TIMELINE_INFORMATION_LIMIT
        ]
    )

    for (
        information_score,
        _published_at,
        post,
        score_result,
    ) in scored_information:

        confidence = safe_float(
            post.operational_confidence
        )

        items.append(
            {
                "timeline_id": (
                    f"information:{post.id}"
                ),
                "timestamp": format_datetime(
                    post.published_at
                ),
                "layer": "INFORMATION",
                "type": "INFORMATION_SIGNAL",
                "signal_type": "INFORMATION_SIGNAL",
                "event_type": None,

                "source": (
                    post.source
                    or "UNKNOWN"
                ),
                "source_post_id": (
                    post.source_post_id
                ),
                "author": post.author,
                "url": post.url,
                "source_url": post.url,

                "region": "GLOBAL",
                "primary_region": "GLOBAL",
                "location": "-",
                "primary_location": "-",
                "country": "-",

                "confidence": confidence,
                "priority": "INFO",
                "priority_score": round(
                    information_score
                    * 10,
                    2,
                ),

                "information_score": (
                    information_score
                ),
                "matched_information_cues": (
                    score_result.get(
                        "matched_cues",
                        []
                    )
                ),
                "freshness_cues": (
                    score_result.get(
                        "freshness_cues",
                        []
                    )
                ),

                "text": post.text or "",
                "text_excerpt": timeline_excerpt(
                    post.text
                ),

                "event_group_id": None,
                "correlation_score": None,
                "related_source_count": None,

                "is_operational": False,
                "influence_detected": False,
                "first_collected_at": format_datetime(
                    post.first_collected_at
                ),
                "last_collected_at": format_datetime(
                    post.last_collected_at
                ),
                "collection_count": safe_int(
                    post.collection_count,
                    1,
                ),
            }
        )

    # ------------------------------------------------------
    # EARLY-WARNING / INFLUENCE LAYER
    # ------------------------------------------------------

    influence_rows = (
        session.execute(
            select(
                InfluenceSignal
            )
            .where(
                InfluenceSignal.published_at
                .is_not(None)
            )
            .where(
                InfluenceSignal.published_at
                >= cutoff
            )
            .order_by(
                InfluenceSignal.published_at.desc(),
                InfluenceSignal.confidence.desc(),
                InfluenceSignal.id.desc(),
            )
            .limit(
                TIMELINE_ITEM_LIMIT
            )
        )
        .scalars()
        .all()
    )

    for signal in influence_rows:
        serialized = (
            serialize_influence_signal(
                signal
            )
        )

        items.append(
            {
                "timeline_id": (
                    f"early_warning:{signal.id}"
                ),
                "timestamp": format_datetime(
                    signal.published_at
                ),
                "layer": "EARLY_WARNING",
                "type": signal.primary_signal,
                "signal_type": signal.primary_signal,
                "event_type": None,

                "source": (
                    signal.source
                    or "UNKNOWN"
                ),
                "source_post_id": (
                    signal.source_post_id
                ),
                "author": signal.author,
                "url": signal.source_url,
                "source_url": signal.source_url,

                "region": (
                    signal.primary_region
                    or "GLOBAL"
                ),
                "primary_region": (
                    signal.primary_region
                    or "GLOBAL"
                ),
                "location": (
                    signal.primary_location
                    or "-"
                ),
                "primary_location": (
                    signal.primary_location
                    or "-"
                ),
                "country": (
                    signal.country
                    or "-"
                ),

                "confidence": safe_float(
                    signal.confidence
                ),
                "priority": (
                    signal.priority
                    or "LOW"
                ),
                "priority_score": (
                    serialized.get(
                        "priority_score"
                    )
                ),
                "analyst_priority": (
                    serialized.get(
                        "analyst_priority"
                    )
                ),

                "text": signal.text or "",
                "text_excerpt": timeline_excerpt(
                    signal.text
                ),

                "event_group_id": None,
                "correlation_score": None,
                "related_source_count": None,

                "signal_mode": (
                    signal.signal_mode
                ),
                "signal_intent": (
                    signal.signal_intent
                ),
                "detection_count": safe_int(
                    signal.detection_count,
                    1,
                ),
                "first_detected_at": (
                    format_datetime(
                        signal.first_detected_at
                    )
                ),
                "last_detected_at": (
                    format_datetime(
                        signal.last_detected_at
                    )
                ),
            }
        )

    # ------------------------------------------------------
    # OPERATIONAL EVENT LAYER
    # ------------------------------------------------------

    operational_rows = (
        session.execute(
            select(
                Post
            )
            .where(
                Post.published_at
                .is_not(None)
            )
            .where(
                Post.published_at
                >= cutoff
            )
            .order_by(
                Post.published_at.desc(),
                Post.id.desc(),
            )
            .limit(
                TIMELINE_ITEM_LIMIT
            )
        )
        .scalars()
        .all()
    )

    for post in operational_rows:
        locations = deserialize_json_text(
            post.locations,
            default=[],
        )

        primary_location = None

        if (
            isinstance(
                locations,
                list,
            )
            and locations
            and isinstance(
                locations[0],
                dict,
            )
        ):
            primary_location = (
                locations[0]
            )

        location_name = (
            primary_location.get(
                "name"
            )
            if primary_location
            else None
        )

        country = (
            primary_location.get(
                "country"
            )
            if primary_location
            else None
        )

        event_group_source = (
            session.execute(
                select(
                    EventGroupSource
                )
                .where(
                    EventGroupSource.post_id
                    == post.id
                )
                .order_by(
                    EventGroupSource.id.desc()
                )
                .limit(1)
            )
            .scalars()
            .first()
        )

        event_group_id = (
            event_group_source.event_group_id
            if event_group_source
            else None
        )

        items.append(
            {
                "timeline_id": (
                    f"operational:{post.id}"
                ),
                "timestamp": format_datetime(
                    post.published_at
                ),
                "layer": "OPERATIONAL",
                "type": (
                    post.signal_type
                    or "GENERAL_DISCUSSION"
                ),
                "signal_type": (
                    post.signal_type
                    or "GENERAL_DISCUSSION"
                ),
                "event_type": (
                    post.signal_type
                    or "GENERAL_DISCUSSION"
                ),

                "source": (
                    post.source
                    or "UNKNOWN"
                ),
                "source_post_id": post.post_id,
                "author": post.author,
                "url": post.url,
                "source_url": post.url,

                "region": "GLOBAL",
                "primary_region": "GLOBAL",
                "location": (
                    location_name
                    or "-"
                ),
                "primary_location": (
                    location_name
                    or "-"
                ),
                "country": (
                    country
                    or "-"
                ),

                "latitude": post.latitude,
                "longitude": post.longitude,

                "confidence": safe_float(
                    post.extraction_confidence
                ),
                "priority": (
                    "HIGH"
                    if safe_float(
                        post.extraction_confidence
                    ) >= HIGH_CONFIDENCE_THRESHOLD
                    else "MEDIUM"
                    if safe_float(
                        post.extraction_confidence
                    ) >= 0.50
                    else "LOW"
                ),
                "priority_score": round(
                    safe_float(
                        post.extraction_confidence
                    )
                    * 100,
                    2,
                ),

                "text": post.text or "",
                "text_excerpt": timeline_excerpt(
                    post.text
                ),

                "event_group_id": (
                    event_group_id
                ),
                "correlation_score": (
                    safe_float(
                        event_group_source.correlation_score
                    )
                    if (
                        event_group_source
                        and event_group_source.correlation_score
                        is not None
                    )
                    else None
                ),
                "related_source_count": None,

                "event_time_text": (
                    post.event_time_text
                ),
                "event_time_normalized": (
                    post.event_time_normalized
                ),
                "event_time_confidence": (
                    post.event_time_confidence
                ),
            }
        )

    # ------------------------------------------------------
    # CORRELATED EVENT LAYER
    # ------------------------------------------------------

    correlated_rows = (
        session.execute(
            select(
                EventGroupSource
            )
            .where(
                EventGroupSource.correlation_score
                .is_not(None)
            )
            .where(
                EventGroupSource.published_at
                .is_not(None)
            )
            .where(
                EventGroupSource.published_at
                >= cutoff
            )
            .order_by(
                EventGroupSource.published_at.desc(),
                EventGroupSource.correlation_score.desc(),
                EventGroupSource.id.desc(),
            )
            .limit(
                TIMELINE_ITEM_LIMIT
            )
        )
        .scalars()
        .all()
    )

    group_ids = {
        row.event_group_id
        for row in correlated_rows
        if row.event_group_id is not None
    }

    group_map = {}

    if group_ids:
        groups = (
            session.execute(
                select(
                    EventGroup
                )
                .where(
                    EventGroup.id.in_(
                        group_ids
                    )
                )
            )
            .scalars()
            .all()
        )

        group_map = {
            group.id: group
            for group in groups
        }

    for link in correlated_rows:
        group = group_map.get(
            link.event_group_id
        )

        group_event_type = (
            group.event_type
            if group
            else link.event_type
        )

        items.append(
            {
                "timeline_id": (
                    f"correlated:{link.id}"
                ),
                "timestamp": format_datetime(
                    link.published_at
                    or link.created_at
                ),
                "layer": "CORRELATED",
                "type": (
                    group_event_type
                    or "CORRELATED_EVENT"
                ),
                "signal_type": (
                    group_event_type
                    or "CORRELATED_EVENT"
                ),
                "event_type": (
                    group_event_type
                    or "CORRELATED_EVENT"
                ),

                "source": (
                    link.source
                    or "UNKNOWN"
                ),
                "source_post_id": (
                    link.source_post_id
                ),
                "author": link.author,
                "url": link.source_url,
                "source_url": link.source_url,

                "region": (
                    group.primary_region
                    if (
                        group
                        and group.primary_region
                    )
                    else "GLOBAL"
                ),
                "primary_region": (
                    group.primary_region
                    if (
                        group
                        and group.primary_region
                    )
                    else "GLOBAL"
                ),
                "location": (
                    group.primary_location
                    if (
                        group
                        and group.primary_location
                    )
                    else "-"
                ),
                "primary_location": (
                    group.primary_location
                    if (
                        group
                        and group.primary_location
                    )
                    else "-"
                ),
                "country": (
                    group.country
                    if (
                        group
                        and group.country
                    )
                    else "-"
                ),

                "latitude": (
                    group.latitude
                    if group
                    else None
                ),
                "longitude": (
                    group.longitude
                    if group
                    else None
                ),

                "confidence": (
                    safe_float(
                        group.confidence
                    )
                    if group
                    else 0.0
                ),
                "priority": (
                    "HIGH"
                    if (
                        group
                        and safe_float(
                            group.confidence
                        )
                        >= HIGH_CONFIDENCE_THRESHOLD
                    )
                    else "MEDIUM"
                ),
                "priority_score": (
                    round(
                        safe_float(
                            group.confidence
                        )
                        * 100,
                        2,
                    )
                    if group
                    else 0.0
                ),

                "text": (
                    link.text
                    or (
                        group.representative_text
                        if group
                        else ""
                    )
                    or ""
                ),
                "text_excerpt": timeline_excerpt(
                    link.text
                    or (
                        group.representative_text
                        if group
                        else ""
                    )
                ),

                "event_group_id": (
                    link.event_group_id
                ),
                "correlation_score": (
                    safe_float(
                        link.correlation_score
                    )
                ),
                "related_source_count": (
                    safe_int(
                        group.source_count,
                        1,
                    )
                    if group
                    else 1
                ),
                "source_types": (
                    deserialize_source_types(
                        group.source_types
                    )
                    if group
                    else []
                ),
            }
        )

    # ------------------------------------------------------
    # SORT / LIMIT / SUMMARY
    # ------------------------------------------------------

    items.sort(
        key=timeline_timestamp_value,
        reverse=True,
    )

    items = items[
        :TIMELINE_ITEM_LIMIT
    ]

    layer_counts = Counter(
        item.get(
            "layer"
        )
        for item in items
    )

    source_counts = Counter(
        item.get(
            "source"
        )
        for item in items
        if item.get(
            "source"
        )
    )

    type_counts = Counter(
        item.get(
            "type"
        )
        for item in items
        if item.get(
            "type"
        )
    )

    return {
        "schema_version": "1.1",
        "window_hours": hours,
        "default_window": "7D",
        "available_windows_hours": [
            24,
            72,
            168,
        ],
        "generated_at": format_datetime(
            utc_now()
        ),

        "total_items": len(
            items
        ),

        "information_count": safe_int(
            layer_counts.get(
                "INFORMATION"
            )
        ),
        "early_warning_count": safe_int(
            layer_counts.get(
                "EARLY_WARNING"
            )
        ),
        "operational_count": safe_int(
            layer_counts.get(
                "OPERATIONAL"
            )
        ),
        "correlated_count": safe_int(
            layer_counts.get(
                "CORRELATED"
            )
        ),

        "layer_counts": dict(
            layer_counts
        ),
        "source_counts": dict(
            source_counts
        ),
        "type_counts": dict(
            type_counts
        ),

        "items": items,
    }


# ==========================================================
# COMPLETE DASHBOARD PAYLOAD
# ==========================================================

def build_dashboard_data(
    session,
):
    """
    Builds the complete V3 dashboard JSON structure.
    """
    current_run = get_current_run(
        session
    )

    technical_health = (
        get_technical_health(
            session
        )
    )

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

    influence_signals = (
        get_influence_signals(
            session
        )
    )

    crossing_access_signals = (
        get_crossing_access_signals(
            session
        )
    )

    top_crossing_access_posts = (
        get_top_crossing_access_posts(
            crossing_access_signals
        )
    )

    influence_narratives = (
        get_top_crossing_access_posts(
            influence_signals
        )
    )

    weekly_activity = (
        get_information_activity_weekly(
            session
        )
    )

    weekly_summary = (
        get_information_activity_summary(
            session,
            weekly_activity,
        )
    )

    high_confidence_events = (
        get_high_confidence_events(
            session
        )
    )

    signal_timeline = (
        get_signal_timeline(
            session
        )
    )

    high_priority_intelligence = (
        get_high_priority_intelligence(
            influence_signals=influence_signals,
            crossing_access_signals=(
                crossing_access_signals
            ),
            high_confidence_events=(
                high_confidence_events
            ),
        )
    )

    kpis["access_signals_raw"] = len(
        crossing_access_signals
    )

    kpis["access_signals"] = len(
        top_crossing_access_posts
    )

    kpis["influence_signals_raw"] = len(
        influence_signals
    )

    kpis["influence_narratives"] = len(
        influence_narratives
    )

    kpis["high_priority"] = sum(
        1
        for item in high_priority_intelligence
        if str(
            item.get("analyst_priority")
            or ""
        ).upper()
        in {
            "HIGH",
            "CRITICAL",
        }
    )

    operational_assessment = (
        get_operational_assessment(
            session=session,
            kpis=kpis,
            region_activity=region_activity,
            source_activity=source_activity,
            correlation=correlation,
            influence_signals=influence_signals,
            crossing_access_signals=(
                crossing_access_signals
            ),
        )
    )

    return {
        "schema_version": "3.0",

        "updated_at": format_datetime(
            utc_now()
        ),
        "generated_at": format_datetime(
            utc_now()
        ),

        "current_run": current_run,

        "kpis": kpis,

        "live_events": live_events,
        "event_groups": event_groups,

        # New V3 names
        "regions": region_activity,
        "sources": source_activity,

        # Legacy names kept for compatibility
        "region_activity": region_activity,
        "source_activity": source_activity,

        "correlation": correlation,

        "technical_health": (
            technical_health.get(
                "status"
            )
        ),
        "collector_health": (
            technical_health.get(
                "status"
            )
        ),
        "technical_health_detail": (
            technical_health
        ),

        "operational_assessment": (
            operational_assessment
        ),
        "analytical_assessment": (
            operational_assessment
        ),

        "high_confidence_events": (
            high_confidence_events
        ),

        "high_priority_intelligence": (
            high_priority_intelligence
        ),

        "influence_signals": (
            influence_signals
        ),
        "early_warning_signals": (
            influence_signals
        ),
        "influence_narratives": (
            influence_narratives
        ),

        "crossing_access_signals": (
            crossing_access_signals
        ),
        "access_signals": (
            crossing_access_signals
        ),
        "top_crossing_access_posts": (
            top_crossing_access_posts
        ),
        "crossing_access_narratives": (
            top_crossing_access_posts
        ),

        "information_activity_weekly": (
            weekly_activity
        ),
        "weekly_post_activity": (
            weekly_activity
        ),
        "information_activity_summary": (
            weekly_summary
        ),

        # Timeline V1
        "signal_timeline": (
            signal_timeline
        ),
    }


# ==========================================================
# EXPORT
# ==========================================================

def export_dashboard_data():
    """
    Exports dashboard-data.json to the repository root.
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
            "DASHBOARD DATA EXPORT V3"
        )

        print(
            "==================================="
        )

        print(
            f"Output: "
            f"{OUTPUT_FILE}"
        )

        print(
            "Current run ID: "
            f"{data['current_run'].get('id')}"
        )

        print(
            "Current run status: "
            f"{data['current_run'].get('status')}"
        )

        print(
            "Operational events (24h): "
            f"{data['kpis']['operational_events']}"
        )

        print(
            "Influence signals (24h): "
            f"{len(data['influence_signals'])}"
        )

        print(
            "Crossing/access signals (24h): "
            f"{len(data['crossing_access_signals'])}"
        )

        print(
            "Top crossing/access posts: "
            f"{len(data['top_crossing_access_posts'])}"
        )

        print(
            "High-priority analyst queue: "
            f"{len(data['high_priority_intelligence'])}"
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
            "Weekly history rows: "
            f"{len(data['information_activity_weekly'])}"
        )

        print(
            "Current week posts: "
            f"{data['information_activity_summary']['current_week']}"
        )

        print(
            "Previous week same-period posts: "
            f"{data['information_activity_summary']['previous_week']}"
        )

        print(
            "Weekly change: "
            f"{data['information_activity_summary']['change_label']}"
        )

        print(
            "Signal timeline items (7d): "
            f"{data['signal_timeline']['total_items']}"
        )

        print(
            "Timeline layers: "
            f"{data['signal_timeline']['layer_counts']}"
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
            "Activity level: "
            f"{data['operational_assessment']['activity_level']}"
        )

        print(
            "Technical health: "
            f"{data['technical_health']}"
        )

        print(
            "Dashboard data exported successfully."
        )

    finally:
        session.close()


if __name__ == "__main__":
    export_dashboard_data()
