"""
Migration OSINT Monitor

File:
influence_signal_detector.py

Description:
JSON-driven detector for migration-related influence,
facilitation and early-warning signals.

The detector loads its knowledge base from:

    config/influence_rules.json

The Python module contains detection logic only.
Keywords, locations, routes, crossing methods,
platform indicators, narratives, weights and
context rules are maintained in JSON.

Main output categories:

- CROSSING_FACILITATION
- LEGAL_MIGRATION_SIGNAL
- POLICY_SIGNAL
- RECRUITMENT_COORDINATION

The detector does not verify whether a claim is true.
It identifies potentially relevant migration-related
information signals for further OSINT analysis.
"""

import json
import re

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
    Detects migration-related influence and early-warning
    signals using rules loaded from JSON.

    The detector is deliberately separated from the normal
    operational event classifier.

    Example:

        Migrants are gathering near the coast.
        Videos of the route are circulating on Telegram.

    This may represent an early-warning / influence signal
    even if an actual border crossing has not yet occurred.
    """

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        rules_file: Optional[Path] = None,
    ):
        """
        Loads the migration influence knowledge base.
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
        Loads and validates influence_rules.json.
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

        Existing main.py-compatible fields are preserved:

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

        Additional analytical fields are also returned.
        """

        if not text:

            return self._empty_result()

        normalized_text = (
            self._normalize_text(
                text
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
            context_result["matches"]
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
        # HIGH VALUE PHRASES
        # --------------------------------------------------

        high_value_result = (
            self._match_high_value_phrases(
                normalized_text
            )
        )

        high_value_match = bool(
            high_value_result["matches"]
        )

        # --------------------------------------------------
        # BUILD MATCHED GROUP MAP
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
                5,
            )
        )

        detected = (
            context_valid
            and score >= minimum_score
        )

        # --------------------------------------------------
        # SIGNAL SELECTION
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

        primary_signal = (
            self._select_primary_signal(
                matched_signals=(
                    matched_signals
                ),
                matched_context_patterns=(
                    matched_context_patterns
                ),
            )
            if detected
            else None
        )

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
        # COMPATIBILITY PHRASES
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
        # FINAL RESULT
        # --------------------------------------------------

        return {
            # ----------------------------------------------
            # ORIGINAL COMPATIBILITY FIELDS
            # ----------------------------------------------

            "detected":
                detected,

            "primary_signal":
                primary_signal,

            "matched_signals":
                matched_signals,

            "matched_phrases":
                matched_phrases,

            "migration_context":
                migration_context,

            "context_matches":
                context_result[
                    "matches"
                ],

            "high_value_match":
                high_value_match,

            "confidence":
                confidence,

            # ----------------------------------------------
            # NEW ANALYTICAL FIELDS
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
                destination_result[
                    "entities"
                ],

            "matched_origin_regions":
                origin_result[
                    "entities"
                ],

            "matched_crossing_points":
                crossing_point_result[
                    "entities"
                ],

            "matched_crossing_methods":
                crossing_method_result[
                    "entities"
                ],

            "matched_platforms":
                platform_result[
                    "entities"
                ],

            "matched_narratives":
                self._matched_group_names(
                    narrative_results
                ),

            "narrative_matches":
                narrative_results,

            "matched_context_patterns":
                matched_context_patterns,

            "high_value_matches":
                high_value_result[
                    "matches"
                ],

            "rules_version":
                self.rules.get(
                    "version"
                ),
        }

    # ======================================================
    # TEXT NORMALIZATION
    # ======================================================

    def _normalize_text(
        self,
        text: str,
    ) -> str:
        """
        Basic text normalization.

        Unicode characters are preserved because migration
        monitoring includes multilingual content.
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
        Performs case-insensitive literal phrase matching.

        Word-like terms use conservative boundaries to reduce
        substring false positives.

        Example:

            "asylum" matches "asylum seekers"
            but not an unrelated larger token.
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
    # SIMPLE SECTION MATCHER
    # ======================================================

    def _match_simple_section(
        self,
        *,
        normalized_text: str,
        section: Dict[str, object],
        value_key: str,
    ) -> Dict[str, object]:
        """
        Matches a flat term section.
        """

        terms = (
            section.get(
                value_key,
                [],
            )
            or []
        )

        matches: List[str] = []

        for term in terms:

            match = (
                self._contains_term(
                    normalized_text,
                    str(term),
                )
            )

            if (
                match
                and match.lower()
                not in {
                    item.lower()
                    for item in matches
                }
            ):

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
        Matches all indicator groups defined in JSON.
        """

        results = {}

        for (
            group_name,
            configuration,
        ) in self.indicator_groups.items():

            result = (
                self._match_simple_section(
                    normalized_text=text,
                    section=configuration,
                    value_key="terms",
                )
            )

            results[
                group_name
            ] = result

        return results

    # ======================================================
    # DESTINATION COUNTRIES
    # ======================================================

    def _match_destinations(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects configured destination countries.
        """

        section = (
            self.rules.get(
                "destination_countries",
                {},
            )
        )

        weight = int(
            section.get(
                "weight",
                0,
            )
            or 0
        )

        entities = []

        for country in (
            section.get(
                "countries",
                []
            )
            or []
        ):

            aliases = (
                country.get(
                    "aliases",
                    [],
                )
                or []
            )

            matched_aliases = (
                self._match_aliases(
                    text=text,
                    aliases=aliases,
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
                weight,
        }

    # ======================================================
    # ORIGIN REGIONS
    # ======================================================

    def _match_origin_regions(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects configured migration origin countries
        and maps them to origin regions.
        """

        section = (
            self.rules.get(
                "origin_regions",
                {},
            )
        )

        weight = int(
            section.get(
                "weight",
                0,
            )
            or 0
        )

        entities = []

        for region in (
            section.get(
                "regions",
                []
            )
            or []
        ):

            countries = (
                region.get(
                    "countries",
                    [],
                )
                or []
            )

            matched_countries = (
                self._match_aliases(
                    text=text,
                    aliases=countries,
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
                weight,
        }

    # ======================================================
    # CROSSING POINTS
    # ======================================================

    def _match_crossing_points(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects important migration crossing,
        departure, transit and arrival locations.
        """

        section = (
            self.rules.get(
                "crossing_points",
                {},
            )
        )

        weight = int(
            section.get(
                "weight",
                0,
            )
            or 0
        )

        entities = []

        for point in (
            section.get(
                "points",
                []
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
                weight,
        }

    # ======================================================
    # CROSSING METHODS
    # ======================================================

    def _match_crossing_methods(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects configured border crossing methods.
        """

        section = (
            self.rules.get(
                "crossing_methods",
                {},
            )
        )

        weight = int(
            section.get(
                "weight",
                0,
            )
            or 0
        )

        entities = []

        for method in (
            section.get(
                "methods",
                []
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
                weight,
        }

    # ======================================================
    # PLATFORM INDICATORS
    # ======================================================

    def _match_platforms(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects references to communication
        and social-media platforms.
        """

        section = (
            self.rules.get(
                "platform_indicators",
                {},
            )
        )

        weight = int(
            section.get(
                "weight",
                0,
            )
            or 0
        )

        entities = []

        for platform in (
            section.get(
                "platforms",
                []
            )
            or []
        ):

            aliases = (
                platform.get(
                    "aliases",
                    [],
                )
                or []
            )

            matched_aliases = (
                self._match_aliases(
                    text=text,
                    aliases=aliases,
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
                weight,
        }

    # ======================================================
    # ALIAS MATCHING
    # ======================================================

    def _match_aliases(
        self,
        *,
        text: str,
        aliases: List[str],
    ) -> List[str]:
        """
        Matches aliases and returns unique actual strings.
        """

        matches: List[str] = []

        for alias in aliases:

            match = (
                self._contains_term(
                    text,
                    str(alias),
                )
            )

            if not match:
                continue

            if (
                match.lower()
                in {
                    existing.lower()
                    for existing in matches
                }
            ):

                continue

            matches.append(
                match
            )

        return matches

    # ======================================================
    # NARRATIVES
    # ======================================================

    def _match_narratives(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects configured migration narratives.
        """

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

            result = (
                self._match_simple_section(
                    normalized_text=text,
                    section=configuration,
                    value_key="terms",
                )
            )

            results[
                narrative_name
            ] = result

        return results

    # ======================================================
    # HIGH VALUE PHRASES
    # ======================================================

    def _match_high_value_phrases(
        self,
        text: str,
    ) -> Dict[str, object]:
        """
        Detects high-value phrases configured in JSON.
        """

        section = (
            self.rules.get(
                "high_value_phrases",
                {},
            )
        )

        terms = (
            section.get(
                "terms",
                [],
            )
            or []
        )

        matches = []

        for term in terms:

            match = (
                self._contains_term(
                    text,
                    str(term),
                )
            )

            if not match:
                continue

            if (
                match.lower()
                in {
                    existing.lower()
                    for existing in matches
                }
            ):

                continue

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
        """
        Creates a normalized boolean map used by
        context and signal rules.
        """

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
        """
        Evaluates multi-indicator context patterns.

        Required groups must all match.

        Optional groups are not required but are recorded
        and can strengthen the analytical interpretation.
        """

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
        """
        Calculates total signal score.

        A category weight is counted once regardless of
        how many terms matched inside that category.

        This prevents long posts from receiving excessive
        scores simply because the same concept is repeated.
        """

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
        """
        Converts numeric score to configured severity level.
        """

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
        """
        Validates whether the detected indicators are
        sufficiently migration-related.

        Normally explicit migration context is required.

        A high-value phrase may override this requirement,
        but only if at least one additional meaningful
        migration-related indicator is present.

        This reduces false positives such as:

            "There are no police at the concert."
        """

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
        """
        Maps matched indicators to final signal categories.
        """

        signals: List[str] = []

        # --------------------------------------------------
        # SIGNAL MAPPING
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
        # CONTEXT PATTERN HINTS
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
        """
        Selects the strongest signal.

        Context-pattern result hints are preferred because
        they are based on combinations of indicators.
        """

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

            strongest_pattern_signal = max(
                pattern_scores,
                key=pattern_scores.get,
            )

            if (
                strongest_pattern_signal
                in matched_signals
            ):

                return (
                    strongest_pattern_signal
                )

        priority = [
            "RECRUITMENT_COORDINATION",
            "LEGAL_MIGRATION_SIGNAL",
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
        """
        Calculates analytical confidence from the
        configured base confidence and score level.
        """

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
    # COMPATIBILITY MATCHED PHRASES
    # ======================================================

    def _build_compatibility_phrases(
        self,
        *,
        primary_signal: Optional[str],
        indicator_results: Dict[str, object],
        narrative_results: Dict[str, object],
        high_value_result: Dict[str, object],
    ) -> List[Tuple[str, str]]:
        """
        Produces the legacy matched_phrases structure
        expected by existing logging code.
        """

        if not primary_signal:

            return []

        results: List[
            Tuple[str, str]
        ] = []

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
        """
        Returns only names of groups with at least one match.
        """

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

        # --------------------------------------------------
        # ROUTE / MOVEMENT
        # --------------------------------------------------

        (
            "Hundreds of migrants are gathering near the coast "
            "and moving toward a known crossing point. "
            "Videos of the route are circulating on Telegram."
        ),

        # --------------------------------------------------
        # LEGAL SIGNAL
        # --------------------------------------------------

        (
            "The court ruled that asylum seekers from this "
            "country cannot currently be returned."
        ),

        # --------------------------------------------------
        # POLICY SIGNAL
        # --------------------------------------------------

        (
            "Temporary protection has been extended for "
            "refugees and new residence permits will be issued."
        ),

        # --------------------------------------------------
        # COORDINATION
        # --------------------------------------------------

        (
            "Migrants can contact us on Telegram. "
            "Transport available and seats available."
        ),

        # --------------------------------------------------
        # LOCATION + MOVEMENT
        # --------------------------------------------------

        (
            "Hundreds of migrants are moving toward Calais "
            "and small boats have been seen near the coast."
        ),

        # --------------------------------------------------
        # FALSE POSITIVE CONTROL
        # --------------------------------------------------

        (
            "Come to the restaurant tonight. "
            "There are no police nearby."
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
            "Migration context:",
            result.get(
                "migration_context"
            ),
        )

        print(
            "Indicator groups:",
            result.get(
                "matched_indicator_groups"
            ),
        )

        print(
            "Narratives:",
            result.get(
                "matched_narratives"
            ),
        )

        print(
            "Crossing points:",
            result.get(
                "matched_crossing_points"
            ),
        )

        print(
            "Crossing methods:",
            result.get(
                "matched_crossing_methods"
            ),
        )

        print(
            "Platforms:",
            result.get(
                "matched_platforms"
            ),
        )

        print(
            "Context patterns:",
            result.get(
                "matched_context_patterns"
            ),
        )

        print(
            "High-value:",
            result.get(
                "high_value_match"
            ),
        )
