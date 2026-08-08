"""
Migration OSINT Monitor

File:
event_extractor.py

Description:
Builds normalized migration-related event records from analyzed social media posts.

This version also marks historical references so old events mentioned in
current posts are not treated as new operational events.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from dateutil import parser as date_parser


class EventExtractor:
    """
    Converts analyzed post data into a normalized event structure.
    """

    HISTORICAL_MAX_AGE_DAYS = 90

    def extract_event(
        self,
        *,
        post: Dict[str, Any],
        classification: Dict[str, Any],
        locations: List[Dict[str, Any]],
        time_result: Optional[Dict[str, Any]],
        score_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Creates a normalized event object from one analyzed post.
        """

        signal_type = classification.get(
            "signal_type",
            "GENERAL_DISCUSSION",
        )

        matched_signals = classification.get(
            "matched_signals",
            [],
        )

        matched_phrases = classification.get(
            "matched_phrases",
            [],
        )

        primary_location = self._get_primary_location(
            locations
        )

        historical_result = self._detect_historical_reference(
            post=post,
            time_result=time_result,
            max_age_days=self.HISTORICAL_MAX_AGE_DAYS,
        )

        return {
            "source": post.get("source"),
            "source_post_id": post.get("post_id"),
            "source_url": post.get("url"),
            "author": post.get("author"),
            "published_at": post.get("published_at"),
            "language": post.get("language"),
            "text": post.get("text", ""),
            "event_type": signal_type,
            "matched_signals": matched_signals,
            "matched_phrases": matched_phrases,
            "locations": locations,
            "primary_location": primary_location,
            "event_time_text": (
                time_result.get("event_time_text")
                if time_result
                else None
            ),
            "event_time_normalized": (
                time_result.get("event_time_normalized")
                if time_result
                else None
            ),
            "event_time_confidence": (
                time_result.get("event_time_confidence")
                if time_result
                else None
            ),
            "historical_reference": historical_result.get(
                "is_historical",
                False,
            ),
            "historical_reason": historical_result.get(
                "reason"
            ),
            "historical_reference_time": historical_result.get(
                "reference_time"
            ),
            "relevance_score": score_result.get("score"),
            "relevance_level": score_result.get("level"),
            "event_confidence": self._calculate_event_confidence(
                signal_type=signal_type,
                locations=locations,
                time_result=time_result,
                relevance_score=score_result.get("score", 0),
            ),
        }

    def _get_primary_location(
        self,
        locations: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Returns the first detected location as the primary location.
        """

        if not locations:
            return None

        return locations[0]

    def _parse_datetime_safe(
        self,
        value: Any,
    ) -> Optional[datetime]:
        """
        Parses datetime-like values and normalizes them to UTC.
        """

        if value is None:
            return None

        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = date_parser.parse(
                    str(value)
                )
            except (
                ValueError,
                TypeError,
                OverflowError,
            ):
                return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )
        else:
            parsed = parsed.astimezone(
                timezone.utc
            )

        return parsed

    def _detect_historical_reference(
        self,
        *,
        post: Dict[str, Any],
        time_result: Optional[Dict[str, Any]],
        max_age_days: int,
    ) -> Dict[str, Any]:
        """
        Detects old historical events mentioned in a current post.

        A post is marked historical when:

        - the extracted event time is older than max_age_days, or
        - the text explicitly mentions a previous calendar year, or
        - the text says that something happened N years ago.

        Strong current-time cues prevent the whole post from being marked
        historical when old background and a current event appear together.
        """

        text = str(
            post.get(
                "text",
                "",
            )
            or ""
        )

        published_at = (
            self._parse_datetime_safe(
                post.get("published_at")
            )
            or datetime.now(timezone.utc)
        )

        current_cue_pattern = re.compile(
            r"\b("
            r"today|tonight|now|currently|"
            r"this\s+morning|this\s+afternoon|this\s+evening|"
            r"this\s+week|this\s+month|"
            r"just\s+now|just\s+arrived|"
            r"breaking|latest|ongoing|"
            r"aujourd'hui|maintenant|"
            r"hoy|ahora|"
            r"oggi|adesso"
            r")\b",
            flags=re.IGNORECASE,
        )

        has_current_cue = bool(
            current_cue_pattern.search(text)
        )

        event_time_normalized = None

        if time_result:
            event_time_normalized = (
                self._parse_datetime_safe(
                    time_result.get(
                        "event_time_normalized"
                    )
                )
            )

        if (
            event_time_normalized is not None
            and not has_current_cue
        ):
            age = (
                published_at
                - event_time_normalized
            )

            if age > timedelta(
                days=max_age_days
            ):
                return {
                    "is_historical": True,
                    "reason": "EXTRACTED_EVENT_TIME_TOO_OLD",
                    "reference_time": (
                        event_time_normalized.isoformat()
                    ),
                }

        explicit_years = [
            int(match)
            for match in re.findall(
                r"(?<!\d)(19\d{2}|20\d{2})(?!\d)",
                text,
            )
        ]

        previous_years = [
            year
            for year in explicit_years
            if year < published_at.year
        ]

        if (
            previous_years
            and not has_current_cue
        ):
            return {
                "is_historical": True,
                "reason": "EXPLICIT_PREVIOUS_YEAR",
                "reference_time": str(
                    max(previous_years)
                ),
            }

        years_ago_match = re.search(
            r"\b("
            r"\d+|one|two|three|four|five|six|seven|eight|nine|ten"
            r")\s+years?\s+ago\b",
            text,
            flags=re.IGNORECASE,
        )

        if (
            years_ago_match
            and not has_current_cue
        ):
            return {
                "is_historical": True,
                "reason": "YEARS_AGO_REFERENCE",
                "reference_time": (
                    years_ago_match.group(0)
                ),
            }

        return {
            "is_historical": False,
            "reason": None,
            "reference_time": None,
        }

    def _calculate_event_confidence(
        self,
        *,
        signal_type: str,
        locations: List[Dict[str, Any]],
        time_result: Optional[Dict[str, Any]],
        relevance_score: int,
    ) -> float:
        """
        Calculates a simple event confidence score between 0 and 1.
        """

        confidence = 0.20

        if signal_type != "GENERAL_DISCUSSION":
            confidence += 0.25

        if locations:
            confidence += 0.20

        if time_result:
            confidence += 0.15

        if relevance_score >= 50:
            confidence += 0.15
        elif relevance_score >= 25:
            confidence += 0.10
        elif relevance_score > 0:
            confidence += 0.05

        return round(
            min(confidence, 1.0),
            2,
        )

