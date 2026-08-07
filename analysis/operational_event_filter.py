"""
Migration OSINT Monitor

File:
operational_event_filter.py

Description:
Determines whether a migration-related social media post describes
a concrete operational event or is primarily commentary, opinion,
political discussion, or other non-operational content.
"""

import re
from typing import Dict, List


class OperationalEventFilter:
    """
    Identifies whether a post contains a concrete migration-related event.
    """

    OPERATIONAL_PATTERNS = {
        "MOVEMENT": [
            r"\bmigrants? crossed\b",
            r"\brefugees? crossed\b",
            r"\bcrossing the border\b",
            r"\battempted crossing\b",
            r"\battempting to enter\b",
            r"\bmigrants? arrived\b",
            r"\brefugees? arrived\b",
            r"\bmass arrival\b",
            r"\bboat departed\b",
            r"\bvessel departed\b",
            r"\bset off from\b",
            r"\bleft the coast\b",
        ],
        "RESCUE": [
            r"\bmigrants? rescued\b",
            r"\brefugees? rescued\b",
            r"\brescue operation\b",
            r"\bcoast guard rescued\b",
            r"\bsaved from drowning\b",
        ],
        "INTERCEPTION": [
            r"\bmigrants? intercepted\b",
            r"\brefugees? intercepted\b",
            r"\bboat intercepted\b",
            r"\bvessel intercepted\b",
            r"\bprevented from crossing\b",
            r"\bstopped at the border\b",
        ],
        "ARREST_DETENTION": [
            r"\bmigrants? arrested\b",
            r"\brefugees? arrested\b",
            r"\bmigrants? detained\b",
            r"\brefugees? detained\b",
            r"\bsmugglers? arrested\b",
            r"\bsuspected smugglers? arrested\b",
            r"\bpolice arrested\b",
        ],
        "SMUGGLING": [
            r"\bmigrant smuggling\b",
            r"\bpeople smuggling\b",
            r"\bpeople smugglers\b",
            r"\bmigrant smugglers\b",
            r"\bsmuggling network\b",
            r"\bsmuggling gang\b",
            r"\bhuman smuggling\b",
        ],
        "CASUALTY": [
            r"\bmigrant died\b",
            r"\bmigrants died\b",
            r"\brefugee died\b",
            r"\brefugees died\b",
            r"\bdrowned migrants\b",
            r"\bdrowned refugees\b",
            r"\bbody recovered\b",
            r"\bbodies recovered\b",
            r"\bmissing migrants\b",
        ],
        "BORDER_ACTION": [
            r"\bborder closed\b",
            r"\bclosed the border\b",
            r"\bborder closure\b",
            r"\bnew border controls\b",
            r"\bborder restrictions\b",
            r"\breinforced border\b",
            r"\bdeployed to the border\b",
            r"\bfence construction\b",
            r"\bnew fence\b",
        ],
        "HUMANITARIAN": [
            r"\bmigrant camp\b",
            r"\brefugee camp\b",
            r"\breception centre\b",
            r"\breception center\b",
            r"\bmigrant shelter\b",
            r"\brefugee shelter\b",
            r"\bsleeping rough\b",
            r"\btemporary accommodation\b",
        ],
        "COORDINATION_ADVICE": [
            r"\bmeeting point\b",
            r"\bcontact me\b",
            r"\bdm me\b",
            r"\bjoin the group\b",
            r"\bwhatsapp\b",
            r"\btelegram\b",
            r"\bhow to cross\b",
            r"\bbest route\b",
            r"\bsafest route\b",
            r"\bleave tonight\b",
            r"\bleaving tonight\b",
            r"\bleave tomorrow\b",
            r"\bleaving tomorrow\b",
        ],
    }

    NON_OPERATIONAL_PATTERNS = {
        "POLITICAL_OPINION": [
            r"\bi think\b",
            r"\bi believe\b",
            r"\bgovernment should\b",
            r"\bpoliticians\b",
            r"\belection\b",
            r"\bcampaign\b",
            r"\btraitor\b",
            r"\binvaders\b",
            r"\breplacement migration\b",
        ],
        "GENERAL_DEBATE": [
            r"\bmigration debate\b",
            r"\bimmigration debate\b",
            r"\bmigration policy debate\b",
            r"\bpublic opinion\b",
            r"\bwhat do you think\b",
            r"\bdiscussion about migration\b",
        ],
        "PERSONAL_COMMENTARY": [
            r"\bi hate migrants\b",
            r"\bi support migrants\b",
            r"\bi oppose migration\b",
            r"\bmy opinion\b",
            r"\bthis is wrong\b",
            r"\bthis is disgusting\b",
        ],
    }

    def analyze(self, text: str) -> Dict[str, object]:
        """
        Determines whether a post contains a concrete operational event.

        Returns:
            {
                "is_operational": bool,
                "operational_categories": list[str],
                "matched_operational_phrases": list[str],
                "non_operational_categories": list[str],
                "matched_non_operational_phrases": list[str],
                "confidence": float
            }
        """

        if not text:
            return {
                "is_operational": False,
                "operational_categories": [],
                "matched_operational_phrases": [],
                "non_operational_categories": ["EMPTY_TEXT"],
                "matched_non_operational_phrases": [],
                "confidence": 0.0,
            }

        operational_categories: List[str] = []
        operational_phrases: List[str] = []

        non_operational_categories: List[str] = []
        non_operational_phrases: List[str] = []

        for category, patterns in self.OPERATIONAL_PATTERNS.items():
            for pattern in patterns:
                match = re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )

                if match:
                    if category not in operational_categories:
                        operational_categories.append(category)

                    operational_phrases.append(match.group(0))

        for category, patterns in self.NON_OPERATIONAL_PATTERNS.items():
            for pattern in patterns:
                match = re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )

                if match:
                    if category not in non_operational_categories:
                        non_operational_categories.append(category)

                    non_operational_phrases.append(match.group(0))

        is_operational = bool(operational_categories)

        confidence = self._calculate_confidence(
            operational_categories=operational_categories,
            operational_phrases=operational_phrases,
            non_operational_categories=non_operational_categories,
        )

        return {
            "is_operational": is_operational,
            "operational_categories": operational_categories,
            "matched_operational_phrases": operational_phrases,
            "non_operational_categories": non_operational_categories,
            "matched_non_operational_phrases": non_operational_phrases,
            "confidence": confidence,
        }

    def _calculate_confidence(
        self,
        *,
        operational_categories: List[str],
        operational_phrases: List[str],
        non_operational_categories: List[str],
    ) -> float:
        """
        Calculates confidence that the post represents an operational event.
        """

        if not operational_categories:
            return 0.10

        confidence = 0.60

        if len(operational_categories) >= 2:
            confidence += 0.10

        if len(operational_phrases) >= 2:
            confidence += 0.10

        if len(operational_phrases) >= 3:
            confidence += 0.05

        if non_operational_categories:
            confidence -= 0.10

        return round(
            max(
                0.0,
                min(confidence, 0.95),
            ),
            2,
        )

    def is_operational(self, text: str) -> bool:
        """
        Convenience method returning only the operational decision.
        """

        return bool(
            self.analyze(text).get("is_operational")
        )
