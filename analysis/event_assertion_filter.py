"""
Migration OSINT Monitor

File:
event_assertion_filter.py

Description:
Precision gate between operational phrase detection and persistent event
creation. It rejects selected analytical, retrospective, hypothetical or
comparative contexts while preserving concrete current event reports.
"""

import re
from typing import Any, Dict, List


class EventAssertionFilter:

    CONTEXT_SENSITIVE_TYPES = {
        "INTERCEPTION",
        "COORDINATION",
        "ROUTE_INFORMATION",
        "TRAVEL_ADVICE",
        "BORDER_CONDITION",
        "MIGRANT_CAMP",
        "GENERAL_DISCUSSION",
    }

    CURRENT_CUE_PATTERNS = [
        r"\btoday\b",
        r"\btonight\b",
        r"\bnow\b",
        r"\bcurrently\b",
        r"\bongoing\b",
        r"\bbreaking\b",
        r"\blatest\b",
        r"\bovernight\b",
        r"\bthis\s+morning\b",
        r"\bthis\s+afternoon\b",
        r"\bthis\s+evening\b",
        r"\bthis\s+week\b",
        r"\bjust\s+(?:arrived|crossed|intercepted|detained|arrested|rescued)\b",
        r"\bminutes?\s+ago\b",
        r"\bhours?\s+ago\b",
        r"\baujourd['’]hui\b",
        r"\bmaintenant\b",
        r"\bhoy\b",
        r"\bahora\b",
        r"\boggi\b",
        r"\badesso\b",
        r"\búltima\s+hora\b",
    ]

    ANALYTICAL_CUE_PATTERNS = [
        r"\bdebunk(?:ing|ed)?\b",
        r"\bexplainer\b",
        r"\banalysis\b",
        r"\banalytical\b",
        r"\bbackground\b",
        r"\bcontext\b",
        r"\btimeline\b",
        r"\bstep[-\s]+by[-\s]+step\s+breakdown\b",
        r"\bwhat\s+really\s+happened\b",
        r"\bthis\s+thread\b",
        r"\bin\s+this\s+thread\b",
        r"\bthe\s+author\s+of\s+this\s+article\b",
        r"\bhistorical\s+overview\b",
        r"\bcase\s+study\b",
        r"\blong[-\s]+term\b",
        r"\bpreviously\b",
        r"\ba\s+few\s+years\s+ago\b",
        r"\byears?\s+ago\b",
    ]

    NON_ASSERTIVE_PATTERNS = [
        r"\bused\s+to\s+assume\b",
        r"\bi\s+(?:used\s+to\s+)?(?:think|assume|imagine)\b",
        r"\bimagine(?:d|s|ing)?\b",
        r"\bhypothetical(?:ly)?\b",
        r"\bsuppose(?:d|s|ing)?\b",
        r"\bas\s+if\b",
        r"\bmetaphor(?:ical|ically)?\b",
        r"\bcompared?\s+to\b",
        r"\b(?:like|as)\s+(?:a\s+)?(?:migrant|refugee)\s+camp\b",
        r"\bwhat\s+if\b",

        # Wish / modal / proposal context.
        # These describe a preference, recommendation or hypothetical
        # future action, not an asserted real-world event.
        r"\bi\s+hope\b",
        r"\bhopefully\b",
        r"\bi\s+wish\b",
        r"\bif\s+they\s+(?:put|build|open|create|establish)\b",
        r"\bthey\s+should\s+(?:put|build|open|create|establish)\b",
        r"\bthey\s+could\s+(?:put|build|open|create|establish)\b",
        r"\bthey\s+would\s+(?:put|build|open|create|establish)\b",
        r"\bthey\s+ought\s+to\s+(?:put|build|open|create|establish)\b",
        r"\bshould\s+(?:put|build|open|create|establish)\b",
        r"\bcould\s+(?:put|build|open|create|establish)\b",
        r"\bwould\s+(?:put|build|open|create|establish)\b",
        r"\bought\s+to\s+(?:put|build|open|create|establish)\b",
    ]

    DIRECT_EVENT_PATTERNS = [
        r"\b(?:migrants?|refugees?)\s+(?:arrived|crossed|landed|departed)\b",
        r"\b(?:migrants?|refugees?)\s+(?:were\s+)?(?:intercepted|detained|arrested|rescued)\b",
        r"\b(?:migrant|refugee)\s+(?:died|drowned)\b",
        r"\b(?:smuggler|smugglers)\s+(?:was|were)?\s*arrested\b",
        r"\b(?:police|authorities|coast\s+guard)\s+(?:arrested|detained|intercepted|rescued)\b",
    ]

    LONG_TEXT_THRESHOLD = 1800
    VERY_LONG_TEXT_THRESHOLD = 4500

    def analyze(
        self,
        *,
        post: Dict[str, Any],
        event: Dict[str, Any],
        operational_result: Dict[str, Any],
    ) -> Dict[str, Any]:

        text = str(
            post.get("text")
            or event.get("text")
            or ""
        )

        event_type = str(
            event.get("event_type")
            or "GENERAL_DISCUSSION"
        ).upper()

        matched_signals = {
            str(value).upper()
            for value in (event.get("matched_signals") or [])
            if value
        }

        operational_categories = {
            str(value).upper()
            for value in (
                operational_result.get("operational_categories")
                or []
            )
            if value
        }

        current_cues = self._find_matches(
            text,
            self.CURRENT_CUE_PATTERNS,
        )
        analytical_cues = self._find_matches(
            text,
            self.ANALYTICAL_CUE_PATTERNS,
        )
        non_assertive_cues = self._find_matches(
            text,
            self.NON_ASSERTIVE_PATTERNS,
        )
        direct_event_cues = self._find_matches(
            text,
            self.DIRECT_EVENT_PATTERNS,
        )

        if (
            non_assertive_cues
            and event_type in {
                "MIGRANT_CAMP",
                "GENERAL_DISCUSSION",
                "BORDER_CONDITION",
                "COORDINATION",
                "ROUTE_INFORMATION",
                "TRAVEL_ADVICE",
            }
            and not current_cues
            and not direct_event_cues
        ):
            return self._reject(
                "NON_ASSERTIVE_OR_COMPARATIVE_CONTEXT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        context_sensitive = (
            event_type in self.CONTEXT_SENSITIVE_TYPES
            or bool(
                matched_signals
                & self.CONTEXT_SENSITIVE_TYPES
            )
            or "COORDINATION_ADVICE"
            in operational_categories
        )

        if (
            len(text) >= self.LONG_TEXT_THRESHOLD
            and len(analytical_cues) >= 2
            and context_sensitive
            and not current_cues
        ):
            return self._reject(
                "ANALYTICAL_OR_RETROSPECTIVE_CONTEXT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        if (
            len(text) >= self.VERY_LONG_TEXT_THRESHOLD
            and analytical_cues
            and event_type in self.CONTEXT_SENSITIVE_TYPES
            and not current_cues
        ):
            return self._reject(
                "VERY_LONG_CONTEXT_DOCUMENT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        if (
            event_type == "GENERAL_DISCUSSION"
            and analytical_cues
            and not direct_event_cues
            and not current_cues
        ):
            return self._reject(
                "GENERAL_DISCUSSION_WITHOUT_DIRECT_ASSERTION",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        return {
            "accepted": True,
            "reason": None,
            "analytical_cues": analytical_cues,
            "current_cues": current_cues,
            "non_assertive_cues": non_assertive_cues,
            "direct_event_cues": direct_event_cues,
        }

    def _find_matches(
        self,
        text: str,
        patterns: List[str],
    ) -> List[str]:

        results: List[str] = []

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                value = match.group(0)

                if value not in results:
                    results.append(value)

        return results

    def _reject(
        self,
        reason,
        analytical_cues,
        current_cues,
        non_assertive_cues,
        direct_event_cues,
    ):
        return {
            "accepted": False,
            "reason": reason,
            "analytical_cues": analytical_cues,
            "current_cues": current_cues,
            "non_assertive_cues": non_assertive_cues,
            "direct_event_cues": direct_event_cues,
        }
