"""
Migration OSINT Monitor

File:
time_extractor.py

Description:
Extracts simple time references from text and normalizes them relative
to the publication time of the source post.
"""

import re

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from dateutil import parser as date_parser


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
        published_at: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Extracts the first recognized time reference.

        published_at may be:

        - datetime
        - ISO-8601 string
        - RFC3339 string
        - None

        Returns:
            Dictionary containing the original expression,
            normalized time value and confidence score.
        """

        if not text:
            return None

        reference_time = self._normalize_reference_time(
            published_at
        )

        text_lower = text.lower()

        for pattern, time_type in self.TIME_PATTERNS:

            match = re.search(
                pattern,
                text_lower,
                re.IGNORECASE,
            )

            if match:

                normalized = (
                    self._normalize_relative_time(
                        time_type,
                        reference_time,
                    )
                )

                return {
                    "event_time_text":
                        match.group(0),

                    "event_time_normalized":
                        normalized.isoformat(),

                    "event_time_confidence":
                        0.80,
                }

        explicit_time = (
            self._extract_explicit_clock_time(
                text_lower,
                reference_time,
            )
        )

        if explicit_time:
            return explicit_time

        return None

    # ======================================================
    # REFERENCE TIME NORMALIZATION
    # ======================================================

    def _normalize_reference_time(
        self,
        value: Optional[Any],
    ) -> datetime:
        """
        Converts the source publication time into a datetime.

        Handles collector values such as:

            2026-08-08T07:04:27.000Z

        as well as actual datetime objects.

        If parsing fails, UTC now is used as a safe fallback.
        """

        if value is None:

            return datetime.now(
                timezone.utc
            )

        if isinstance(
            value,
            datetime,
        ):

            reference_time = value

        elif isinstance(
            value,
            str,
        ):

            raw_value = value.strip()

            if not raw_value:

                return datetime.now(
                    timezone.utc
                )

            try:

                reference_time = (
                    date_parser.parse(
                        raw_value
                    )
                )

            except (
                ValueError,
                TypeError,
                OverflowError,
            ):

                return datetime.now(
                    timezone.utc
                )

        else:

            try:

                reference_time = (
                    date_parser.parse(
                        str(value)
                    )
                )

            except (
                ValueError,
                TypeError,
                OverflowError,
            ):

                return datetime.now(
                    timezone.utc
                )

        # --------------------------------------------------
        # NORMALIZE TIMEZONE
        # --------------------------------------------------

        if reference_time.tzinfo is None:

            reference_time = (
                reference_time.replace(
                    tzinfo=timezone.utc
                )
            )

        else:

            reference_time = (
                reference_time.astimezone(
                    timezone.utc
                )
            )

        return reference_time

    # ======================================================
    # RELATIVE TIME
    # ======================================================

    def _normalize_relative_time(
        self,
        time_type: str,
        reference_time: datetime,
    ) -> datetime:
        """
        Converts a relative time expression into an approximate
        datetime.
        """

        if time_type == "tomorrow":

            return (
                reference_time
                + timedelta(
                    days=1
                )
            ).replace(
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

    # ======================================================
    # EXPLICIT CLOCK TIMES
    # ======================================================

    def _extract_explicit_clock_time(
        self,
        text: str,
        reference_time: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Extracts simple clock times such as:

            23:30
            03:15
            3am
            11 pm
        """

        # --------------------------------------------------
        # 24-HOUR FORMAT
        # --------------------------------------------------

        match_24h = re.search(
            r"\b([01]?\d|2[0-3]):([0-5]\d)\b",
            text,
        )

        if match_24h:

            hour = int(
                match_24h.group(1)
            )

            minute = int(
                match_24h.group(2)
            )

            normalized = (
                reference_time.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                )
            )

            return {
                "event_time_text":
                    match_24h.group(0),

                "event_time_normalized":
                    normalized.isoformat(),

                "event_time_confidence":
                    0.90,
            }

        # --------------------------------------------------
        # 12-HOUR FORMAT
        # --------------------------------------------------

        match_12h = re.search(
            r"\b(1[0-2]|0?[1-9])\s?(am|pm)\b",
            text,
            re.IGNORECASE,
        )

        if match_12h:

            hour = int(
                match_12h.group(1)
            )

            period = (
                match_12h.group(2)
                .lower()
            )

            if (
                period == "pm"
                and hour != 12
            ):

                hour += 12

            if (
                period == "am"
                and hour == 12
            ):

                hour = 0

            normalized = (
                reference_time.replace(
                    hour=hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            )

            return {
                "event_time_text":
                    match_12h.group(0),

                "event_time_normalized":
                    normalized.isoformat(),

                "event_time_confidence":
                    0.90,
            }

        return None
