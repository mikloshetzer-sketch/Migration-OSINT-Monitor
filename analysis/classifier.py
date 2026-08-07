
"""
Migration OSINT Monitor

File:
classifier.py

Description:
Classifies migration-related posts into signal categories
using stricter phrase matching to reduce false positives.
"""

import re
from typing import Dict, List, Tuple


class SignalClassifier:
    """
    Performs rule-based classification of migration-related text.
    """

    SIGNAL_PATTERNS = {
        "ROUTE_INFORMATION": [
            r"\broute\b",
            r"\bborder crossing\b",
            r"\bcrossing point\b",
            r"\bway to\b",
            r"\bruta\b",
            r"\bcruzar\b",
            r"\bcamino\b",
            r"\broute vers\b",
            r"\bpassage\b",
        ],
        "TRAVEL_ADVICE": [
            r"\badvice\b",
            r"\brecommend\b",
            r"\bavoid\b",
            r"\bbest way\b",
            r"\bhow to\b",
            r"\bconsejo\b",
            r"\brecomiendo\b",
            r"\bevitar\b",
            r"\bmejor forma\b",
            r"\bconseil\b",
            r"\béviter\b",
        ],
        "BORDER_CONDITION": [
            r"\bborder\b",
            r"\bcheckpoint\b",
            r"\bcoast guard\b",
            r"\bpatrol\b",
            r"\bguardia civil\b",
            r"\bfrontera\b",
            r"\bcontrôle\b",
            r"\bborder police\b",
        ],
        "COORDINATION": [
            r"\bmeet at\b",
            r"\bmeeting point\b",
            r"\bcontact me\b",
            r"\bdm me\b",
            r"\bsend me a message\b",
            r"\bjoin the group\b",
            r"\bwhatsapp\b",
            r"\btelegram\b",
            r"\bpunto de encuentro\b",
            r"\bcontáctame\b",
            r"\benvíame un mensaje\b",
            r"\brendez-vous\b",
            r"\bcontactez-moi\b",
        ],
        "DEPARTURE_SIGNAL": [
            r"\bleave tonight\b",
            r"\bleaving tonight\b",
            r"\bleave tomorrow\b",
            r"\bleaving tomorrow\b",
            r"\bdepart tonight\b",
            r"\bdepart tomorrow\b",
            r"\bsalida esta noche\b",
            r"\bsalimos esta noche\b",
            r"\bsalimos mañana\b",
            r"\bdépart ce soir\b",
            r"\bdépart demain\b",
        ],
        "TRANSPORT_OFFER": [
            r"\bboat available\b",
            r"\bcar available\b",
            r"\btaxi available\b",
            r"\bdriver available\b",
            r"\btransport available\b",
            r"\bseats available\b",
            r"\bplaces available\b",
            r"\bbarco disponible\b",
            r"\btransporte disponible\b",
            r"\bchauffeur disponible\b",
            r"\bbateau disponible\b",
        ],
    }

    PRIORITY = [
        "COORDINATION",
        "TRANSPORT_OFFER",
        "DEPARTURE_SIGNAL",
        "ROUTE_INFORMATION",
        "TRAVEL_ADVICE",
        "BORDER_CONDITION",
    ]

    def classify(self, text: str) -> Dict[str, object]:
        """
        Classifies text and returns:
        - primary signal type
        - all matched signal types
        - exact matched phrases
        """

        if not text:
            return {
                "signal_type": "GENERAL_DISCUSSION",
                "matched_signals": [],
                "matched_phrases": [],
            }

        matched_signals: List[str] = []
        matched_phrases: List[Tuple[str, str]] = []

        for signal_type, patterns in self.SIGNAL_PATTERNS.items():
            for pattern in patterns:
                match = re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )

                if match:
                    if signal_type not in matched_signals:
                        matched_signals.append(signal_type)

                    matched_phrases.append(
                        (
                            signal_type,
                            match.group(0),
                        )
                    )

        if not matched_signals:
            return {
                "signal_type": "GENERAL_DISCUSSION",
                "matched_signals": [],
                "matched_phrases": [],
            }

        primary_signal = next(
            (
                signal
                for signal in self.PRIORITY
                if signal in matched_signals
            ),
            matched_signals[0],
        )

        return {
            "signal_type": primary_signal,
            "matched_signals": matched_signals,
            "matched_phrases": matched_phrases,
        }
