"""
Migration OSINT Monitor

File:
event_repository.py

Description:
Database repository for storing normalized operational migration events.
"""

from datetime import datetime
from typing import Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database.models import Post


class EventRepository:
    """
    Stores normalized operational events in the existing posts table.

    In V1, one operational source post is stored as one event record.
    Later, correlated multi-source events can be introduced separately
    without breaking the current storage layer.
    """

    def save_event(
        self,
        session: Session,
        event: Dict[str, Any],
    ) -> bool:
        """
        Saves a normalized event.

        Returns:
            True if saved successfully.
            False if the same source + post ID already exists.
        """

        primary_location = event.get("primary_location") or {}

        post = Post(
            source=event.get("source") or "UNKNOWN",
            post_id=str(event.get("source_post_id") or ""),
            author=event.get("author"),
            text=event.get("text") or "",
            language=event.get("language"),
            published_at=self._parse_datetime(
                event.get("published_at")
            ),
            collected_at=datetime.utcnow(),
            url=event.get("source_url"),
            relevance_score=event.get("relevance_score"),
            signal_type=event.get("event_type"),
            locations=self._serialize_locations(
                event.get("locations", [])
            ),
            origin_location=None,
            destination_location=None,
            event_time_text=event.get("event_time_text"),
            event_time_normalized=event.get(
                "event_time_normalized"
            ),
            event_time_confidence=event.get(
                "event_time_confidence"
            ),
            latitude=primary_location.get("latitude"),
            longitude=primary_location.get("longitude"),
            extraction_confidence=event.get(
                "event_confidence"
            ),
        )

        try:
            session.add(post)
            session.commit()
            session.refresh(post)
            return True

        except IntegrityError:
            session.rollback()
            return False

    def _parse_datetime(
        self,
        value,
    ):
        """
        Converts ISO timestamp strings into datetime objects.
        """

        if not value:
            return None

        if isinstance(value, datetime):
            return value

        try:
            return datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError:
            return None

    def _serialize_locations(
        self,
        locations,
    ) -> str:
        """
        Stores detected location names as a comma-separated string.
        """

        if not locations:
            return ""

        names = []

        for location in locations:
            name = location.get("name")

            if name and name not in names:
                names.append(name)

        return ", ".join(names)
