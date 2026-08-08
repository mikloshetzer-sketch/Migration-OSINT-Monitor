"""
Migration OSINT Monitor

File:
models.py

Description:
SQLAlchemy database models for:

- operational migration events
- correlated EventGroups
- raw collected social-media post history
- migration influence / early-warning signals
- monitor run history

The existing operational Post -> EventGroup -> EventGroupSource
pipeline is preserved. The additional tables form a parallel
history / influence layer and do not change the existing event
classification or correlation schema.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.orm import declarative_base


Base = declarative_base()


# ==========================================================
# EXISTING OPERATIONAL EVENT MODEL
# ==========================================================


class Post(Base):
    """
    Existing operational event/post record.

    IMPORTANT:
    This model remains the storage layer used by the current
    operational event pipeline and correlation engine.
    """

    __tablename__ = "posts"

    id = Column(
        Integer,
        primary_key=True,
    )

    source = Column(
        String(50),
        nullable=False,
    )

    post_id = Column(
        String(255),
        nullable=False,
    )

    author = Column(
        String(255),
        nullable=True,
    )

    text = Column(
        Text,
        nullable=False,
    )

    language = Column(
        String(20),
        nullable=True,
    )

    published_at = Column(
        DateTime,
        nullable=True,
    )

    collected_at = Column(
        DateTime,
        nullable=False,
    )

    url = Column(
        Text,
        nullable=True,
    )

    relevance_score = Column(
        Float,
        nullable=True,
    )

    signal_type = Column(
        String(100),
        nullable=True,
    )

    locations = Column(
        Text,
        nullable=True,
    )

    origin_location = Column(
        String(255),
        nullable=True,
    )

    destination_location = Column(
        String(255),
        nullable=True,
    )

    event_time_text = Column(
        String(255),
        nullable=True,
    )

    event_time_normalized = Column(
        String(255),
        nullable=True,
    )

    event_time_confidence = Column(
        Float,
        nullable=True,
    )

    latitude = Column(
        Float,
        nullable=True,
    )

    longitude = Column(
        Float,
        nullable=True,
    )

    extraction_confidence = Column(
        Float,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "post_id",
            name="uq_source_post_id",
        ),
    )


# ==========================================================
# EXISTING CORRELATED EVENT GROUP MODEL
# ==========================================================


class EventGroup(Base):
    """
    Represents one correlated real-world operational event.

    Multiple source posts can belong to the same EventGroup.
    """

    __tablename__ = "event_groups"

    id = Column(
        Integer,
        primary_key=True,
    )

    event_type = Column(
        String(100),
        nullable=False,
    )

    title = Column(
        String(500),
        nullable=True,
    )

    representative_text = Column(
        Text,
        nullable=True,
    )

    primary_region = Column(
        String(100),
        nullable=True,
    )

    primary_location = Column(
        String(255),
        nullable=True,
    )

    country = Column(
        String(100),
        nullable=True,
    )

    latitude = Column(
        Float,
        nullable=True,
    )

    longitude = Column(
        Float,
        nullable=True,
    )

    first_seen = Column(
        DateTime,
        nullable=True,
    )

    last_seen = Column(
        DateTime,
        nullable=True,
    )

    source_count = Column(
        Integer,
        nullable=False,
        default=1,
    )

    source_types = Column(
        Text,
        nullable=True,
    )

    status = Column(
        String(50),
        nullable=False,
        default="ACTIVE",
    )

    confidence = Column(
        Float,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        nullable=True,
    )

    updated_at = Column(
        DateTime,
        nullable=True,
    )


# ==========================================================
# EXISTING EVENT GROUP SOURCE LINK
# ==========================================================


class EventGroupSource(Base):
    """
    Links an individual source post/event to an EventGroup.
    """

    __tablename__ = "event_group_sources"

    id = Column(
        Integer,
        primary_key=True,
    )

    event_group_id = Column(
        Integer,
        ForeignKey(
            "event_groups.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    post_id = Column(
        Integer,
        ForeignKey(
            "posts.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    source = Column(
        String(50),
        nullable=True,
    )

    source_post_id = Column(
        String(255),
        nullable=True,
    )

    author = Column(
        String(255),
        nullable=True,
    )

    published_at = Column(
        DateTime,
        nullable=True,
    )

    event_type = Column(
        String(100),
        nullable=True,
    )

    text = Column(
        Text,
        nullable=True,
    )

    source_url = Column(
        Text,
        nullable=True,
    )

    correlation_score = Column(
        Float,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "event_group_id",
            "source",
            "source_post_id",
            name="uq_event_group_source",
        ),
    )


# ==========================================================
# NEW: MONITOR RUN HISTORY
# ==========================================================


class MonitorRun(Base):
    """
    Stores one complete Migration OSINT Monitor execution.

    The repository can currently be started manually. This table
    makes every execution auditable and allows the dashboard to
    distinguish:

    - CURRENT RUN
    - LAST 24 HOURS
    - historical trends

    It stores summary counters only. It does not replace any
    operational event tables.
    """

    __tablename__ = "monitor_runs"

    id = Column(
        Integer,
        primary_key=True,
    )

    run_uuid = Column(
        String(64),
        nullable=False,
        unique=True,
    )

    started_at = Column(
        DateTime,
        nullable=False,
    )

    completed_at = Column(
        DateTime,
        nullable=True,
    )

    status = Column(
        String(50),
        nullable=False,
        default="RUNNING",
    )

    # ------------------------------------------------------
    # COLLECTION COUNTERS
    # ------------------------------------------------------

    posts_returned = Column(
        Integer,
        nullable=False,
        default=0,
    )

    unique_posts_collected = Column(
        Integer,
        nullable=False,
        default=0,
    )

    x_posts_returned = Column(
        Integer,
        nullable=False,
        default=0,
    )

    reddit_posts_returned = Column(
        Integer,
        nullable=False,
        default=0,
    )

    mastodon_posts_returned = Column(
        Integer,
        nullable=False,
        default=0,
    )

    unique_x_posts = Column(
        Integer,
        nullable=False,
        default=0,
    )

    unique_reddit_posts = Column(
        Integer,
        nullable=False,
        default=0,
    )

    unique_mastodon_posts = Column(
        Integer,
        nullable=False,
        default=0,
    )

    # ------------------------------------------------------
    # FILTER / ANALYSIS COUNTERS
    # ------------------------------------------------------

    noise_filtered = Column(
        Integer,
        nullable=False,
        default=0,
    )

    non_operational_filtered = Column(
        Integer,
        nullable=False,
        default=0,
    )

    historical_references_filtered = Column(
        Integer,
        nullable=False,
        default=0,
    )

    influence_signals_detected = Column(
        Integer,
        nullable=False,
        default=0,
    )

    crossing_facilitation_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    legal_migration_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    policy_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    recruitment_coordination_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    mobilization_coordination_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    mobilization_report_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    decision_influence_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    online_influence_report_signals = Column(
        Integer,
        nullable=False,
        default=0,
    )

    # ------------------------------------------------------
    # OPERATIONAL / CORRELATION COUNTERS
    # ------------------------------------------------------

    operational_events_analyzed = Column(
        Integer,
        nullable=False,
        default=0,
    )

    historical_events_available = Column(
        Integer,
        nullable=False,
        default=0,
    )

    new_correlation_groups = Column(
        Integer,
        nullable=False,
        default=0,
    )

    events_correlated_existing = Column(
        Integer,
        nullable=False,
        default=0,
    )

    database_correlations = Column(
        Integer,
        nullable=False,
        default=0,
    )

    current_run_correlations = Column(
        Integer,
        nullable=False,
        default=0,
    )

    new_events_saved = Column(
        Integer,
        nullable=False,
        default=0,
    )

    events_already_existing = Column(
        Integer,
        nullable=False,
        default=0,
    )

    new_event_groups = Column(
        Integer,
        nullable=False,
        default=0,
    )

    updated_event_groups = Column(
        Integer,
        nullable=False,
        default=0,
    )

    bootstrapped_event_groups = Column(
        Integer,
        nullable=False,
        default=0,
    )

    existing_event_groups_reused = Column(
        Integer,
        nullable=False,
        default=0,
    )

    event_group_sources_linked = Column(
        Integer,
        nullable=False,
        default=0,
    )

    # ------------------------------------------------------
    # TECHNICAL HEALTH
    # ------------------------------------------------------

    x_collector_errors = Column(
        Integer,
        nullable=False,
        default=0,
    )

    reddit_collector_errors = Column(
        Integer,
        nullable=False,
        default=0,
    )

    mastodon_collector_errors = Column(
        Integer,
        nullable=False,
        default=0,
    )

    error_message = Column(
        Text,
        nullable=True,
    )


# ==========================================================
# NEW: RAW COLLECTED POST HISTORY
# ==========================================================


class CollectedPost(Base):
    """
    Stores one UNIQUE social-media post collected by the monitor.

    This is deliberately separate from Post.

    Post:
        operational event storage used by the existing analytical
        / correlation pipeline.

    CollectedPost:
        raw collection history used for information-volume trends,
        source statistics and dashboard traceability.

    Recollecting the same source + source_post_id does not create
    another row. Instead the application will update last_seen
    fields and collection_count.

    This prevents repeated manual runs from inflating weekly post
    history.
    """

    __tablename__ = "collected_posts"

    id = Column(
        Integer,
        primary_key=True,
    )

    source = Column(
        String(50),
        nullable=False,
    )

    source_post_id = Column(
        String(255),
        nullable=False,
    )

    author = Column(
        String(255),
        nullable=True,
    )

    text = Column(
        Text,
        nullable=False,
    )

    language = Column(
        String(20),
        nullable=True,
    )

    published_at = Column(
        DateTime,
        nullable=True,
    )

    url = Column(
        Text,
        nullable=True,
    )

    # First / most recent monitor observation
    first_collected_at = Column(
        DateTime,
        nullable=False,
    )

    last_collected_at = Column(
        DateTime,
        nullable=False,
    )

    collection_count = Column(
        Integer,
        nullable=False,
        default=1,
    )

    first_run_id = Column(
        Integer,
        ForeignKey(
            "monitor_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    last_run_id = Column(
        Integer,
        ForeignKey(
            "monitor_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # Query provenance
    first_query_id = Column(
        String(255),
        nullable=True,
    )

    last_query_id = Column(
        String(255),
        nullable=True,
    )

    first_query_group = Column(
        String(255),
        nullable=True,
    )

    last_query_group = Column(
        String(255),
        nullable=True,
    )

    last_search_query = Column(
        Text,
        nullable=True,
    )

    # Filter states from the most recent observation
    is_noise = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_operational = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    operational_confidence = Column(
        Float,
        nullable=True,
    )

    influence_detected = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_post_id",
            name="uq_collected_post_source_id",
        ),
    )


# ==========================================================
# NEW: INFLUENCE / EARLY-WARNING SIGNAL HISTORY
# ==========================================================


class InfluenceSignal(Base):
    """
    Persistent migration influence / early-warning signal.

    This table is intentionally independent from operational
    event classification.

    Therefore a post may be:

        operational = False
        influence signal = True

    and still remain available to the dashboard.

    A source post can carry more than one signal over time, so
    uniqueness is based on:

        source + source_post_id + primary_signal

    Re-detection updates last_detected_at / last_run_id rather
    than creating duplicate history rows.
    """

    __tablename__ = "influence_signals"

    id = Column(
        Integer,
        primary_key=True,
    )

    collected_post_id = Column(
        Integer,
        ForeignKey(
            "collected_posts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    source = Column(
        String(50),
        nullable=False,
    )

    source_post_id = Column(
        String(255),
        nullable=False,
    )

    author = Column(
        String(255),
        nullable=True,
    )

    language = Column(
        String(20),
        nullable=True,
    )

    published_at = Column(
        DateTime,
        nullable=True,
    )

    text = Column(
        Text,
        nullable=False,
    )

    source_url = Column(
        Text,
        nullable=True,
    )

    # ------------------------------------------------------
    # SIGNAL CLASSIFICATION
    # ------------------------------------------------------

    primary_signal = Column(
        String(100),
        nullable=False,
    )

    signal_mode = Column(
        String(50),
        nullable=True,
    )

    signal_intent = Column(
        String(100),
        nullable=True,
    )

    priority = Column(
        String(50),
        nullable=True,
    )

    confidence = Column(
        Float,
        nullable=True,
    )

    score = Column(
        Float,
        nullable=True,
    )

    # JSON-serialized detector details
    matched_signals = Column(
        Text,
        nullable=True,
    )

    matched_phrases = Column(
        Text,
        nullable=True,
    )

    matched_groups = Column(
        Text,
        nullable=True,
    )

    context_matches = Column(
        Text,
        nullable=True,
    )

    high_value_matches = Column(
        Text,
        nullable=True,
    )

    signal_context_rejections = Column(
        Text,
        nullable=True,
    )

    rules_version = Column(
        String(50),
        nullable=True,
    )

    # ------------------------------------------------------
    # MIGRATION / HISTORICAL CONTEXT
    # ------------------------------------------------------

    migration_context = Column(
        Boolean,
        nullable=True,
    )

    human_migration_context = Column(
        Boolean,
        nullable=True,
    )

    historical_reference = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    historical_reason = Column(
        String(255),
        nullable=True,
    )

    historical_reference_text = Column(
        String(500),
        nullable=True,
    )

    # ------------------------------------------------------
    # LOCATION / REGION ENRICHMENT
    # ------------------------------------------------------

    primary_location = Column(
        String(255),
        nullable=True,
    )

    country = Column(
        String(100),
        nullable=True,
    )

    primary_region = Column(
        String(100),
        nullable=True,
    )

    latitude = Column(
        Float,
        nullable=True,
    )

    longitude = Column(
        Float,
        nullable=True,
    )

    # ------------------------------------------------------
    # SIGNAL HISTORY
    # ------------------------------------------------------

    first_detected_at = Column(
        DateTime,
        nullable=False,
    )

    last_detected_at = Column(
        DateTime,
        nullable=False,
    )

    detection_count = Column(
        Integer,
        nullable=False,
        default=1,
    )

    first_run_id = Column(
        Integer,
        ForeignKey(
            "monitor_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    last_run_id = Column(
        Integer,
        ForeignKey(
            "monitor_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_post_id",
            "primary_signal",
            name="uq_influence_source_post_signal",
        ),
    )
