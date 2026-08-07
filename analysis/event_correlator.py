"""
Migration OSINT Monitor

File:
event_correlator.py

Description:
Correlates normalized migration events that likely refer
to the same real-world operational event.
"""

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional


class EventCorrelator:
    """
    Performs simple rule-based correlation between operational events.
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.58,
        max_time_difference_hours: int = 48,
    ):
        self.similarity_threshold = similarity_threshold
        self.max_time_difference_hours = max_time_difference_hours

    def find_match(
        self,
        new_event: Dict[str, Any],
        existing_events: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the best matching existing event.

        Returns:
            The best matching event if correlation confidence
            reaches the configured threshold, otherwise None.
        """

        best_match = None
        best_score = 0.0

        for existing_event in existing_events:
            score = self.calculate_similarity(
                new_event,
                existing_event,
            )

            if score > best_score:
                best_score = score
                best_match = existing_event

        if (
            best_match is not None
            and best_score >= self.similarity_threshold
        ):
            return {
                "event": best_match,
                "correlation_score": round(best_score, 2),
            }

        return None

    def calculate_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Calculates similarity between two operational events.

        Components:
        - event type
        - detected location
        - event/publication time proximity
        - text similarity
        """

        score = 0.0

        if self._same_event_type(
            event_a,
            event_b,
        ):
            score += 0.35

        if self._same_location(
            event_a,
            event_b,
        ):
            score += 0.25

        if self._time_is_close(
            event_a,
            event_b,
        ):
            score += 0.15

        text_similarity = self._text_similarity(
            event_a.get("text", ""),
            event_b.get("text", ""),
        )

        score += text_similarity * 0.25

        return round(
            min(score, 1.0),
            4,
        )

    def _same_event_type(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> bool:
        """
        Checks whether the two events share a primary or secondary signal.
        """

        type_a = event_a.get("event_type")
        type_b = event_b.get("event_type")

        if type_a and type_b and type_a == type_b:
            return True

        signals_a = set(
            event_a.get("matched_signals") or []
        )

        signals_b = set(
            event_b.get("matched_signals") or []
        )

        return bool(
            signals_a.intersection(signals_b)
        )

    def _same_location(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> bool:
        """
        Checks whether events share at least one detected location.
        """

        names_a = self._extract_location_names(event_a)
        names_b = self._extract_location_names(event_b)

        if not names_a or not names_b:
            return False

        return bool(
            names_a.intersection(names_b)
        )

    def _extract_location_names(
        self,
        event: Dict[str, Any],
    ) -> set:
        """
        Returns normalized detected location names.
        """

        names = set()

        locations = event.get("locations") or []

        for location in locations:
            name = location.get("name")

            if name:
                names.add(
                    str(name).strip().lower()
                )

        primary_location = event.get(
            "primary_location"
        )

        if primary_location:
            name = primary_location.get("name")

            if name:
                names.add(
                    str(name).strip().lower()
                )

        return names

    def _time_is_close(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> bool:
        """
        Checks whether event timestamps are within the configured window.
        """

        time_a = self._get_event_datetime(
            event_a
        )

        time_b = self._get_event_datetime(
            event_b
        )

        if time_a is None or time_b is None:
            return False

        difference = abs(
            (time_a - time_b).total_seconds()
        )

        max_difference = (
            self.max_time_difference_hours
            * 60
            * 60
        )

        return difference <= max_difference

    def _get_event_datetime(
        self,
        event: Dict[str, Any],
    ) -> Optional[datetime]:
        """
        Uses normalized event time when available,
        otherwise falls back to publication time.
        """

        candidates = [
            event.get("event_time_normalized"),
            event.get("published_at"),
        ]

        for value in candidates:
            parsed = self._parse_datetime(value)

            if parsed is not None:
                return parsed

        return None

    def _parse_datetime(
        self,
        value,
    ) -> Optional[datetime]:
        """
        Parses datetime objects or ISO timestamp strings.
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

    def _text_similarity(
        self,
        text_a: str,
        text_b: str,
    ) -> float:
        """
        Calculates normalized textual similarity.
        """

        normalized_a = self._normalize_text(
            text_a
        )

        normalized_b = self._normalize_text(
            text_b
        )

        if not normalized_a or not normalized_b:
            return 0.0

        return SequenceMatcher(
            None,
            normalized_a,
            normalized_b,
        ).ratio()

    def _normalize_text(
        self,
        text: str,
    ) -> str:
        """
        Normalizes text before similarity comparison.
        """

        return " ".join(
            str(text)
            .lower()
            .replace("\n", " ")
            .split()
        )
