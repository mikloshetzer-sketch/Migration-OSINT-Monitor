"""
Migration OSINT Monitor

File:
correlation_repository.py

Description:
Provides database access methods used by the
Event Correlation Engine.

This repository allows the correlator to search
previously stored operational events instead of
only comparing events collected during the current run.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database.models import Event


class CorrelationRepository:
    """
    Repository used by the Event Correlator.

    It exposes methods for retrieving previously
    collected operational events.
    """

    def __init__(self, lookback_days: int = 7):
        self.lookback_days = lookback_days

    def get_recent_events(
        self,
        session,
    ):
        """
        Returns operational events collected during the
        configured lookback window.

        Events are ordered from newest to oldest.
        """

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=self.lookback_days)
        )

        statement = (
            select(Event)
            .where(Event.created_at >= cutoff)
            .order_by(Event.created_at.desc())
        )

        return list(
            session.execute(statement)
            .scalars()
            .all()
        )

    def get_recent_events_as_dicts(
        self,
        session,
    ):
        """
        Returns recent events converted into dictionaries
        compatible with the EventCorrelator.
        """

        events = self.get_recent_events(session)

        results = []

        for event in events:
            results.append(
                self._event_to_dict(event)
            )

        return results

    def _event_to_dict(
        self,
        event,
    ):
        """
        Converts a SQLAlchemy Event model into the
        dictionary structure used throughout the
        analytical pipeline.
        """

        return {
            "source_post_id": event.source_post_id,
            "event_type": event.event_type,
            "event_confidence": event.event_confidence,
            "text": event.text,
            "published_at": event.published_at,
            "event_time_normalized": event.event_time,
            "matched_signals": event.matched_signals or [],
            "primary_region": getattr(
                event,
                "primary_region",
                None,
            ),
            "matched_regions": getattr(
                event,
                "matched_regions",
                [],
            ),
            "matched_countries": getattr(
                event,
                "matched_countries",
                [],
            ),
            "locations": [],
            "primary_location": None,
        }
