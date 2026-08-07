"""
Migration OSINT Monitor

File:
correlation_repository.py

Description:
Provides database access methods used by the
Event Correlation Engine.

The current V1 database stores operational events
in the Post model. This repository loads recent
stored operational posts and converts them into
the dictionary structure expected by EventCorrelator.
"""

from datetime import datetime, timedelta

from sqlalchemy import select

from database.models import Post


class CorrelationRepository:
    """
    Repository used by the Event Correlator
    to retrieve previously stored operational events.
    """

    def __init__(
        self,
        lookback_days: int = 7,
    ):
        self.lookback_days = lookback_days

    def get_recent_events(
        self,
        session,
    ):
        """
        Returns stored operational events from the
        configured lookback window.

        Uses collected_at because this field exists
        in the current Post storage model.
        """

        cutoff = (
            datetime.utcnow()
            - timedelta(days=self.lookback_days)
        )

        statement = (
            select(Post)
            .where(
                Post.collected_at >= cutoff
            )
            .where(
                Post.signal_type.is_not(None)
            )
            .order_by(
                Post.collected_at.desc()
            )
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
        Returns recent stored operational events
        as dictionaries compatible with EventCorrelator.
        """

        events = self.get_recent_events(
            session
        )

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
        Converts the current Post database model into
        an EventCorrelator-compatible dictionary.
        """

        locations = self._deserialize_locations(
            getattr(
                event,
                "locations",
                "",
            )
        )

        primary_location = None

        latitude = getattr(
            event,
            "latitude",
            None,
        )

        longitude = getattr(
            event,
            "longitude",
            None,
        )

        if (
            locations
            and (
                latitude is not None
                or longitude is not None
            )
        ):
            primary_location = {
                "name": locations[0].get(
                    "name"
                ),
                "country": None,
                "latitude": latitude,
                "longitude": longitude,
            }

        return {
            "source": getattr(
                event,
                "source",
                None,
            ),
            "source_post_id": getattr(
                event,
                "post_id",
                None,
            ),
            "author": getattr(
                event,
                "author",
                None,
            ),
            "event_type": getattr(
                event,
                "signal_type",
                None,
            ),
            "event_confidence": getattr(
                event,
                "extraction_confidence",
                None,
            ),
            "relevance_score": getattr(
                event,
                "relevance_score",
                None,
            ),
            "text": getattr(
                event,
                "text",
                "",
            ),
            "language": getattr(
                event,
                "language",
                None,
            ),
            "published_at": getattr(
                event,
                "published_at",
                None,
            ),
            "event_time_normalized": getattr(
                event,
                "event_time_normalized",
                None,
            ),
            "event_time_confidence": getattr(
                event,
                "event_time_confidence",
                None,
            ),
            "matched_signals": self._build_signals(
                event
            ),
            "locations": locations,
            "primary_location": primary_location,

            # These fields are not yet persisted
            # in the current V1 database schema.
            # They remain available for compatibility.
            "primary_region": None,
            "matched_regions": [],
            "matched_countries": [],
        }

    def _build_signals(
        self,
        event,
    ):
        """
        Reconstructs the available signal list from
        the currently stored primary signal type.
        """

        signal_type = getattr(
            event,
            "signal_type",
            None,
        )

        if not signal_type:
            return []

        return [signal_type]

    def _deserialize_locations(
        self,
        value,
    ):
        """
        Converts the current comma-separated locations
        database field back into location dictionaries.
        """

        if not value:
            return []

        names = [
            item.strip()
            for item in str(value).split(",")
            if item.strip()
        ]

        return [
            {
                "name": name,
                "country": None,
            }
            for name in names
        ]
