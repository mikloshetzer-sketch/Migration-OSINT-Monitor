"""
Migration OSINT Monitor

File:
classifier.py

Description:
Advanced rule-based classifier for migration-related operational events.
Supports multiple simultaneous signal types and selects a primary signal
based on priority.
"""

import re
from typing import Dict, List, Tuple


class SignalClassifier:
    """
    Classifies migration-related text into one or more operational signals.
    """

    SIGNAL_PATTERNS = {
        "SMUGGLING_ACTIVITY": [
            r"\bmigrant smuggling\b",
            r"\bpeople smuggling\b",
            r"\bpeople smugglers\b",
            r"\bmigrant smugglers\b",
            r"\bsmuggling network\b",
            r"\bsmuggling gang\b",
            r"\bhuman smuggling\b",
            r"\bfacilitating illegal migration\b",
            r"\borganised migration network\b",
            r"\borganized migration network\b",
        ],
        "RESCUE_OPERATION": [
            r"\brescued migrants\b",
            r"\brescued refugees\b",
            r"\bmigrants rescued\b",
            r"\brefugees rescued\b",
            r"\brescue operation\b",
            r"\bcoast guard rescued\b",
            r"\bsaved from drowning\b",
            r"\brecovered alive\b",
        ],
        "INTERCEPTION": [
            r"\bmigrants intercepted\b",
            r"\brefugees intercepted\b",
            r"\bboat intercepted\b",
            r"\bvessel intercepted\b",
            r"\bintercepted at sea\b",
            r"\bintercepted by authorities\b",
            r"\bprevented from crossing\b",
            r"\bstopped at the border\b",
        ],
        "DETENTION": [
            r"\bmigrants arrested\b",
            r"\brefugees arrested\b",
            r"\bmigrants detained\b",
            r"\brefugees detained\b",
            r"\bsmugglers arrested\b",
            r"\bsuspected smugglers arrested\b",
            r"\bdetention centre\b",
            r"\bdetention center\b",
        ],
        "CASUALTY": [
            r"\bmigrant died\b",
            r"\bmigrants died\b",
            r"\brefugee died\b",
            r"\brefugees died\b",
            r"\bmigrant death\b",
            r"\bmigrant deaths\b",
            r"\bdrowned migrants\b",
            r"\bdrowned refugees\b",
            r"\bbody recovered\b",
            r"\bbodies recovered\b",
            r"\bmissing migrants\b",
            r"\bdead migrants\b",
        ],
        "ARRIVAL": [
            r"\bmigrants arrived\b",
            r"\brefugees arrived\b",
            r"\barrival of migrants\b",
            r"\barrival of refugees\b",
            r"\bmass arrival\b",
            r"\blanded in\b",
            r"\breached the border\b",
            r"\breached the fence\b",
            r"\breached the barrier\b",
            r"\bentered the country\b",
        ],
        "DEPARTURE_SIGNAL": [
            r"\bleave tonight\b",
            r"\bleaving tonight\b",
            r"\bleave tomorrow\b",
            r"\bleaving tomorrow\b",
            r"\bdepart tonight\b",
            r"\bdepart tomorrow\b",
            r"\bdeparture tonight\b",
            r"\bdeparture tomorrow\b",
            r"\bboat departed\b",
            r"\bvessel departed\b",
            r"\bset off from\b",
            r"\bleft the coast\b",
            r"\bsalida esta noche\b",
            r"\bsalimos esta noche\b",
            r"\bsalimos mañana\b",
            r"\bdépart ce soir\b",
            r"\bdépart demain\b",
        ],
        "BORDER_CROSSING": [
            r"\bmigrant crossing\b",
            r"\bmigrants crossing\b",
            r"\brefugee crossing\b",
            r"\brefugees crossing\b",
            r"\bcrossed the border\b",
            r"\bcrossing the border\b",
            r"\bcrossing point\b",
            r"\billegal crossing\b",
            r"\birregular crossing\b",
            r"\battempted crossing\b",
            r"\battempting to enter\b",
        ],
        "ROUTE_INFORMATION": [
            r"\bmigration route\b",
            r"\bmigrant route\b",
            r"\brefugee route\b",
            r"\broute to\b",
            r"\broute from\b",
            r"\bway to\b",
            r"\bcorridor\b",
            r"\bcrossing route\b",
            r"\broute vers\b",
            r"\bruta\b",
            r"\bcamino\b",
        ],
        "TRANSPORT_OFFER": [
            r"\bboat available\b",
            r"\bcar available\b",
            r"\btaxi available\b",
            r"\bdriver available\b",
            r"\btransport available\b",
            r"\bseats available\b",
            r"\bplaces available\b",
            r"\btransport migrants\b",
            r"\btransport refugees\b",
            r"\bbarco disponible\b",
            r"\btransporte disponible\b",
            r"\bchauffeur disponible\b",
            r"\bbateau disponible\b",
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
            r"\bmeeting location\b",
            r"\bpunto de encuentro\b",
            r"\bcontáctame\b",
            r"\benvíame un mensaje\b",
            r"\brendez-vous\b",
            r"\bcontactez-moi\b",
        ],
        "TRAVEL_ADVICE": [
            r"\badvice\b",
            r"\brecommend\b",
            r"\bavoid\b",
            r"\bbest way\b",
            r"\bhow to cross\b",
            r"\bhow to get\b",
            r"\bbest route\b",
            r"\bsafest route\b",
            r"\bconsejo\b",
            r"\brecomiendo\b",
            r"\bevitar\b",
            r"\bmejor forma\b",
            r"\bconseil\b",
            r"\béviter\b",
        ],
        "BORDER_CONDITION": [
            r"\bborder control\b",
            r"\bborder controls\b",
            r"\bborder checks\b",
            r"\bborder security\b",
            r"\bcheckpoint\b",
            r"\bcheckpoints\b",
            r"\bcoast guard\b",
            r"\bpatrol\b",
            r"\bpatrols\b",
            r"\bguardia civil\b",
            r"\bfrontera\b",
            r"\bborder police\b",
        ],
        "BORDER_MEASURE": [
            r"\bborder closed\b",
            r"\bclosed the border\b",
            r"\bborder closure\b",
            r"\bborder restrictions\b",
            r"\bnew border controls\b",
            r"\breinforced border\b",
            r"\bdeployed to the border\b",
            r"\bfence construction\b",
            r"\bnew fence\b",
            r"\bbarrier construction\b",
        ],
        "DEPORTATION": [
            r"\bdeported migrants\b",
            r"\bdeported refugees\b",
            r"\bdeportation of migrants\b",
            r"\bremoved from the country\b",
            r"\bforced return\b",
            r"\breturned to\b.*\bcountry\b",
            r"\brepatriated\b",
        ],
        "ASYLUM_POLICY": [
            r"\basylum policy\b",
            r"\basylum rules\b",
            r"\basylum law\b",
            r"\basylum application\b",
            r"\basylum applications\b",
            r"\basylum processing\b",
            r"\brefugee processing\b",
        ],
        "MIGRANT_CAMP": [
            r"\bmigrant camp\b",
            r"\brefugee camp\b",
            r"\breception centre\b",
            r"\breception center\b",
            r"\btemporary accommodation\b",
            r"\bmigrant shelter\b",
            r"\brefugee shelter\b",
        ],
        "NGO_ACTIVITY": [
            r"\bngo rescue\b",
            r"\brescue vessel\b",
            r"\bhumanitarian vessel\b",
            r"\bcharity vessel\b",
            r"\bngo ship\b",
            r"\bhumanitarian organization\b",
            r"\bhumanitarian organisation\b",
        ],
        "PROTEST": [
            r"\bmigrant protest\b",
            r"\brefugee protest\b",
            r"\bprotest against migration\b",
            r"\bprotest over migration\b",
            r"\bdemonstration against migration\b",
            r"\bdemonstration over migration\b",
        ],
    }

    PRIORITY = [
        "SMUGGLING_ACTIVITY",
        "CASUALTY",
        "RESCUE_OPERATION",
        "INTERCEPTION",
        "DETENTION",
        "BORDER_CROSSING",
        "DEPARTURE_SIGNAL",
        "ARRIVAL",
        "TRANSPORT_OFFER",
        "COORDINATION",
        "ROUTE_INFORMATION",
        "TRAVEL_ADVICE",
        "BORDER_MEASURE",
        "BORDER_CONDITION",
        "DEPORTATION",
        "ASYLUM_POLICY",
        "MIGRANT_CAMP",
        "NGO_ACTIVITY",
        "PROTEST",
    ]

    BASE_CONFIDENCE = {
        "SMUGGLING_ACTIVITY": 0.92,
        "CASUALTY": 0.92,
        "RESCUE_OPERATION": 0.90,
        "INTERCEPTION": 0.88,
        "DETENTION": 0.88,
        "BORDER_CROSSING": 0.86,
        "DEPARTURE_SIGNAL": 0.84,
        "ARRIVAL": 0.84,
        "TRANSPORT_OFFER": 0.82,
        "COORDINATION": 0.82,
        "ROUTE_INFORMATION": 0.78,
        "TRAVEL_ADVICE": 0.76,
        "BORDER_MEASURE": 0.80,
        "BORDER_CONDITION": 0.72,
        "DEPORTATION": 0.86,
        "ASYLUM_POLICY": 0.74,
        "MIGRANT_CAMP": 0.82,
        "NGO_ACTIVITY": 0.80,
        "PROTEST": 0.78,
        "GENERAL_DISCUSSION": 0.30,
    }

    def classify(self, text: str) -> Dict[str, object]:
        """
        Classifies text into one or more operational migration signals.

        Returns:
            {
                "signal_type": str,
                "primary_signal": str,
                "matched_signals": list[str],
                "matched_phrases": list[tuple[str, str]],
                "confidence": float
            }
        """

        if not text:
            return {
                "signal_type": "GENERAL_DISCUSSION",
                "primary_signal": "GENERAL_DISCUSSION",
                "matched_signals": [],
                "matched_phrases": [],
                "confidence": self.BASE_CONFIDENCE["GENERAL_DISCUSSION"],
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
                "primary_signal": "GENERAL_DISCUSSION",
                "matched_signals": [],
                "matched_phrases": [],
                "confidence": self.BASE_CONFIDENCE["GENERAL_DISCUSSION"],
            }

        primary_signal = self._select_primary_signal(
            matched_signals
        )

        confidence = self._calculate_confidence(
            primary_signal=primary_signal,
            matched_signals=matched_signals,
            matched_phrases=matched_phrases,
        )

        return {
            "signal_type": primary_signal,
            "primary_signal": primary_signal,
            "matched_signals": matched_signals,
            "matched_phrases": matched_phrases,
            "confidence": confidence,
        }

    def _select_primary_signal(
        self,
        matched_signals: List[str],
    ) -> str:
        """
        Selects the highest-priority matched signal.
        """

        for signal in self.PRIORITY:
            if signal in matched_signals:
                return signal

        return matched_signals[0]

    def _calculate_confidence(
        self,
        *,
        primary_signal: str,
        matched_signals: List[str],
        matched_phrases: List[Tuple[str, str]],
    ) -> float:
        """
        Calculates classifier confidence.

        Confidence increases slightly when multiple independent
        event signals or multiple matching phrases are present.
        """

        confidence = self.BASE_CONFIDENCE.get(
            primary_signal,
            0.50,
        )

        if len(matched_signals) >= 2:
            confidence += 0.03

        if len(matched_signals) >= 3:
            confidence += 0.02

        if len(matched_phrases) >= 3:
            confidence += 0.02

        return round(
            min(confidence, 0.99),
            2,
        )
