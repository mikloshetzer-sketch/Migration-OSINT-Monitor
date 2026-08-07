"""
Migration OSINT Monitor

File:
classifier.py

Description:
Classifies migration-related posts into signal categories.
"""

from typing import Dict, List


class SignalClassifier:
    """
    Performs simple rule-based classification of migration-related text.
    """

    SIGNAL_PATTERNS = {
        "ROUTE_INFORMATION": [
            "route",
            "crossing",
            "border crossing",
            "way to",
            "ruta",
            "cruzar",
            "camino",
            "route vers",
            "passage",
        ],
        "TRAVEL_ADVICE": [
            "advice",
            "recommend",
            "avoid",
            "best way",
            "how to",
            "consejo",
            "recomiendo",
            "evitar",
            "mejor forma",
            "comment",
            "conseil",
            "éviter",
        ],
        "BORDER_CONDITION": [
            "border",
            "police",
            "checkpoint",
            "coast guard",
            "patrol",
            "guardia civil",
            "policía",
            "frontera",
            "contrôle",
            "police",
        ],
        "COORDINATION": [
            "meet",
            "meeting",
            "contact",
            "group",
            "gather",
            "send message",
            "dm me",
            "whatsapp",
            "telegram",
            "reunión",
            "contacto",
            "grupo",
            "mensaje",
            "rendez-vous",
            "contactez",
        ],
        "DEPARTURE_SIGNAL": [
            "departure",
            "depart",
            "leave tonight",
            "leaving tonight",
            "leave tomorrow",
            "leaving tomorrow",
            "salida",
            "salimos",
            "salir",
            "partir",
            "départ",
        ],
        "TRANSPORT_OFFER": [
            "boat",
            "car",
            "taxi",
            "driver",
            "transport",
            "ride",
            "place available",
            "seats available",
            "barco",
            "coche",
            "conductor",
            "transporte",
            "bateau",
            "voiture",
            "chauffeur",
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
        Classifies text and returns the primary signal type plus all matches.
        """
        if not text:
            return {
                "signal_type": "GENERAL_DISCUSSION",
                "matched_signals": [],
            }

        text_lower = text.lower()
        matched_signals: List[str] = []

        for signal_type, patterns in self.SIGNAL_PATTERNS.items():
            if any(pattern.lower() in text_lower for pattern in patterns):
                matched_signals.append(signal_type)

        if not matched_signals:
            return {
                "signal_type": "GENERAL_DISCUSSION",
                "matched_signals": [],
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
        }
