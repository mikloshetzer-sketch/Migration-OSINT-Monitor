"""
Migration OSINT Monitor

File:
event_correlator.py

Description:
Event Correlator V3.

Correlates normalized migration events that likely refer to the same
real-world operational event.

V3 correlation uses:
- event type
- primary / matched region overlap
- location overlap
- time proximity
- numeric fact overlap
- important entity overlap
- text similarity

Region information is now a first-class correlation signal.
"""

import re

from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set


class EventCorrelator:
    """
    Performs weighted multi-factor correlation between operational events.
    """

    EVENT_TYPE_WEIGHT = 0.30
    REGION_WEIGHT = 0.20
    LOCATION_WEIGHT = 0.15
    TIME_WEIGHT = 0.15
    NUMBER_WEIGHT = 0.10
    ENTITY_WEIGHT = 0.05
    TEXT_WEIGHT = 0.05

    DEFAULT_SIMILARITY_THRESHOLD = 0.55
    DEFAULT_MAX_TIME_DIFFERENCE_HOURS = 72

    GENERIC_TERMS = {
        "migrant",
        "migrants",
        "migration",
        "refugee",
        "refugees",
        "asylum",
        "illegal",
        "irregular",
        "border",
        "borders",
        "crossing",
        "crossings",
        "smuggling",
        "smuggler",
        "smugglers",
        "network",
        "networks",
        "police",
        "operation",
        "operations",
        "people",
        "person",
        "persons",
        "authorities",
        "government",
        "official",
        "officials",
        "country",
        "countries",
        "arrived",
        "arrival",
        "departed",
        "departure",
        "boat",
        "boats",
        "vessel",
        "vessels",
        "arrested",
        "detained",
        "rescued",
        "intercepted",
        "trafficking",
    }

    STOP_WORDS = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "have",
        "has",
        "had",
        "was",
        "were",
        "are",
        "is",
        "been",
        "being",
        "their",
        "they",
        "them",
        "after",
        "before",
        "about",
        "against",
        "over",
        "under",
        "through",
        "across",
        "between",
        "within",
        "would",
        "could",
        "should",
        "will",
        "more",
        "most",
        "some",
        "what",
        "when",
        "where",
        "which",
        "while",
        "than",
        "then",
        "also",
        "says",
        "said",
        "report",
        "reports",
        "reported",
        "according",
    }

    def __init__(
        self,
        *,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        max_time_difference_hours: int = DEFAULT_MAX_TIME_DIFFERENCE_HOURS,
    ):
        self.similarity_threshold = similarity_threshold
        self.max_time_difference_hours = max_time_difference_hours

    def find_match(
        self,
        new_event: Dict[str, Any],
        existing_events: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the strongest matching existing event.
        """

        best_match = None
        best_score = 0.0
        best_details = None

        for existing_event in existing_events:
            result = self.calculate_similarity_details(
                new_event,
                existing_event,
            )

            score = result["score"]

            if score > best_score:
                best_score = score
                best_match = existing_event
                best_details = result

        if best_match is None:
            return None

        if best_score < self.similarity_threshold:
            return None

        if not self._has_minimum_correlation_evidence(
            new_event,
            best_match,
            best_details,
        ):
            return None

        return {
            "event": best_match,
            "correlation_score": round(best_score, 2),
            "correlation_details": best_details,
        }

    def calculate_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Compatibility method returning only the final score.
        """

        result = self.calculate_similarity_details(
            event_a,
            event_b,
        )

        return result["score"]

    def calculate_similarity_details(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Calculates weighted similarity and exposes component scores.
        """

        event_type_score = self._event_type_similarity(
            event_a,
            event_b,
        )

        region_score = self._region_similarity(
            event_a,
            event_b,
        )

        location_score = self._location_similarity(
            event_a,
            event_b,
        )

        time_score = self._time_similarity(
            event_a,
            event_b,
        )

        number_score = self._number_similarity(
            event_a,
            event_b,
        )

        entity_score = self._entity_similarity(
            event_a,
            event_b,
        )

        text_score = self._text_similarity(
            event_a.get("text", ""),
            event_b.get("text", ""),
        )

        weighted_score = (
            event_type_score * self.EVENT_TYPE_WEIGHT
            + region_score * self.REGION_WEIGHT
            + location_score * self.LOCATION_WEIGHT
            + time_score * self.TIME_WEIGHT
            + number_score * self.NUMBER_WEIGHT
            + entity_score * self.ENTITY_WEIGHT
            + text_score * self.TEXT_WEIGHT
        )

        return {
            "score": round(
                min(weighted_score, 1.0),
                4,
            ),
            "event_type_score": round(
                event_type_score,
                3,
            ),
            "region_score": round(
                region_score,
                3,
            ),
            "location_score": round(
                location_score,
                3,
            ),
            "time_score": round(
                time_score,
                3,
            ),
            "number_score": round(
                number_score,
                3,
            ),
            "entity_score": round(
                entity_score,
                3,
            ),
            "text_score": round(
                text_score,
                3,
            ),
            "shared_regions": sorted(
                self._extract_regions(event_a).intersection(
                    self._extract_regions(event_b)
                )
            ),
            "shared_numbers": sorted(
                self._extract_numbers(
                    event_a.get("text", "")
                ).intersection(
                    self._extract_numbers(
                        event_b.get("text", "")
                    )
                )
            ),
            "shared_entities": sorted(
                self._extract_entities(
                    event_a
                ).intersection(
                    self._extract_entities(
                        event_b
                    )
                )
            ),
            "shared_locations": sorted(
                self._extract_location_names(
                    event_a
                ).intersection(
                    self._extract_location_names(
                        event_b
                    )
                )
            ),
        }

    def _event_type_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Scores similarity of primary and secondary event signals.
        """

        type_a = event_a.get("event_type")
        type_b = event_b.get("event_type")

        if type_a and type_b and type_a == type_b:
            return 1.0

        signals_a = set(
            event_a.get("matched_signals") or []
        )

        signals_b = set(
            event_b.get("matched_signals") or []
        )

        if not signals_a or not signals_b:
            return 0.0

        intersection = signals_a.intersection(
            signals_b
        )

        if not intersection:
            return 0.0

        union = signals_a.union(
            signals_b
        )

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _region_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Scores geographic region similarity.

        Primary region equality receives the strongest score.
        Matched region overlap receives partial credit.
        GLOBAL is not treated as meaningful geographic evidence.
        """

        primary_a = event_a.get("primary_region")
        primary_b = event_b.get("primary_region")

        if (
            primary_a
            and primary_b
            and primary_a != "GLOBAL"
            and primary_a == primary_b
        ):
            return 1.0

        regions_a = self._extract_regions(
            event_a
        )

        regions_b = self._extract_regions(
            event_b
        )

        if not regions_a or not regions_b:
            return 0.0

        intersection = regions_a.intersection(
            regions_b
        )

        if not intersection:
            return 0.0

        union = regions_a.union(
            regions_b
        )

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _extract_regions(
        self,
        event: Dict[str, Any],
    ) -> Set[str]:
        """
        Extracts meaningful normalized regions from an event.
        """

        regions = set()

        primary_region = event.get(
            "primary_region"
        )

        if (
            primary_region
            and primary_region != "GLOBAL"
        ):
            regions.add(
                str(primary_region).strip()
            )

        matched_regions = event.get(
            "matched_regions"
        ) or []

        for region in matched_regions:
            if not region:
                continue

            region = str(region).strip()

            if region == "GLOBAL":
                continue

            regions.add(region)

        return regions

    def _location_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Scores overlap between detected locations.
        """

        locations_a = self._extract_location_names(
            event_a
        )

        locations_b = self._extract_location_names(
            event_b
        )

        if not locations_a or not locations_b:
            return 0.0

        intersection = locations_a.intersection(
            locations_b
        )

        if not intersection:
            return 0.0

        union = locations_a.union(
            locations_b
        )

        return len(intersection) / len(union)

    def _time_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Scores temporal proximity.
        """

        time_a = self._get_event_datetime(
            event_a
        )

        time_b = self._get_event_datetime(
            event_b
        )

        if time_a is None or time_b is None:
            return 0.0

        difference_hours = abs(
            (
                time_a - time_b
            ).total_seconds()
        ) / 3600

        if difference_hours <= 1:
            return 1.0

        if difference_hours <= 6:
            return 0.9

        if difference_hours <= 12:
            return 0.8

        if difference_hours <= 24:
            return 0.7

        if difference_hours <= 48:
            return 0.5

        if (
            difference_hours
            <= self.max_time_difference_hours
        ):
            return 0.3

        return 0.0

    def _number_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Compares significant numeric facts.
        """

        numbers_a = self._extract_numbers(
            event_a.get("text", "")
        )

        numbers_b = self._extract_numbers(
            event_b.get("text", "")
        )

        if not numbers_a or not numbers_b:
            return 0.0

        intersection = numbers_a.intersection(
            numbers_b
        )

        if not intersection:
            return 0.0

        union = numbers_a.union(
            numbers_b
        )

        if not union:
            return 0.0

        jaccard = (
            len(intersection)
            / len(union)
        )

        if len(intersection) >= 3:
            return min(
                1.0,
                jaccard + 0.35,
            )

        if len(intersection) == 2:
            return min(
                1.0,
                jaccard + 0.25,
            )

        return min(
            1.0,
            jaccard + 0.15,
        )

    def _entity_similarity(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
    ) -> float:
        """
        Compares lightweight event-specific entity terms.
        """

        entities_a = self._extract_entities(
            event_a
        )

        entities_b = self._extract_entities(
            event_b
        )

        if not entities_a or not entities_b:
            return 0.0

        intersection = entities_a.intersection(
            entities_b
        )

        if not intersection:
            return 0.0

        union = entities_a.union(
            entities_b
        )

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _extract_numbers(
        self,
        text: str,
    ) -> Set[str]:
        """
        Extracts potentially meaningful numeric facts.
        """

        if not text:
            return set()

        raw_numbers = re.findall(
            r"\b\d[\d,.]*\b",
            str(text),
        )

        numbers = set()

        for raw_value in raw_numbers:
            normalized = (
                raw_value
                .replace(",", "")
                .replace(".", "")
            )

            if not normalized.isdigit():
                continue

            try:
                numeric_value = int(
                    normalized
                )
            except ValueError:
                continue

            if numeric_value < 2:
                continue

            if 1900 <= numeric_value <= 2100:
                continue

            numbers.add(
                str(numeric_value)
            )

        return numbers

    def _extract_entities(
        self,
        event: Dict[str, Any],
    ) -> Set[str]:
        """
        Extracts lightweight event-specific entity terms.
        """

        entities = set()

        entities.update(
            self._extract_location_names(
                event
            )
        )

        text = str(
            event.get("text", "")
        )

        words = re.findall(
            r"\b[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]{2,}\b",
            text,
        )

        for word in words:
            normalized = (
                word.lower().strip()
            )

            if normalized in self.STOP_WORDS:
                continue

            if normalized in self.GENERIC_TERMS:
                continue

            if len(normalized) < 4:
                continue

            entities.add(normalized)

        return entities

    def _extract_location_names(
        self,
        event: Dict[str, Any],
    ) -> Set[str]:
        """
        Returns normalized detected location names and countries.
        """

        names = set()

        locations = event.get(
            "locations"
        ) or []

        for location in locations:
            name = location.get("name")
            country = location.get("country")

            if name:
                names.add(
                    str(name)
                    .strip()
                    .lower()
                )

            if country:
                names.add(
                    str(country)
                    .strip()
                    .lower()
                )

        primary_location = event.get(
            "primary_location"
        )

        if primary_location:
            name = primary_location.get(
                "name"
            )

            country = primary_location.get(
                "country"
            )

            if name:
                names.add(
                    str(name)
                    .strip()
                    .lower()
                )

            if country:
                names.add(
                    str(country)
                    .strip()
                    .lower()
                )

        matched_countries = event.get(
            "matched_countries"
        ) or []

        for country in matched_countries:
            if country:
                names.add(
                    str(country)
                    .strip()
                    .lower()
                )

        return names

    def _text_similarity(
        self,
        text_a: str,
        text_b: str,
    ) -> float:
        """
        Calculates normalized textual similarity.
        """

        normalized_a = self._normalize_text(
            text_a
        )

        normalized_b = self._normalize_text(
            text_b
        )

        if not normalized_a or not normalized_b:
            return 0.0

        return SequenceMatcher(
            None,
            normalized_a,
            normalized_b,
        ).ratio()

    def _normalize_text(
        self,
        text: str,
    ) -> str:
        """
        Normalizes text before similarity comparison.
        """

        text = str(text).lower()

        text = re.sub(
            r"https?://\S+",
            " ",
            text,
        )

        text = re.sub(
            r"@\w+",
            " ",
            text,
        )

        text = re.sub(
            r"#",
            "",
            text,
        )

        text = re.sub(
            r"[^a-z0-9à-ÿ\s]",
            " ",
            text,
        )

        return " ".join(
            text.split()
        )

    def _get_event_datetime(
        self,
        event: Dict[str, Any],
    ) -> Optional[datetime]:
        """
        Uses normalized event time when available,
        otherwise publication time.
        """

        candidates = [
            event.get(
                "event_time_normalized"
            ),
            event.get(
                "published_at"
            ),
        ]

        for value in candidates:
            parsed = self._parse_datetime(
                value
            )

            if parsed is not None:
                return parsed

        return None

    def _parse_datetime(
        self,
        value,
    ) -> Optional[datetime]:
        """
        Parses datetime objects or ISO timestamp strings.
        """

        if not value:
            return None

        if isinstance(
            value,
            datetime,
        ):
            parsed = value

        else:
            try:
                parsed = datetime.fromisoformat(
                    str(value).replace(
                        "Z",
                        "+00:00",
                    )
                )

            except ValueError:
                return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed

    def _has_minimum_correlation_evidence(
        self,
        event_a: Dict[str, Any],
        event_b: Dict[str, Any],
        details: Dict[str, Any],
    ) -> bool:
        """
        Prevents weak false correlations.

        Matching event type alone is never sufficient.

        At least one strong event-specific indicator must also match.
        """

        if details is None:
            return False

        if (
            details.get(
                "event_type_score",
                0.0,
            )
            <= 0
        ):
            return False

        region_match = (
            details.get(
                "region_score",
                0.0,
            )
            >= 0.5
        )

        location_match = (
            details.get(
                "location_score",
                0.0,
            )
            > 0
        )

        number_match = (
            details.get(
                "number_score",
                0.0,
            )
            > 0
        )

        entity_match = (
            details.get(
                "entity_score",
                0.0,
            )
            >= 0.15
        )

        strong_text_match = (
            details.get(
                "text_score",
                0.0,
            )
            >= 0.45
        )

        return any(
            [
                region_match,
                location_match,
                number_match,
                entity_match,
                strong_text_match,
            ]
        )
