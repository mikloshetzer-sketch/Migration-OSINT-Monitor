"""
Migration OSINT Monitor

File:
models.py

Description:
SQLAlchemy database models for collected posts and extracted events.
"""

from sqlalchemy import Column, Integer, String, Text, Float, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)

    source = Column(String(50), nullable=False)
    post_id = Column(String(255), nullable=False)

    author = Column(String(255), nullable=True)
    text = Column(Text, nullable=False)
    language = Column(String(20), nullable=True)

    published_at = Column(DateTime, nullable=True)
    collected_at = Column(DateTime, nullable=False)

    url = Column(Text, nullable=True)

    relevance_score = Column(Float, nullable=True)
    signal_type = Column(String(100), nullable=True)

    locations = Column(Text, nullable=True)
    origin_location = Column(String(255), nullable=True)
    destination_location = Column(String(255), nullable=True)

    event_time_text = Column(String(255), nullable=True)
    event_time_normalized = Column(String(255), nullable=True)
    event_time_confidence = Column(Float, nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    extraction_confidence = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source",
            "post_id",
            name="uq_source_post_id"
        ),
    )
