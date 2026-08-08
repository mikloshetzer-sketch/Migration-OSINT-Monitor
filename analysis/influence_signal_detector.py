"""
Migration OSINT Monitor

File:
influence_signal_detector.py

Description:
JSON-driven detector for migration-related influence,
facilitation and early-warning signals.

Knowledge base:

    config/influence_rules.json

The Python module contains detection logic only.

The detector identifies:

- CROSSING_FACILITATION
- LEGAL_MIGRATION_SIGNAL
- POLICY_SIGNAL
- RECRUITMENT_COORDINATION
- MOBILIZATION_COORDINATION
- DECISION_INFLUENCE
- MOBILIZATION_REPORT
- ONLINE_INFLUENCE_REPORT

Important:

A post is considered a detected influence signal only when:

1. migration context is valid
2. the configured minimum score is reached
3. at least one valid influence signal category is derived

This prevents candidate posts from being counted as real
influence signals when they contain relevant migration terms
but do not match a meaningful influence category.
"""

import json
import re
from datetime import datetime, timezone

from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ==========================================================
# PATHS
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DEFAULT_RULES_FILE = (
    PROJECT_ROOT
    / "config"
    / "influence_rules.json"
)


# ==========================================================
# DETECTOR
# ==========================================================

class InfluenceSignalDetector:
    """
    JSON-driven migration influence and early-warning detector.
    """

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        rules_file: Optional[Path] = None,
    ):
        """
        Loads detector configuration.
        """

        self.rules_file = (
            Path(rules_file)
            if rules_file
            else DEFAULT_RULES_FILE
        )

        self.rules = (
            self._load_rules()
        )

        self.settings = (
            self.rules.get(
                "settings",
                {},
            )
        )

        self.indicator_groups = (
            self.rules.get(
                "indicator_groups",
                {},
            )
        )

        self.signal_mapping = (
            self.rules.get(
                "signal_mapping",
                {},
            )
        )

        self.base_confidence = (
            self.rules.get(
                "base_confidence",
                {},
            )
        )

        self.score_levels = (
            self.rules.get(
                "score_levels",
                {},
            )
        )

        self.context_patterns = (
            self.rules.get(
                "context_patterns",
                [],
            )
        )

    # ======================================================
    # RULE LOADING
    # ======================================================

    def _load_rules(
        self,
    ) -> Dict[str, object]:
        """
        Loads influence_rules.json.
        """

        if not self.rules_file.exists():

            raise FileNotFoundError(
                "Influence rules file not found: "
                f"{self.rules_file}"
            )

        try:

            with self.rules_file.open(
                "r",
                encoding="utf-8",
            ) as file:

                rules = json.load(
                    file
                )

        except json.JSONDecodeError as error:

            raise ValueError(
                "Invalid JSON in influence rules file: "
                f"{self.rules_file}. "
                f"{error}"
            ) from error

        if not isinstance(
            rules,
            dict,
        ):

            raise ValueError(
                "Influence rules root must be a JSON object."
            )

        return rules

    # ======================================================
    # PUBLIC API
    # ======================================================

    def detect(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Analyses a post for migration influence and
        early-warning indicators.
        """

        if not text:

            return self._empty_result()

        normalized_text = (
            self._normalize_text(
                text
            )
        )

        # --------------------------------------------------
        # HISTORICAL REFERENCE GUARD
        # --------------------------------------------------
        #
        # Influence signals are meant to describe current or
        # forward-looking information conditions. A historical
        # retrospective such as "11 years ago ... first wave of
        # migrants" must not be counted as a current influence
        # signal merely because it contains migration / movement
        # vocabulary.
        #
        # Mixed texts that also contain a strong current or future
        # cue are not automatically suppressed.

        historical_result = (
            self._detect_historical_reference(
                normalized_text
            )
        )

        # --------------------------------------------------
        # MIGRATION CONTEXT
        # --------------------------------------------------

        context_result = (
            self._match_simple_section(
                normalized_text=normalized_text,
                section=self.rules.get(
                    "migration_context",
                    {},
                ),
                value_key="terms",
            )
        )

        migration_context = bool(
            context_result.get(
                "matches"
            )
        )

        # --------------------------------------------------
        # INDICATOR GROUPS
        # --------------------------------------------------

        indicator_results = (
            self._match_indicator_groups(
                normalized_text
            )
        )

        # --------------------------------------------------
        # STRUCTURED ENTITIES
        # --------------------------------------------------

        destination_result = (
            self._match_destinations(
                normalized_text
            )
        )

        origin_result = (
            self._match_origin_regions(
                normalized_text
            )
        )

        crossing_point_result = (
            self._match_crossing_points(
                normalized_text
            )
        )

        crossing_method_result = (
            self._match_crossing_methods(
                normalized_text
            )
        )

        platform_result = (
            self._match_platforms(
                normalized_text
            )
        )

        # --------------------------------------------------
        # NARRATIVES
        # --------------------------------------------------

        narrative_results = (
            self._match_narratives(
                normalized_text
            )
        )

        # --------------------------------------------------
        # HIGH VALUE
        # --------------------------------------------------

        high_value_result = (
            self._match_high_value_phrases(
                normalized_text
            )
        )

        high_value_match = bool(
            high_value_result.get(
                "matches"
            )
        )

        # --------------------------------------------------
        # NORMALIZED MATCH MAP
        # --------------------------------------------------

        matched_group_map = (
            self._build_group_map(
                migration_context=(
                    migration_context
                ),
                indicator_results=(
                    indicator_results
                ),
                destination_result=(
                    destination_result
                ),
                origin_result=(
                    origin_result
                ),
                crossing_point_result=(
                    crossing_point_result
                ),
                crossing_method_result=(
                    crossing_method_result
                ),
                platform_result=(
                    platform_result
                ),
                narrative_results=(
                    narrative_results
                ),
            )
        )

        # --------------------------------------------------
        # CONTEXT PATTERNS
        # --------------------------------------------------

        matched_context_patterns = (
            self._evaluate_context_patterns(
                matched_group_map
            )
        )

        # --------------------------------------------------
        # DERIVE SIGNALS BEFORE FINAL DETECTION
        # --------------------------------------------------

        matched_signals = (
            self._derive_signals(
                matched_group_map=(
                    matched_group_map
                ),
                matched_context_patterns=(
                    matched_context_patterns
                ),
            )
        )

        # --------------------------------------------------
        # SCORE
        # --------------------------------------------------

        score = (
            self._calculate_score(
                migration_context=(
                    migration_context
                ),
                context_result=(
                    context_result
                ),
                indicator_results=(
                    indicator_results
                ),
                destination_result=(
                    destination_result
                ),
                origin_result=(
                    origin_result
                ),
                crossing_point_result=(
                    crossing_point_result
                ),
                crossing_method_result=(
                    crossing_method_result
                ),
                platform_result=(
                    platform_result
                ),
                narrative_results=(
                    narrative_results
                ),
                high_value_result=(
                    high_value_result
                ),
                matched_context_patterns=(
                    matched_context_patterns
                ),
            )
        )

        score_level = (
            self._get_score_level(
                score
            )
        )

        # --------------------------------------------------
        # CONTEXT VALIDATION
        # --------------------------------------------------

        context_valid = (
            self._is_context_valid(
                migration_context=(
                    migration_context
                ),
                high_value_match=(
                    high_value_match
                ),
                matched_group_map=(
                    matched_group_map
                ),
            )
        )

        minimum_score = int(
            self.settings.get(
                "minimum_score",
                6,
            )
        )

        # --------------------------------------------------
        # FINAL DETECTION RULE
        # --------------------------------------------------
        #
        # IMPORTANT:
        #
        # A high score is NOT sufficient.
        #
        # At least one actual influence signal must also
        # have been derived.
        #
        # This fixes cases such as:
        #
        # migration context
        # + destination country
        # + border-policy information
        #
        # which may produce a useful candidate score but
        # must not automatically become an influence signal.

        detected = (
            context_valid
            and score >= minimum_score
            and len(
                matched_signals
            ) > 0
            and not historical_result.get(
                "is_historical",
                False,
            )
        )

        # --------------------------------------------------
        # PRIMARY SIGNAL
        # --------------------------------------------------

        primary_signal = None

        if detected:

            primary_signal = (
                self._select_primary_signal(
                    matched_signals=(
                        matched_signals
                    ),
                    matched_context_patterns=(
                        matched_context_patterns
                    ),
                )
            )

        # Secondary safeguard.
        #
        # A detected result is never allowed without a
        # primary signal.

        if not primary_signal:

            detected = False

        # --------------------------------------------------
        # CONFIDENCE
        # --------------------------------------------------

        confidence = 0.0

        if detected:

            confidence = (
                self._calculate_confidence(
                    primary_signal=(
                        primary_signal
                    ),
                    score=score,
                    score_level=(
                        score_level
                    ),
                    migration_context=(
                        migration_context
                    ),
                    high_value_match=(
                        high_value_match
                    ),
                    matched_group_map=(
                        matched_group_map
                    ),
                    matched_context_patterns=(
                        matched_context_patterns
                    ),
                )
            )

        # --------------------------------------------------
        # LEGACY / MAIN.PY COMPATIBILITY
        # --------------------------------------------------

        matched_phrases = (
            self._build_compatibility_phrases(
                primary_signal=(
                    primary_signal
                ),
                indicator_results=(
                    indicator_results
                ),
                narrative_results=(
                    narrative_results
                ),
                high_value_result=(
                    high_value_result
                ),
            )
        )

        # --------------------------------------------------
        # CANDIDATE STATUS
        # --------------------------------------------------

        candidate = (
            migration_context
            and score > 0
        )

        # --------------------------------------------------
        # RESULT
        # --------------------------------------------------

        return {
            # ----------------------------------------------
            # MAIN.PY COMPATIBILITY
            # ----------------------------------------------

            "detected":
                detected,

            "primary_signal":
                primary_signal,

            "matched_signals":
                (
                    matched_signals
                    if detected
                    else []
                ),

            "matched_phrases":
                (
                    matched_phrases
                    if detected
                    else []
                ),

            "migration_context":
                migration_context,

            "context_matches":
                context_result.get(
                    "matches",
                    [],
                ),

            "high_value_match":
                high_value_match,

            "confidence":
                confidence,

            # ----------------------------------------------
            # CANDIDATE INFORMATION
            # ----------------------------------------------

            "candidate":
                candidate,

            # ----------------------------------------------
            # ANALYTICAL FIELDS
            # ----------------------------------------------

            "score":
                score,

            "score_level":
                score_level,

            "matched_indicator_groups":
                self._matched_group_names(
                    indicator_results
                ),

            "indicator_matches":
                indicator_results,

            "matched_destination_countries":
                destination_result.get(
                    "entities",
                    [],
                ),

            "matched_origin_regions":
                origin_result.get(
                    "entities",
                    [],
                ),

            "matched_crossing_points":
                crossing_point_result.get(
                    "entities",
                    [],
                ),

            "matched_crossing_methods":
                crossing_method_result.get(
                    "entities",
                    [],
                ),

            "matched_platforms":
                platform_result.get(
                    "entities",
                    [],
                ),

            "matched_narratives":
                self._matched_group_names(
                    narrative_results
                ),

            "narrative_matches":
                narrative_results,

            "matched_context_patterns":
                matched_context_patterns,

            "high_value_matches":
                high_value_result.get(
                    "matches",
                    [],
                ),

            "historical_reference":
                historical_result.get(
                    "is_historical",
                    False,
                ),

            "historical_reason":
                historical_result.get(
                    "reason"
                ),

            "historical_reference_text":
                historical_result.get(
                    "reference_text"
                ),

            "signal_mode":
                self._get_signal_mode(
                    primary_signal
                ),

            "rules_version":
                self.rules.get(
                    "version"
                ),
        }

    # ======================================================
    # HISTORICAL REFERENCE DETECTION
    # ======================================================

    def _detect_historical_reference(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects clear retrospective references that should not
        be treated as current influence signals.

        The method is deliberately conservative. It suppresses
        historical-only statements, but allows mixed posts when
        they also contain a strong current or future cue.

        Examples suppressed:

            "11 years ago ... first wave of migrants"
            "In 1947 refugees arrived ..."
            "During the 2015 migration crisis ..."

        Examples not automatically suppressed:

            "In 2015 this happened, but today migrants are
             gathering again."

            "11 years ago this route was used; on August 15
             another crossing is planned."
        """

        if not text:

            return {
                "is_historical": False,
                "reason": None,
                "reference_text": None,
            }

        # Strong present / future cues override a purely
        # retrospective interpretation.
        current_or_future_patterns = [
            r"\btoday\b",
            r"\btonight\b",
            r"\bnow\b",
            r"\bcurrently\b",
            r"\bthis\s+week\b",
            r"\bthis\s+month\b",
            r"\bthis\s+year\b",
            r"\btomorrow\b",
            r"\bnext\s+week\b",
            r"\bnext\s+month\b",
            r"\bnext\s+year\b",
            r"\bupcoming\b",
            r"\bplanned\b",
            r"\bis\s+planned\b",
            r"\bare\s+planned\b",
            r"\bplans\s+to\b",
            r"\bplans\s+for\b",
            r"\bthere\s+are\s+plans\b",
            r"\bpreparing\b",
            r"\bexpected\s+to\b",
            r"\bexpect(?:ed|s|ing)?\b",
            r"\bwill\s+cross\b",
            r"\bwill\s+arrive\b",
            r"\bwill\s+gather\b",
            r"\bwill\s+move\b",
            r"\bon\s+[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?\b",
            r"\bon\s+\d{1,2}\s+[A-Z][a-z]+\b",
            r"\baujourd'hui\b",
            r"\bmaintenant\b",
            r"\bdemain\b",
            r"\bhoy\b",
            r"\bahora\b",
            r"\bmañana\b",
            r"\boggi\b",
            r"\badesso\b",
            r"\bdomani\b",
        ]

        has_current_or_future_cue = any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            for pattern in current_or_future_patterns
        )

        # "N years ago", including written numbers.
        years_ago_pattern = re.compile(
            r"\b("
            r"\d{1,3}|"
            r"one|two|three|four|five|six|seven|eight|nine|ten|"
            r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
            r"seventeen|eighteen|nineteen|twenty"
            r")\s+years?\s+ago\b",
            flags=re.IGNORECASE,
        )

        match = years_ago_pattern.search(
            text
        )

        if (
            match
            and not has_current_or_future_cue
        ):

            return {
                "is_historical": True,
                "reason": "YEARS_AGO_REFERENCE",
                "reference_text": match.group(0),
            }

        # "decades ago", "years ago", etc.
        relative_history_pattern = re.compile(
            r"\b("
            r"decades?\s+ago|"
            r"many\s+years\s+ago|"
            r"several\s+years\s+ago|"
            r"back\s+in\s+the\s+\d{4}s?|"
            r"looking\s+back"
            r")\b",
            flags=re.IGNORECASE,
        )

        match = relative_history_pattern.search(
            text
        )

        if (
            match
            and not has_current_or_future_cue
        ):

            return {
                "is_historical": True,
                "reason": "RETROSPECTIVE_REFERENCE",
                "reference_text": match.group(0),
            }

        # Explicit previous calendar years.
        current_year = datetime.now(
            timezone.utc
        ).year

        explicit_years = [
            int(value)
            for value in re.findall(
                r"(?<!\d)(19\d{2}|20\d{2})(?!\d)",
                text,
            )
        ]

        old_years = [
            year
            for year in explicit_years
            if year < current_year
        ]

        if (
            old_years
            and not has_current_or_future_cue
        ):

            newest_old_year = max(
                old_years
            )

            return {
                "is_historical": True,
                "reason": "EXPLICIT_PREVIOUS_YEAR",
                "reference_text": str(
                    newest_old_year
                ),
            }

        # Decade references such as "1870s" or "1990s".
        decade_match = re.search(
            r"(?<!\d)(18|19|20)\d0s(?!\d)",
            text,
            flags=re.IGNORECASE,
        )

        if (
            decade_match
            and not has_current_or_future_cue
        ):

            return {
                "is_historical": True,
                "reason": "HISTORICAL_DECADE_REFERENCE",
                "reference_text": decade_match.group(0),
            }

        return {
            "is_historical": False,
            "reason": None,
            "reference_text": None,
        }

    def _get_signal_mode(
        self,
        primary_signal: Optional[str],
    ) -> Optional[str]:
        """
        Distinguishes direct influence / facilitation content
        from reporting about influence or mobilization.

        This does not change the primary signal name. It adds
        an analytical field that downstream components can use.
        """

        if not primary_signal:

            return None

        if primary_signal in {
            "MOBILIZATION_REPORT",
            "ONLINE_INFLUENCE_REPORT",
        }:
            return "REPORT"

        return "DIRECT"


    # ======================================================
    # TEXT NORMALIZATION
    # ======================================================

    def _normalize_text(
        self,
        text: str,
    ) -> str:
        """
        Normalizes whitespace while preserving Unicode.
        """

        text = str(
            text
        )

        text = text.replace(
            "\n",
            " "
        )

        text = text.replace(
            "\r",
            " "
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    # ======================================================
    # TERM MATCHING
    # ======================================================

    def _contains_term(
        self,
        text: str,
        term: str,
    ) -> Optional[str]:
        """
        Case-insensitive literal matching.

        Conservative token boundaries reduce substring
        false positives.
        """

        if not term:

            return None

        term = str(
            term
        ).strip()

        if not term:

            return None

        escaped = re.escape(
            term
        )

        first_character = (
            term[0]
        )

        last_character = (
            term[-1]
        )

        prefix = (
            r"(?<!\w)"
            if (
                first_character.isalnum()
                or first_character == "_"
            )
            else ""
        )

        suffix = (
            r"(?!\w)"
            if (
                last_character.isalnum()
                or last_character == "_"
            )
            else ""
        )

        pattern = (
            prefix
            + escaped
            + suffix
        )

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:

            return match.group(
                0
            )

        return None

    # ======================================================
    # SIMPLE SECTION
    # ======================================================

    def _match_simple_section(
        self,
        *,
        normalized_text: str,
        section: Dict[str, object],
        value_key: str,
    ) -> Dict[str, object]:
        """
        Matches a flat configured term list.
        """

        terms = (
            section.get(
                value_key,
                [],
            )
            or []
        )

        matches: List[str] = []

        normalized_seen = set()

        for term in terms:

            match = (
                self._contains_term(
                    normalized_text,
                    str(term),
                )
            )

            if not match:
                continue

            match_key = (
                match.lower()
            )

            if match_key in normalized_seen:
                continue

            normalized_seen.add(
                match_key
            )

            matches.append(
                match
            )

        return {
            "matched":
                bool(matches),

            "matches":
                matches,

            "weight":
                int(
                    section.get(
                        "weight",
                        0,
                    )
                    or 0
                ),
        }

    # ======================================================
    # INDICATOR GROUPS
    # ======================================================

    def _match_indicator_groups(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Matches configured indicator groups.
        """

        results = {}

        for (
            group_name,
            configuration,
        ) in self.indicator_groups.items():

            results[
                group_name
            ] = (
                self._match_simple_section(
                    normalized_text=text,
                    section=configuration,
                    value_key="terms",
                )
            )

        return results

    # ======================================================
    # ALIASES
    # ======================================================

    def _match_aliases(
        self,
        *,
        text: str,
        aliases: List[str],
    ) -> List[str]:
        """
        Matches configured aliases.
        """

        matches = []

        seen = set()

        for alias in aliases:

            match = (
                self._contains_term(
                    text,
                    str(alias),
                )
            )

            if not match:
                continue

            key = (
                match.lower()
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            matches.append(
                match
            )

        return matches

    # ======================================================
    # DESTINATIONS
    # ======================================================

    def _match_destinations(
        self,
        text: str,
    ) -> Dict[str, object]:

        section = (
            self.rules.get(
                "destination_countries",
                {},
            )
        )

        entities = []

        for country in (
            section.get(
                "countries",
                [],
            )
            or []
        ):

            matched_aliases = (
                self._match_aliases(
                    text=text,
                    aliases=(
                        country.get(
                            "aliases",
                            [],
                        )
                        or []
                    ),
                )
            )

            if not matched_aliases:
                continue

            entities.append(
                {
                    "name":
                        country.get(
                            "name"
                        ),

                    "continent":
                        country.get(
                            "continent"
                        ),

                    "type":
                        country.get(
                            "type"
                        ),

                    "schengen":
                        country.get(
                            "schengen"
                        ),

                    "importance":
                        country.get(
                            "importance"
                        ),

                    "matched_aliases":
                        matched_aliases,
                }
            )

        return {
            "matched":
                bool(entities),

            "entities":
                entities,

            "weight":
                int(
                    section.get(
                        "weight",
                        0,
                    )
                    or 0
                ),
        }

    # ======================================================
    # ORIGIN REGIONS
    # ======================================================

    def _match_origin_regions(
        self,
        text: str,
    ) -> Dict[str, object]:

        section = (
            self.rules.get(
                "origin_regions",
                {},
            )
        )

        entities = []

        for region in (
            section.get(
                "regions",
                [],
            )
            or []
        ):

            matched_countries = (
                self._match_aliases(
                    text=text,
                    aliases=(
                        region.get(
                            "countries",
                            [],
                        )
                        or []
                    ),
                )
            )

            if not matched_countries:
                continue

            entities.append(
                {
                    "name":
                        region.get(
                            "name"
                        ),

                    "importance":
                        region.get(
                            "importance"
                        ),

                    "matched_countries":
                        matched_countries,
                }
            )

        return {
            "matched":
                bool(entities),

            "entities":
                entities,

            "weight":
                int(
                    section.get(
                        "weight",
                        0,
                    )
                    or 0
                ),
        }

    # ======================================================
    # CROSSING POINTS
    # ======================================================

    def _match_crossing_points(
        self,
        text: str,
    ) -> Dict[str, object]:

        section = (
            self.rules.get(
                "crossing_points",
                {},
            )
        )

        entities = []

        for point in (
            section.get(
                "points",
                [],
            )
            or []
        ):

            matched_aliases = (
                self._match_aliases(
                    text=text,
                    aliases=(
                        point.get(
                            "aliases",
                            [],
                        )
                        or []
                    ),
                )
            )

            if not matched_aliases:
                continue

            entities.append(
                {
                    "name":
                        point.get(
                            "name"
                        ),

                    "country":
                        point.get(
                            "country"
                        ),

                    "route":
                        point.get(
                            "route"
                        ),

                    "type":
                        point.get(
                            "type"
                        ),

                    "importance":
                        point.get(
                            "importance"
                        ),

                    "matched_aliases":
                        matched_aliases,
                }
            )

        return {
            "matched":
                bool(entities),

            "entities":
                entities,

            "weight":
                int(
                    section.get(
                        "weight",
                        0,
                    )
                    or 0
                ),
        }

    # ======================================================
    # CROSSING METHODS
    # ======================================================

    def _match_crossing_methods(
        self,
        text: str,
    ) -> Dict[str, object]:

        section = (
            self.rules.get(
                "crossing_methods",
                {},
            )
        )

        entities = []

        for method in (
            section.get(
                "methods",
                [],
            )
            or []
        ):

            matched_aliases = (
                self._match_aliases(
                    text=text,
                    aliases=(
                        method.get(
                            "aliases",
                            [],
                        )
                        or []
                    ),
                )
            )

            if not matched_aliases:
                continue

            entities.append(
                {
                    "name":
                        method.get(
                            "name"
                        ),

                    "type":
                        method.get(
                            "type"
                        ),

                    "importance":
                        method.get(
                            "importance"
                        ),

                    "matched_aliases":
                        matched_aliases,
                }
            )

        return {
            "matched":
                bool(entities),

            "entities":
                entities,

            "weight":
                int(
                    section.get(
                        "weight",
                        0,
                    )
                    or 0
                ),
        }

    # ======================================================
    # PLATFORMS
    # ======================================================

    def _match_platforms(
        self,
        text: str,
    ) -> Dict[str, object]:

        section = (
            self.rules.get(
                "platform_indicators",
                {},
            )
        )

        entities = []

        for platform in (
            section.get(
                "platforms",
                [],
            )
            or []
        ):

            matched_aliases = (
                self._match_aliases(
                    text=text,
                    aliases=(
                        platform.get(
                            "aliases",
                            [],
                        )
                        or []
                    ),
                )
            )

            if not matched_aliases:
                continue

            entities.append(
                {
                    "name":
                        platform.get(
                            "name"
                        ),

                    "importance":
                        platform.get(
                            "importance"
                        ),

                    "risk":
                        platform.get(
                            "risk"
                        ),

                    "matched_aliases":
                        matched_aliases,
                }
            )

        return {
            "matched":
                bool(entities),

            "entities":
                entities,

            "weight":
                int(
                    section.get(
                        "weight",
                        0,
                    )
                    or 0
                ),
        }

    # ======================================================
    # NARRATIVES
    # ======================================================

    def _match_narratives(
        self,
        text: str,
    ) -> Dict[str, object]:

        narratives = (
            self.rules.get(
                "narratives",
                {},
            )
        )

        results = {}

        for (
            narrative_name,
            configuration,
        ) in narratives.items():

            results[
                narrative_name
            ] = (
                self._match_simple_section(
                    normalized_text=text,
                    section=configuration,
                    value_key="terms",
                )
            )

        return results

    # ======================================================
    # HIGH VALUE
    # ======================================================

    def _match_high_value_phrases(
        self,
        text: str,
    ) -> Dict[str, object]:

        section = (
            self.rules.get(
                "high_value_phrases",
                {},
            )
        )

        matches = []

        seen = set()

        for term in (
            section.get(
                "terms",
                [],
            )
            or []
        ):

            match = (
                self._contains_term(
                    text,
                    str(term),
                )
            )

            if not match:
                continue

            key = (
                match.lower()
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            matches.append(
                match
            )

        return {
            "matched":
                bool(matches),

            "matches":
                matches,

            "bonus_score":
                int(
                    section.get(
                        "bonus_score",
                        0,
                    )
                    or 0
                ),
        }

    # ======================================================
    # GROUP MAP
    # ======================================================

    def _build_group_map(
        self,
        *,
        migration_context: bool,
        indicator_results: Dict[str, object],
        destination_result: Dict[str, object],
        origin_result: Dict[str, object],
        crossing_point_result: Dict[str, object],
        crossing_method_result: Dict[str, object],
        platform_result: Dict[str, object],
        narrative_results: Dict[str, object],
    ) -> Dict[str, bool]:

        result = {
            "migration_context":
                migration_context,

            "destination_country":
                bool(
                    destination_result.get(
                        "matched"
                    )
                ),

            "origin_region":
                bool(
                    origin_result.get(
                        "matched"
                    )
                ),

            "crossing_point":
                bool(
                    crossing_point_result.get(
                        "matched"
                    )
                ),

            "crossing_method":
                bool(
                    crossing_method_result.get(
                        "matched"
                    )
                ),

            "platform_indicator":
                bool(
                    platform_result.get(
                        "matched"
                    )
                ),
        }

        for (
            group_name,
            group_result,
        ) in indicator_results.items():

            result[
                group_name
            ] = bool(
                group_result.get(
                    "matched"
                )
            )

        for (
            narrative_name,
            narrative_result,
        ) in narrative_results.items():

            result[
                narrative_name
            ] = bool(
                narrative_result.get(
                    "matched"
                )
            )

        return result

    # ======================================================
    # CONTEXT PATTERNS
    # ======================================================

    def _evaluate_context_patterns(
        self,
        matched_group_map: Dict[str, bool],
    ) -> List[Dict[str, object]]:

        results = []

        for pattern in (
            self.context_patterns
        ):

            required_groups = (
                pattern.get(
                    "required_groups",
                    [],
                )
                or []
            )

            optional_groups = (
                pattern.get(
                    "optional_groups",
                    [],
                )
                or []
            )

            required_match = all(
                matched_group_map.get(
                    group,
                    False,
                )
                for group
                in required_groups
            )

            if not required_match:
                continue

            matched_optional = [
                group
                for group
                in optional_groups
                if matched_group_map.get(
                    group,
                    False,
                )
            ]

            results.append(
                {
                    "id":
                        pattern.get(
                            "id"
                        ),

                    "name":
                        pattern.get(
                            "name"
                        ),

                    "score":
                        int(
                            pattern.get(
                                "score",
                                0,
                            )
                            or 0
                        ),

                    "result_hint":
                        pattern.get(
                            "result_hint"
                        ),

                    "required_groups":
                        required_groups,

                    "matched_optional_groups":
                        matched_optional,
                }
            )

        return results

    # ======================================================
    # SCORE
    # ======================================================

    def _calculate_score(
        self,
        *,
        migration_context: bool,
        context_result: Dict[str, object],
        indicator_results: Dict[str, object],
        destination_result: Dict[str, object],
        origin_result: Dict[str, object],
        crossing_point_result: Dict[str, object],
        crossing_method_result: Dict[str, object],
        platform_result: Dict[str, object],
        narrative_results: Dict[str, object],
        high_value_result: Dict[str, object],
        matched_context_patterns: List[
            Dict[str, object]
        ],
    ) -> int:

        score = 0

        if migration_context:

            score += int(
                context_result.get(
                    "weight",
                    0,
                )
                or 0
            )

        for result in (
            indicator_results.values()
        ):

            if result.get(
                "matched"
            ):

                score += int(
                    result.get(
                        "weight",
                        0,
                    )
                    or 0
                )

        for result in [
            destination_result,
            origin_result,
            crossing_point_result,
            crossing_method_result,
            platform_result,
        ]:

            if result.get(
                "matched"
            ):

                score += int(
                    result.get(
                        "weight",
                        0,
                    )
                    or 0
                )

        for result in (
            narrative_results.values()
        ):

            if result.get(
                "matched"
            ):

                score += int(
                    result.get(
                        "weight",
                        0,
                    )
                    or 0
                )

        if high_value_result.get(
            "matched"
        ):

            score += int(
                high_value_result.get(
                    "bonus_score",
                    0,
                )
                or 0
            )

        for pattern in (
            matched_context_patterns
        ):

            score += int(
                pattern.get(
                    "score",
                    0,
                )
                or 0
            )

        return score

    # ======================================================
    # SCORE LEVEL
    # ======================================================

    def _get_score_level(
        self,
        score: int,
    ) -> str:

        levels = []

        for (
            level_name,
            configuration,
        ) in self.score_levels.items():

            levels.append(
                (
                    int(
                        configuration.get(
                            "minimum",
                            0,
                        )
                        or 0
                    ),
                    level_name,
                )
            )

        levels.sort(
            key=lambda item:
                item[0],
            reverse=True,
        )

        for (
            minimum,
            level_name,
        ) in levels:

            if score >= minimum:

                return level_name

        return "NONE"

    # ======================================================
    # CONTEXT VALIDATION
    # ======================================================

    def _is_context_valid(
        self,
        *,
        migration_context: bool,
        high_value_match: bool,
        matched_group_map: Dict[str, bool],
    ) -> bool:

        require_context = bool(
            self.settings.get(
                "require_migration_context",
                True,
            )
        )

        if not require_context:

            return True

        if migration_context:

            return True

        allow_override = bool(
            self.settings.get(
                "allow_high_value_override",
                False,
            )
        )

        if not allow_override:

            return False

        if not high_value_match:

            return False

        supporting_groups = {
            "movement",
            "mass_movement",
            "route_information",
            "facilitation",
            "legal_signal",
            "policy_signal",
            "border_condition",
            "smuggling_ecosystem",
            "destination_country",
            "origin_region",
            "crossing_point",
            "crossing_method",
            "information_spread",
            "legal_protection",
            "border_access",
            "coordination",
            "route_promotion",
            "policy_pull_factor",
            "mobilization",
            "mobilization_coordination",
            "decision_influence",
            "mobilization_report",
            "online_influence_report",
        }

        supporting_match_count = sum(
            1
            for group
            in supporting_groups
            if matched_group_map.get(
                group,
                False,
            )
        )

        return (
            supporting_match_count
            >= 1
        )

    # ======================================================
    # SIGNAL DERIVATION
    # ======================================================

    def _derive_signals(
        self,
        *,
        matched_group_map: Dict[str, bool],
        matched_context_patterns: List[
            Dict[str, object]
        ],
    ) -> List[str]:

        signals = []

        # --------------------------------------------------
        # DIRECT SIGNAL MAPPING
        # --------------------------------------------------

        for (
            signal_name,
            groups,
        ) in self.signal_mapping.items():

            if any(
                matched_group_map.get(
                    group,
                    False,
                )
                for group
                in groups
            ):

                if (
                    signal_name
                    not in signals
                ):

                    signals.append(
                        signal_name
                    )

        # --------------------------------------------------
        # CONTEXT PATTERN RESULT HINTS
        # --------------------------------------------------

        for pattern in (
            matched_context_patterns
        ):

            result_hint = (
                pattern.get(
                    "result_hint"
                )
            )

            if (
                result_hint
                and result_hint
                not in signals
            ):

                signals.append(
                    result_hint
                )

        return signals

    # ======================================================
    # PRIMARY SIGNAL
    # ======================================================

    def _select_primary_signal(
        self,
        *,
        matched_signals: List[str],
        matched_context_patterns: List[
            Dict[str, object]
        ],
    ) -> Optional[str]:

        if not matched_signals:

            return None

        pattern_scores = {}

        for pattern in (
            matched_context_patterns
        ):

            result_hint = (
                pattern.get(
                    "result_hint"
                )
            )

            if not result_hint:
                continue

            pattern_scores[
                result_hint
            ] = (
                pattern_scores.get(
                    result_hint,
                    0,
                )
                +
                int(
                    pattern.get(
                        "score",
                        0,
                    )
                    or 0
                )
            )

        if pattern_scores:

            strongest_signal = max(
                pattern_scores,
                key=pattern_scores.get,
            )

            if strongest_signal in matched_signals:

                return strongest_signal

        priority = [
            "RECRUITMENT_COORDINATION",
            "MOBILIZATION_COORDINATION",
            "MOBILIZATION_REPORT",
            "ONLINE_INFLUENCE_REPORT",
            "LEGAL_MIGRATION_SIGNAL",
            "DECISION_INFLUENCE",
            "CROSSING_FACILITATION",
            "POLICY_SIGNAL",
        ]

        for signal in priority:

            if signal in matched_signals:

                return signal

        return matched_signals[0]

    # ======================================================
    # CONFIDENCE
    # ======================================================

    def _calculate_confidence(
        self,
        *,
        primary_signal: Optional[str],
        score: int,
        score_level: str,
        migration_context: bool,
        high_value_match: bool,
        matched_group_map: Dict[str, bool],
        matched_context_patterns: List[
            Dict[str, object]
        ],
    ) -> float:

        if not primary_signal:

            return 0.0

        confidence = float(
            self.base_confidence.get(
                primary_signal,
                0.60,
            )
        )

        level_configuration = (
            self.score_levels.get(
                score_level,
                {},
            )
        )

        confidence += float(
            level_configuration.get(
                "confidence_bonus",
                0.0,
            )
            or 0.0
        )

        if migration_context:

            confidence += 0.03

        if high_value_match:

            confidence += 0.04

        matched_group_count = sum(
            1
            for matched
            in matched_group_map.values()
            if matched
        )

        if matched_group_count >= 4:

            confidence += 0.03

        if matched_group_count >= 6:

            confidence += 0.02

        if matched_context_patterns:

            confidence += 0.03

        if len(
            matched_context_patterns
        ) >= 2:

            confidence += 0.02

        maximum = float(
            self.settings.get(
                "max_confidence",
                0.99,
            )
        )

        return round(
            min(
                confidence,
                maximum,
            ),
            2,
        )

    # ======================================================
    # COMPATIBILITY PHRASES
    # ======================================================

    def _build_compatibility_phrases(
        self,
        *,
        primary_signal: Optional[str],
        indicator_results: Dict[str, object],
        narrative_results: Dict[str, object],
        high_value_result: Dict[str, object],
    ) -> List[Tuple[str, str]]:

        if not primary_signal:

            return []

        results = []

        seen = set()

        for (
            group_name,
            group_result,
        ) in indicator_results.items():

            for phrase in (
                group_result.get(
                    "matches",
                    [],
                )
                or []
            ):

                key = (
                    group_name,
                    phrase.lower(),
                )

                if key in seen:
                    continue

                seen.add(
                    key
                )

                results.append(
                    (
                        group_name,
                        phrase,
                    )
                )

        for (
            narrative_name,
            narrative_result,
        ) in narrative_results.items():

            for phrase in (
                narrative_result.get(
                    "matches",
                    [],
                )
                or []
            ):

                key = (
                    narrative_name,
                    phrase.lower(),
                )

                if key in seen:
                    continue

                seen.add(
                    key
                )

                results.append(
                    (
                        narrative_name,
                        phrase,
                    )
                )

        for phrase in (
            high_value_result.get(
                "matches",
                [],
            )
            or []
        ):

            key = (
                "HIGH_VALUE",
                phrase.lower(),
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            results.append(
                (
                    "HIGH_VALUE",
                    phrase,
                )
            )

        return results

    # ======================================================
    # MATCHED GROUP NAMES
    # ======================================================

    def _matched_group_names(
        self,
        results: Dict[str, object],
    ) -> List[str]:

        return [
            name
            for (
                name,
                result,
            ) in results.items()
            if result.get(
                "matched"
            )
        ]

    # ======================================================
    # EMPTY RESULT
    # ======================================================

    def _empty_result(
        self,
    ) -> Dict[str, object]:

        return {
            "detected":
                False,

            "candidate":
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

            "score":
                0,

            "score_level":
                "NONE",

            "matched_indicator_groups":
                [],

            "indicator_matches":
                {},

            "matched_destination_countries":
                [],

            "matched_origin_regions":
                [],

            "matched_crossing_points":
                [],

            "matched_crossing_methods":
                [],

            "matched_platforms":
                [],

            "matched_narratives":
                [],

            "narrative_matches":
                {},

            "matched_context_patterns":
                [],

            "high_value_matches":
                [],

            "historical_reference":
                False,

            "historical_reason":
                None,

            "historical_reference_text":
                None,

            "signal_mode":
                None,

            "rules_version":
                self.rules.get(
                    "version"
                ),
        }


# ==========================================================
# MANUAL TEST
# ==========================================================

if __name__ == "__main__":

    detector = (
        InfluenceSignalDetector()
    )

    test_cases = [
        (
            "Hundreds of migrants are gathering near Calais "
            "and moving toward small boat launch locations."
        ),
        (
            "The court ruled that asylum seekers cannot "
            "currently be returned."
        ),
        (
            "Migrants can contact us on Telegram. "
            "Transport available and seats available."
        ),
        (
            "Spain introduced temporary border controls "
            "because of migration pressure."
        ),
        (
            "Come to the restaurant tonight. "
            "There are no police nearby."
        ),
        (
            "There are plans for migrants to storm the Spanish "
            "city of Ceuta again this month on August 15th. "
            "We expect tens of thousands to cross the border."
        ),
        (
            "Over 70,000 migrants swam from Morocco, lured by "
            "online falsehoods circulating on social media."
        ),
        (
            "11 years ago, I was in Athens when the first wave "
            "of migrants arrived. Looking back, I did not know "
            "how large it would become."
        ),
    ]

    print(
        "==================================="
    )

    print(
        "Migration Influence Detector Test"
    )

    print(
        "Rules:",
        detector.rules_file,
    )

    print(
        "Rules version:",
        detector.rules.get(
            "version"
        ),
    )

    print(
        "==================================="
    )

    for index, text in enumerate(
        test_cases,
        start=1,
    ):

        result = (
            detector.detect(
                text
            )
        )

        print()

        print(
            "-----------------------------------"
        )

        print(
            f"TEST {index}"
        )

        print(
            "-----------------------------------"
        )

        print(
            "Text:",
            text,
        )

        print(
            "Candidate:",
            result.get(
                "candidate"
            ),
        )

        print(
            "Detected:",
            result.get(
                "detected"
            ),
        )

        print(
            "Primary signal:",
            result.get(
                "primary_signal"
            ),
        )

        print(
            "Matched signals:",
            result.get(
                "matched_signals"
            ),
        )

        print(
            "Score:",
            result.get(
                "score"
            ),
        )

        print(
            "Score level:",
            result.get(
                "score_level"
            ),
        )

        print(
            "Confidence:",
            result.get(
                "confidence"
            ),
        )

        print(
            "Indicator groups:",
            result.get(
                "matched_indicator_groups"
            ),
        )

        print(
            "Context patterns:",
            result.get(
                "matched_context_patterns"
            ),
        )
