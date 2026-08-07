"""
Migration OSINT Monitor

File:
time_extractor.py

Description:
Extracts simple time references from text and normalizes them relative
to the publication time of the source post.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class TimeExtractor:
    """
    Extracts common relative and explicit time references from text.
    """

    TIME_PATTERNS = [
        (r"\btonight\b", "tonight"),
        (r"\btomorrow\b", "tomorrow"),
        (r"\bthis morning\b", "this_morning"),
        (r"\bthis afternoon\b", "this_afternoon"),
        (r"\bthis evening\b", "this_evening"),
        (r"\bmidnight\b", "midnight"),
        (r"\besta noche\b", "tonight"),
        (r"\bmañana\b", "tomorrow"),
        (r"\bce soir\b", "tonight"),
        (r"\bdemain\b", "tomorrow"),
    ]

    def extract(
        self,
        text: str,
        published_at: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Extracts the first recognized time reference.

        Returns:
            Dictionary containing the original expression,
            normalized time value and confidence score.
        """
        if not text:
            return None

        reference_time = published_at or datetime.utcnow()
        text_lower = text.lower()

        for pattern, time_type in self.TIME_PATTERNS:
            match = re.search(pattern, text_lower, re.IGNORECASE)

            if match:
                normalized = self._normalize_relative_time(
                    time_type,
                    reference_time,
                )

                return {
                    "event_time_text": match.group(0),
                    "event_time_normalized": normalized.isoformat(),
                    "event_time_confidence": 0.80,
                }

        explicit_time = self._extract_explicit_clock_time(
            text_lower,
            reference_time,
        )

        if explicit_time:
            return explicit_time

        return None

    def _normalize_relative_time(
        self,
        time_type: str,
        reference_time: datetime,
    ) -> datetime:
        """
        Converts a relative time expression into an approximate datetime.
        """
        if time_type == "tomorrow":
            return (reference_time + timedelta(days=1)).replace(
                hour=12,
                minute=0,
                second=0,
                microsecond=0,
            )

        if time_type == "tonight":
            return reference_time.replace(
                hour=21,
                minute=0,
                second=0,
                microsecond=0,
            )

        if time_type == "this_morning":
            return reference_time.replace(
                hour=9,
                minute=0,
                second=0,
                microsecond=0,
            )

        if time_type == "this_afternoon":
            return reference_time.replace(
                hour=15,
                minute=0,
                second=0,
                microsecond=0,
            )

        if time_type == "this_evening":
            return reference_time.replace(
                hour=19,
                minute=0,
                second=0,
                microsecond=0,
            )

        if time_type == "midnight":
            return reference_time.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

        return reference_time

    def _extract_explicit_clock_time(
        self,
        text: str,
        reference_time: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Extracts simple clock times such as 23:30 or 3am.
        """
        match_24h = re.search(
            r"\b([01]?\d|2[0-3]):([0-5]\d)\b",
            text,
        )

        if match_24h:
            hour = int(match_24h.group(1))
            minute = int(match_24h.group(2))

            normalized = reference_time.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )

            return {
                "event_time_text": match_24h.group(0),
                "event_time_normalized": normalized.isoformat(),
                "event_time_confidence": 0.90,
            }

        match_12h = re.search(
            r"\b(1[0-2]|0?[1-9])\s?(am|pm)\b",
            text,
            re.IGNORECASE,
        )

        if match_12h:
            hour = int(match_12h.group(1))
            period = match_12h.group(2).lower()

            if period == "pm" and hour != 12:
                hour += 12

            if period == "am" and hour == 12:
                hour = 0

            normalized = reference_time.replace(
                hour=hour,
                minute=0,
                second=0,
                microsecond=0,
            )

            return {
                "event_time_text": match_12h.group(0),
                "event_time_normalized": normalized.isoformat(),
                "event_time_confidence": 0.90,
            }

        return None
