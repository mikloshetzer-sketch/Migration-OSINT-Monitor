"""
Migration OSINT Monitor

File:
models.py

Description:
SQLAlchemy database models for collected posts,
extracted events and correlated event groups.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    DateTime,
    UniqueConstraint,
    ForeignKey,
)

from sqlalchemy.orm import declarative_base


Base = declarative_base()


class Post(Base):
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
