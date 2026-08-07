"""
Migration OSINT Monitor

File:
event_group_repository.py

Description:
Repository layer for managing correlated operational event groups.

This module provides the database-facing logic for:
- creating a new event group
- attaching source events to an existing group
- updating first_seen / last_seen timestamps
- tracking source count
- tracking source types
- maintaining a representative event record
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class EventGroupRepository:
    """
    Repository interface for operational event groups.
    """

    def build_new_group_payload(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Creates a normalized payload for a new event group.
        """

        published_at = self._get_datetime(
            event.get("published_at")
        )

        source = event.get("source")

        primary_region = event.get(
            "primary_region"
        )

        primary_location = (
            event.get("primary_location")
            or {}
        )

        return {
            "event_type": event.get(
                "event_type"
            ),
            "title": self._build_group_title(
                event
            ),
            "representative_text": event.get(
                "text",
                "",
            ),
            "primary_region": primary_region,
            "primary_location": primary_location.get(
                "name"
            ),
            "country": primary_location.get(
                "country"
            ),
            "latitude": primary_location.get(
                "latitude"
            ),
            "longitude": primary_location.get(
                "longitude"
            ),
            "first_seen": published_at,
            "last_seen": published_at,
            "source_count": 1,
            "source_types": (
                [source]
                if source
                else []
            ),
            "status": "ACTIVE",
            "confidence": event.get(
                "event_confidence"
            ),
        }

    def build_group_update_payload(
        self,
        existing_group: Dict[str, Any],
        new_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Builds an updated event-group payload after
        another correlated source is attached.
        """

        first_seen = self._get_datetime(
            existing_group.get(
                "first_seen"
            )
        )

        last_seen = self._get_datetime(
            existing_group.get(
                "last_seen"
            )
        )

        new_time = self._get_datetime(
            new_event.get(
                "published_at"
            )
        )

        first_seen = self._normalize_datetime(
            first_seen
        )

        last_seen = self._normalize_datetime(
            last_seen
        )

        new_time = self._normalize_datetime(
            new_time
        )

        if new_time:
            if (
                first_seen is None
                or new_time < first_seen
            ):
                first_seen = new_time

            if (
                last_seen is None
                or new_time > last_seen
            ):
                last_seen = new_time

        source_types = list(
            existing_group.get(
                "source_types"
            )
            or []
        )

        new_source = new_event.get(
            "source"
        )

        if (
            new_source
            and new_source not in source_types
        ):
            source_types.append(
                new_source
            )

        source_count = (
            int(
                existing_group.get(
                    "source_count"
                )
                or 0
            )
            + 1
        )

        confidence = self._merge_confidence(
            existing_group.get(
                "confidence"
            ),
            new_event.get(
                "event_confidence"
            ),
        )

        representative_text = (
            existing_group.get(
                "representative_text"
            )
            or ""
        )

        new_text = new_event.get(
            "text",
            ""
        )

        if len(new_text) > len(
            representative_text
        ):
            representative_text = (
                new_text
            )

        return {
            "first_seen": first_seen,
            "last_seen": last_seen,
            "source_count": source_count,
            "source_types": source_types,
            "confidence": confidence,
            "representative_text": representative_text,
            "status": "ACTIVE",
        }

    def build_source_link_payload(
        self,
        event_group_id: int,
        event: Dict[str, Any],
        correlation_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Creates a normalized payload for linking
        an individual source event to an event group.
        """

        return {
            "event_group_id": event_group_id,
            "source": event.get(
                "source"
            ),
            "source_post_id": event.get(
                "source_post_id"
            ),
            "author": event.get(
                "author"
            ),
            "published_at": self._get_datetime(
                event.get(
                    "published_at"
                )
            ),
            "event_type": event.get(
                "event_type"
            ),
            "text": event.get(
                "text",
                "",
            ),
            "source_url": event.get(
                "source_url"
            ),
            "correlation_score": correlation_score,
        }

    def _build_group_title(
        self,
        event: Dict[str, Any],
    ) -> str:
        """
        Builds a short technical title for the event group.
        """

        event_type = (
            event.get(
                "event_type"
            )
            or "UNKNOWN_EVENT"
        )

        primary_location = (
            event.get(
                "primary_location"
            )
            or {}
        )

        location_name = (
            primary_location.get(
                "name"
            )
        )

        primary_region = (
            event.get(
                "primary_region"
            )
        )

        if location_name:
            return (
                f"{event_type} - "
                f"{location_name}"
            )

        if (
            primary_region
            and primary_region != "GLOBAL"
        ):
            return (
                f"{event_type} - "
                f"{primary_region}"
            )

        return event_type

    def _merge_confidence(
        self,
        existing_confidence,
        new_confidence,
    ) -> Optional[float]:
        """
        Combines confidence values conservatively.
        """

        values: List[float] = []

        for value in [
            existing_confidence,
            new_confidence,
        ]:
            if value is None:
                continue

            try:
                values.append(
                    float(value)
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

        if not values:
            return None

        return round(
            max(values),
            3,
        )

    def _get_datetime(
        self,
        value,
    ) -> Optional[datetime]:
        """
        Converts datetime objects or ISO strings
        into datetime values.
        """

        if not value:
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value

        try:
            return datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )

        except ValueError:
            return None

    def _normalize_datetime(
        self,
        value: Optional[datetime],
    ) -> Optional[datetime]:
        """
        Normalizes all datetime values to naive UTC.

        This prevents comparisons between offset-aware
        and offset-naive datetime objects.
        """

        if value is None:
            return None

        if value.tzinfo is not None:
            return (
                value
                .astimezone(timezone.utc)
                .replace(
                    tzinfo=None
                )
            )

        return value
