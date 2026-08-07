"""
Migration OSINT Monitor

File:
event_extractor.py

Description:
Builds normalized migration-related event records from analyzed social media posts.
"""

from typing import Dict, Any, List, Optional


class EventExtractor:
    """
    Converts analyzed post data into a normalized event structure.
    """

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

        primary_location = self._get_primary_location(locations)

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

        return round(min(confidence, 1.0), 2)
