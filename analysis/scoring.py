"""
Migration OSINT Monitor

File:
scoring.py

Description:
Calculates a relevance score for migration-related social media posts.
"""

from typing import Dict, Any


class RelevanceScorer:
    """
    Calculates a simple rule-based relevance score from extracted signals.
    """

    MAX_SCORE = 100

    def calculate_score(
        self,
        *,
        has_migration_keyword: bool = False,
        location_count: int = 0,
        has_time_reference: bool = False,
        has_movement_signal: bool = False,
        has_advice_signal: bool = False,
        has_coordination_signal: bool = False,
        has_transport_signal: bool = False,
    ) -> Dict[str, Any]:
        """
        Calculates a 0-100 relevance score and assigns a severity label.
        """

        score = 0

        if has_migration_keyword:
            score += 10

        if location_count > 0:
            score += min(location_count * 10, 20)

        if has_time_reference:
            score += 10

        if has_movement_signal:
            score += 20

        if has_advice_signal:
            score += 15

        if has_coordination_signal:
            score += 15

        if has_transport_signal:
            score += 10

        score = min(score, self.MAX_SCORE)

        return {
            "score": score,
            "level": self._get_level(score),
        }

    def _get_level(self, score: int) -> str:
        """
        Converts a numerical score into a relevance level.
        """

        if score >= 75:
            return "CRITICAL"

        if score >= 50:
            return "HIGH"

        if score >= 25:
            return "MEDIUM"

        return "LOW"
