"""
Migration OSINT Monitor

File:
influence_signal_detector.py

Description:
Rule-based detector for migration-related influence and enabling signals.

The detector is intentionally separated from the operational event
classifier.

It identifies information that may influence, facilitate, organize,
encourage, or legally affect migration behaviour.

Main categories:

- CROSSING_FACILITATION
- LEGAL_MIGRATION_SIGNAL
- POLICY_SIGNAL
- RECRUITMENT_COORDINATION

The detector does not determine whether a claim is true.
It only identifies potentially relevant information signals.
"""

import re

from typing import Dict, List, Tuple


class InfluenceSignalDetector:
    """
    Detects migration-related influence and enabling signals.

    These signals are different from direct operational events.

    Example:

        "Come to this beach tonight, there are no police."

    is not necessarily a BORDER_CROSSING event yet.

    It is an enabling / facilitation signal that may precede
    operational movement.
    """

    # ==========================================================
    # MIGRATION CONTEXT
    # ==========================================================

    MIGRATION_CONTEXT_PATTERNS = [

        r"\bmigrant\b",
        r"\bmigrants\b",
        r"\bmigration\b",

        r"\brefugee\b",
        r"\brefugees\b",

        r"\basylum\b",
        r"\basylum seeker\b",
        r"\basylum seekers\b",

        r"\billegal migrant\b",
        r"\billegal migrants\b",

        r"\birregular migrant\b",
        r"\birregular migrants\b",

        r"\bundocumented migrant\b",
        r"\bundocumented migrants\b",

        r"\bborder crossing\b",
        r"\bborder crossings\b",

        r"\bsmall boat\b",
        r"\bsmall boats\b",

        r"\bdinghy\b",
        r"\bdinghies\b",

        r"\bdeportation\b",
        r"\bdeported\b",

        r"\breturn decision\b",
        r"\bforced return\b",

        r"\bnon-refoulement\b",

        r"\bimmigration\b",

        # Spanish

        r"\bmigrante\b",
        r"\bmigrantes\b",

        r"\brefugiado\b",
        r"\brefugiados\b",

        r"\basilo\b",

        r"\binmigración\b",

        r"\bdeportación\b",

        # French

        r"\bmigrant\b",
        r"\bmigrants\b",

        r"\bréfugié\b",
        r"\bréfugiés\b",

        r"\bdemandeur d['’]asile\b",
        r"\bdemandeurs d['’]asile\b",

        r"\bimmigration\b",

        r"\bexpulsion\b",
    ]


    # ==========================================================
    # SIGNAL PATTERNS
    # ==========================================================

    SIGNAL_PATTERNS = {

        # ------------------------------------------------------
        # CROSSING FACILITATION
        # ------------------------------------------------------

        "CROSSING_FACILITATION": [

            # English

            r"\bcome here\b",
            r"\bcome to\b",

            r"\bgo to this\b",
            r"\bgo to the\b",

            r"\bcross here\b",

            r"\byou can cross\b",
            r"\bcan cross here\b",

            r"\beasy crossing\b",
            r"\beasier crossing\b",

            r"\bsafe crossing\b",

            r"\bsafe route\b",

            r"\buse this route\b",
            r"\btake this route\b",

            r"\buse this crossing\b",
            r"\btake this crossing\b",

            r"\bborder is open\b",
            r"\bborder open\b",

            r"\bcheckpoint is open\b",

            r"\bno police\b",
            r"\bno border police\b",

            r"\bno patrol\b",
            r"\bno patrols\b",

            r"\bno guards\b",
            r"\bno border guards\b",

            r"\bno checks\b",
            r"\bwithout checks\b",

            r"\bunguarded border\b",

            r"\bavoid the police\b",
            r"\bavoid police\b",

            r"\bavoid the patrol\b",
            r"\bavoid patrols\b",

            r"\bpolice are not there\b",

            r"\bguards are not there\b",

            r"\bcross tonight\b",
            r"\bcross tomorrow\b",

            r"\bmove tonight\b",

            r"\bleave tonight\b",

            r"\bdeparture tonight\b",

            r"\bboat leaves tonight\b",
            r"\bboat leaving tonight\b",

            r"\bboat leaves from\b",
            r"\bboat departs from\b",

            r"\blaunch point\b",

            r"\bcrossing location\b",

            r"\bcrossing point\b",

            r"\bmeeting point\b",

            # Spanish

            r"\bven aquí\b",
            r"\bvengan aquí\b",

            r"\bven a\b",
            r"\bvengan a\b",

            r"\bcruza aquí\b",
            r"\bcruzar aquí\b",

            r"\bse puede cruzar\b",

            r"\bpuedes cruzar\b",

            r"\bfrontera abierta\b",

            r"\bno hay policía\b",

            r"\bno hay controles\b",

            r"\bsin controles\b",

            r"\bruta segura\b",

            r"\bruta fácil\b",

            r"\busa esta ruta\b",

            r"\bcruzar esta noche\b",

            r"\bsalimos esta noche\b",

            r"\bpunto de encuentro\b",

            # French

            r"\bvenez ici\b",

            r"\bvenez à\b",

            r"\btraversez ici\b",

            r"\bon peut traverser\b",

            r"\bfrontière ouverte\b",

            r"\bpas de police\b",

            r"\bpas de contrôles\b",

            r"\bsans contrôle\b",

            r"\broute sûre\b",

            r"\bitinéraire sûr\b",

            r"\butilisez cette route\b",

            r"\btraverser ce soir\b",

            r"\bdépart ce soir\b",

            r"\bpoint de rendez-vous\b",
        ],


        # ------------------------------------------------------
        # LEGAL MIGRATION SIGNAL
        # ------------------------------------------------------

        "LEGAL_MIGRATION_SIGNAL": [

            # Courts / judgments

            r"\bcourt ruled\b",
            r"\bcourt has ruled\b",

            r"\bcourt decision\b",

            r"\bcourt judgment\b",
            r"\bcourt judgement\b",

            r"\bjudge ruled\b",

            r"\btribunal ruled\b",

            r"\beuropean court ruled\b",

            r"\beuropean court of human rights\b",

            r"\becthr\b",

            r"\bechr ruling\b",
            r"\bechr decision\b",

            r"\becj ruling\b",

            r"\bcourt of justice of the european union\b",

            # Deportation / return protection

            r"\bcannot be deported\b",
            r"\bcan't be deported\b",

            r"\bcannot deport\b",

            r"\bmay not be deported\b",

            r"\bcannot be returned\b",
            r"\bcan't be returned\b",

            r"\bmay not be returned\b",

            r"\breturn prohibited\b",

            r"\bdeportation prohibited\b",

            r"\bdeportation suspended\b",

            r"\bdeportation blocked\b",

            r"\bdeportation halted\b",

            r"\bdeportation stopped\b",

            r"\bremoval suspended\b",

            r"\bremoval blocked\b",

            r"\bremoval prohibited\b",

            r"\bexpulsion suspended\b",

            r"\bexpulsion prohibited\b",

            r"\bprotected from deportation\b",

            r"\bprotected from removal\b",

            r"\bprotection from return\b",

            # Protection concepts

            r"\bnon-refoulement\b",

            r"\bright to remain\b",

            r"\bright to stay\b",

            r"\bright to asylum\b",

            r"\btemporary right to remain\b",

            r"\bgranted asylum\b",

            r"\basylum granted\b",

            r"\bgranted protection\b",

            r"\bsubsidiary protection\b",

            r"\btemporary protection granted\b",

            # Spanish

            r"\bel tribunal dictaminó\b",

            r"\bel tribunal ha dictaminado\b",

            r"\bsentencia judicial\b",

            r"\bno puede ser deportado\b",
            r"\bno puede ser deportada\b",

            r"\bno puede ser devuelto\b",
            r"\bno puede ser devuelta\b",

            r"\bdeportación suspendida\b",

            r"\bexpulsión suspendida\b",

            r"\bderecho a permanecer\b",

            r"\basilo concedido\b",

            # French

            r"\ble tribunal a jugé\b",

            r"\bdécision de justice\b",

            r"\bne peut pas être expulsé\b",
            r"\bne peut pas être expulsée\b",

            r"\bne peut pas être renvoyé\b",
            r"\bne peut pas être renvoyée\b",

            r"\bexpulsion suspendue\b",

            r"\bdroit de rester\b",

            r"\basile accordé\b",
        ],


        # ------------------------------------------------------
        # POLICY SIGNAL
        # ------------------------------------------------------

        "POLICY_SIGNAL": [

            r"\btemporary protection\b",

            r"\btemporary protection scheme\b",

            r"\bnew asylum rules\b",

            r"\bnew asylum policy\b",

            r"\bnew migration policy\b",

            r"\bnew immigration rules\b",

            r"\bnew immigration policy\b",

            r"\brelocation scheme\b",

            r"\brelocation programme\b",
            r"\brelocation program\b",

            r"\bregularisation scheme\b",
            r"\bregularization scheme\b",

            r"\bmigrant amnesty\b",
            r"\bimmigration amnesty\b",

            r"\bamnesty for migrants\b",

            r"\blegal status granted\b",

            r"\bresidence permit granted\b",

            r"\btemporary residence\b",

            r"\bhumanitarian visa\b",

            r"\bhumanitarian visas\b",

            r"\bhumanitarian corridor\b",

            r"\basylum applications accepted\b",

            r"\bapplications will be accepted\b",

            r"\bprotection status\b",

            # Spanish

            r"\bprotección temporal\b",

            r"\bnuevas normas de asilo\b",

            r"\bnueva política migratoria\b",

            r"\bregularización\b",

            r"\bamnistía migratoria\b",

            r"\bpermiso de residencia\b",

            r"\bvisado humanitario\b",

            # French

            r"\bprotection temporaire\b",

            r"\bnouvelles règles d['’]asile\b",

            r"\bnouvelle politique migratoire\b",

            r"\brégularisation\b",

            r"\bvisa humanitaire\b",
        ],


        # ------------------------------------------------------
        # RECRUITMENT / COORDINATION
        # ------------------------------------------------------

        "RECRUITMENT_COORDINATION": [

            r"\bcontact me\b",

            r"\bcontact us\b",

            r"\bdm me\b",

            r"\bdm us\b",

            r"\bmessage me\b",

            r"\bmessage us\b",

            r"\bsend me a message\b",

            r"\bsend us a message\b",

            r"\bjoin the group\b",

            r"\bjoin our group\b",

            r"\bjoin telegram\b",

            r"\btelegram group\b",

            r"\bwhatsapp group\b",

            r"\bwhatsapp me\b",

            r"\btelegram me\b",

            r"\bdriver available\b",

            r"\bdrivers available\b",

            r"\btransport available\b",

            r"\bboat available\b",

            r"\bboats available\b",

            r"\bseats available\b",

            r"\bplaces available\b",

            r"\bspaces available\b",

            r"\bbook your place\b",

            r"\breserve your place\b",

            r"\bmeeting point\b",

            r"\bmeet us at\b",

            r"\bmeet at\b",

            # Spanish

            r"\bcontáctame\b",
            r"\bcontáctanos\b",

            r"\benvíame un mensaje\b",
            r"\benvíanos un mensaje\b",

            r"\búnete al grupo\b",

            r"\bgrupo de whatsapp\b",

            r"\bgrupo de telegram\b",

            r"\bconductor disponible\b",

            r"\btransporte disponible\b",

            r"\bbarco disponible\b",

            r"\bplazas disponibles\b",

            # French

            r"\bcontactez-moi\b",
            r"\bcontactez-nous\b",

            r"\benvoyez-moi un message\b",

            r"\brejoignez le groupe\b",

            r"\bgroupe whatsapp\b",

            r"\bgroupe telegram\b",

            r"\bchauffeur disponible\b",

            r"\btransport disponible\b",

            r"\bbateau disponible\b",

            r"\bplaces disponibles\b",
        ],
    }


    # ==========================================================
    # HIGH VALUE PATTERNS
    # ==========================================================

    HIGH_VALUE_PATTERNS = {

        "CROSSING_FACILITATION": [

            r"\bborder is open\b",

            r"\bcross here\b",

            r"\byou can cross\b",

            r"\bno police\b",

            r"\bno patrols\b",

            r"\bno border guards\b",

            r"\bboat leaves tonight\b",

            r"\bboat leaving tonight\b",

            r"\bse puede cruzar\b",

            r"\bfrontera abierta\b",

            r"\bno hay policía\b",

            r"\bon peut traverser\b",

            r"\bfrontière ouverte\b",

            r"\bpas de police\b",
        ],

        "LEGAL_MIGRATION_SIGNAL": [

            r"\bcannot be deported\b",

            r"\bcannot be returned\b",

            r"\bdeportation suspended\b",

            r"\bnon-refoulement\b",

            r"\bright to remain\b",

            r"\bcourt ruled\b",

            r"\beuropean court of human rights\b",

            r"\becthr\b",
        ],

        "POLICY_SIGNAL": [

            r"\bmigrant amnesty\b",

            r"\bimmigration amnesty\b",

            r"\bregularisation scheme\b",

            r"\bregularization scheme\b",

            r"\btemporary protection scheme\b",

            r"\bhumanitarian corridor\b",
        ],

        "RECRUITMENT_COORDINATION": [

            r"\bboat available\b",

            r"\bdriver available\b",

            r"\btransport available\b",

            r"\bjoin telegram\b",

            r"\bwhatsapp group\b",

            r"\bbook your place\b",

            r"\breserve your place\b",
        ],
    }


    # ==========================================================
    # PRIORITY
    # ==========================================================

    PRIORITY = [

        "CROSSING_FACILITATION",

        "RECRUITMENT_COORDINATION",

        "LEGAL_MIGRATION_SIGNAL",

        "POLICY_SIGNAL",
    ]


    # ==========================================================
    # BASE CONFIDENCE
    # ==========================================================

    BASE_CONFIDENCE = {

        "CROSSING_FACILITATION":
            0.78,

        "RECRUITMENT_COORDINATION":
            0.76,

        "LEGAL_MIGRATION_SIGNAL":
            0.80,

        "POLICY_SIGNAL":
            0.70,
    }


    # ==========================================================
    # PUBLIC DETECTOR
    # ==========================================================

    def detect(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects influence signals in migration-related text.

        Returns:

        {
            "detected": bool,
            "primary_signal": str | None,
            "matched_signals": list[str],
            "matched_phrases": list[tuple[str, str]],
            "migration_context": bool,
            "context_matches": list[str],
            "high_value_match": bool,
            "confidence": float
        }
        """

        if not text:

            return self._empty_result()

        context_matches = (
            self._find_context_matches(
                text
            )
        )

        migration_context = (
            len(
                context_matches
            )
            > 0
        )

        matched_signals: List[str] = []

        matched_phrases: List[
            Tuple[str, str]
        ] = []

        high_value_match = False

        # ------------------------------------------------------
        # DETECT SIGNAL PATTERNS
        # ------------------------------------------------------

        for (
            signal_type,
            patterns,
        ) in self.SIGNAL_PATTERNS.items():

            for pattern in patterns:

                match = re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )

                if not match:
                    continue

                if (
                    signal_type
                    not in matched_signals
                ):

                    matched_signals.append(
                        signal_type
                    )

                matched_phrases.append(
                    (
                        signal_type,
                        match.group(0),
                    )
                )

        # ------------------------------------------------------
        # NO SIGNAL
        # ------------------------------------------------------

        if not matched_signals:

            return {
                "detected":
                    False,

                "primary_signal":
                    None,

                "matched_signals":
                    [],

                "matched_phrases":
                    [],

                "migration_context":
                    migration_context,

                "context_matches":
                    context_matches,

                "high_value_match":
                    False,

                "confidence":
                    0.0,
            }

        # ------------------------------------------------------
        # HIGH VALUE CHECK
        # ------------------------------------------------------

        high_value_match = (
            self._has_high_value_match(
                text=text,
                signals=matched_signals,
            )
        )

        # ------------------------------------------------------
        # CONTEXT REQUIREMENT
        # ------------------------------------------------------

        signal_is_valid = (
            migration_context
            or high_value_match
        )

        if not signal_is_valid:

            return {
                "detected":
                    False,

                "primary_signal":
                    None,

                "matched_signals":
                    matched_signals,

                "matched_phrases":
                    matched_phrases,

                "migration_context":
                    False,

                "context_matches":
                    [],

                "high_value_match":
                    high_value_match,

                "confidence":
                    0.0,
            }

        # ------------------------------------------------------
        # PRIMARY SIGNAL
        # ------------------------------------------------------

        primary_signal = (
            self._select_primary_signal(
                matched_signals
            )
        )

        # ------------------------------------------------------
        # CONFIDENCE
        # ------------------------------------------------------

        confidence = (
            self._calculate_confidence(
                primary_signal=primary_signal,
                matched_signals=matched_signals,
                matched_phrases=matched_phrases,
                migration_context=(
                    migration_context
                ),
                context_matches=(
                    context_matches
                ),
                high_value_match=(
                    high_value_match
                ),
            )
        )

        return {
            "detected":
                True,

            "primary_signal":
                primary_signal,

            "matched_signals":
                matched_signals,

            "matched_phrases":
                matched_phrases,

            "migration_context":
                migration_context,

            "context_matches":
                context_matches,

            "high_value_match":
                high_value_match,

            "confidence":
                confidence,
        }


    # ==========================================================
    # CONTEXT MATCHING
    # ==========================================================

    def _find_context_matches(
        self,
        text: str,
    ) -> List[str]:
        """
        Finds explicit migration context terms.
        """

        matches: List[str] = []

        for pattern in (
            self.MIGRATION_CONTEXT_PATTERNS
        ):

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            normalized_match = (
                match.group(0)
            )

            if (
                normalized_match
                not in matches
            ):

                matches.append(
                    normalized_match
                )

        return matches


    # ==========================================================
    # HIGH VALUE MATCH
    # ==========================================================

    def _has_high_value_match(
        self,
        *,
        text: str,
        signals: List[str],
    ) -> bool:
        """
        Checks whether one of the detected signals contains
        a high-value phrase.

        High-value phrases can justify detection even when
        explicit migration terminology is missing.
        """

        for signal in signals:

            patterns = (
                self.HIGH_VALUE_PATTERNS.get(
                    signal,
                    [],
                )
            )

            for pattern in patterns:

                if re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                ):

                    return True

        return False


    # ==========================================================
    # PRIMARY SIGNAL
    # ==========================================================

    def _select_primary_signal(
        self,
        matched_signals: List[str],
    ) -> str:
        """
        Selects highest priority signal.
        """

        for signal in self.PRIORITY:

            if signal in matched_signals:

                return signal

        return matched_signals[0]


    # ==========================================================
    # CONFIDENCE
    # ==========================================================

    def _calculate_confidence(
        self,
        *,
        primary_signal: str,
        matched_signals: List[str],
        matched_phrases: List[
            Tuple[str, str]
        ],
        migration_context: bool,
        context_matches: List[str],
        high_value_match: bool,
    ) -> float:
        """
        Calculates confidence for the detected influence signal.

        Confidence increases when:

        - explicit migration context exists
        - several influence signals occur together
        - several phrases match
        - a high-value phrase is detected
        """

        confidence = (
            self.BASE_CONFIDENCE.get(
                primary_signal,
                0.60,
            )
        )

        if migration_context:

            confidence += 0.04

        if len(context_matches) >= 2:

            confidence += 0.02

        if len(matched_signals) >= 2:

            confidence += 0.04

        if len(matched_signals) >= 3:

            confidence += 0.02

        if len(matched_phrases) >= 3:

            confidence += 0.03

        if high_value_match:

            confidence += 0.05

        return round(
            min(
                confidence,
                0.99,
            ),
            2,
        )


    # ==========================================================
    # EMPTY RESULT
    # ==========================================================

    def _empty_result(
        self,
    ) -> Dict[str, object]:
        """
        Standard empty detector response.
        """

        return {
            "detected":
                False,

            "primary_signal":
                None,

            "matched_signals":
                [],

            "matched_phrases":
                [],

            "migration_context":
                False,

            "context_matches":
                [],

            "high_value_match":
                False,

            "confidence":
                0.0,
        }


# ==========================================================
# OPTIONAL MANUAL TEST
# ==========================================================

if __name__ == "__main__":

    detector = (
        InfluenceSignalDetector()
    )

    test_cases = [

        (
            "Migrants should come to this crossing tonight. "
            "There are no police and you can cross here."
        ),

        (
            "The court ruled that asylum seekers from this "
            "country cannot be returned."
        ),

        (
            "Temporary protection has been extended for refugees."
        ),

        (
            "Migrants can contact us on Telegram. "
            "Transport available and seats available."
        ),

        (
            "Come to the restaurant tonight."
        ),
    ]

    print(
        "==================================="
    )

    print(
        "Influence Signal Detector Test"
    )

    print(
        "==================================="
    )

    for index, text in enumerate(
        test_cases,
        start=1,
    ):

        result = detector.detect(
            text
        )

        print(
            f"\nTEST {index}"
        )

        print(
            "Text:",
            text,
        )

        print(
            "Detected:",
            result["detected"],
        )

        print(
            "Primary:",
            result["primary_signal"],
        )

        print(
            "Signals:",
            result["matched_signals"],
        )

        print(
            "Phrases:",
            result["matched_phrases"],
        )

        print(
            "Migration context:",
            result["migration_context"],
        )

        print(
            "Context matches:",
            result["context_matches"],
        )

        print(
            "High value:",
            result["high_value_match"],
        )

        print(
            "Confidence:",
            result["confidence"],
        )
