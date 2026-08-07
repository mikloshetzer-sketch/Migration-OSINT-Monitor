"""
Migration OSINT Monitor

File:
region_resolver.py

Description:
Resolves normalized migration events to configured geographic regions
using detected locations, countries, and explicit regional mentions.
"""

import json
import re

from pathlib import Path
from typing import Any, Dict, List, Optional, Set


class RegionResolver:
    """
    Resolves events to one or more configured migration regions.
    """

    def __init__(
        self,
        regions_file: str = "config/regions.json",
    ):
        self.regions_file = Path(regions_file)
        self.regions = self._load_regions()

    def resolve(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Resolves an event to matching regions.

        Returns:
            {
                "primary_region": str | None,
                "matched_regions": list[str],
                "region_names": list[str],
                "matched_countries": list[str],
                "matched_region_terms": list[str],
                "confidence": float
            }
        """

        detected_countries = self._extract_event_countries(event)
        explicit_region_terms = self._extract_explicit_region_terms(event)

        matched_regions: List[str] = []
        matched_countries: Set[str] = set()
        matched_region_terms: Set[str] = set()

        for region_id, region_data in self.regions.items():
            if region_id == "GLOBAL":
                continue

            region_countries = {
                str(country).strip().lower()
                for country in region_data.get("countries", [])
            }

            country_overlap = detected_countries.intersection(
                region_countries
            )

            region_term_match = self._region_term_matches(
                event=event,
                region_id=region_id,
                region_data=region_data,
            )

            if country_overlap or region_term_match:
                matched_regions.append(region_id)

                matched_countries.update(country_overlap)

                if region_term_match:
                    matched_region_terms.add(
                        region_data.get("name", region_id)
                    )

        primary_region = self._select_primary_region(
            matched_regions
        )

        confidence = self._calculate_confidence(
            matched_regions=matched_regions,
            matched_countries=matched_countries,
            matched_region_terms=matched_region_terms,
        )

        region_names = [
            self.regions[region_id].get(
                "name",
                region_id,
            )
            for region_id in matched_regions
            if region_id in self.regions
        ]

        if not matched_regions:
            matched_regions = ["GLOBAL"]
            region_names = [
                self.regions.get(
                    "GLOBAL",
                    {},
                ).get(
                    "name",
                    "Global",
                )
            ]

            if primary_region is None:
                primary_region = "GLOBAL"

        return {
            "primary_region": primary_region,
            "matched_regions": matched_regions,
            "region_names": region_names,
            "matched_countries": sorted(matched_countries),
            "matched_region_terms": sorted(matched_region_terms),
            "confidence": confidence,
        }

    def _load_regions(self) -> Dict[str, Dict[str, Any]]:
        """
        Loads region configuration from JSON.
        """

        if not self.regions_file.exists():
            return {}

        with open(
            self.regions_file,
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    def _extract_event_countries(
        self,
        event: Dict[str, Any],
    ) -> Set[str]:
        """
        Extracts normalized country names from event locations.
        """

        countries = set()

        locations = event.get("locations") or []

        for location in locations:
            country = location.get("country")

            if country:
                countries.add(
                    str(country).strip().lower()
                )

        primary_location = event.get(
            "primary_location"
        )

        if primary_location:
            country = primary_location.get("country")

            if country:
                countries.add(
                    str(country).strip().lower()
                )

        text = str(
            event.get("text", "")
        ).lower()

        for region_data in self.regions.values():
            for country in region_data.get("countries", []):
                country_name = str(country).strip()

                pattern = (
                    r"\b"
                    + re.escape(country_name.lower())
                    + r"\b"
                )

                if re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                ):
                    countries.add(
                        country_name.lower()
                    )

        return countries

    def _extract_explicit_region_terms(
        self,
        event: Dict[str, Any],
    ) -> Set[str]:
        """
        Extracts explicitly mentioned configured region names.
        """

        matched_terms = set()

        text = str(
            event.get("text", "")
        )

        for region_id, region_data in self.regions.items():
            if region_id == "GLOBAL":
                continue

            name = region_data.get("name")

            if not name:
                continue

            pattern = (
                r"\b"
                + re.escape(str(name))
                + r"\b"
            )

            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                matched_terms.add(
                    str(name)
                )

        return matched_terms

    def _region_term_matches(
        self,
        *,
        event: Dict[str, Any],
        region_id: str,
        region_data: Dict[str, Any],
    ) -> bool:
        """
        Checks whether a region name or common regional variant
        appears explicitly in the event text.
        """

        text = str(
            event.get("text", "")
        )

        terms = set()

        region_name = region_data.get("name")

        if region_name:
            terms.add(str(region_name))

        aliases = self._get_region_aliases(
            region_id
        )

        terms.update(aliases)

        for term in terms:
            pattern = (
                r"\b"
                + re.escape(term)
                + r"\b"
            )

            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                return True

        return False

    def _get_region_aliases(
        self,
        region_id: str,
    ) -> Set[str]:
        """
        Returns common aliases for configured regions.
        """

        aliases = {
            "WESTERN_MEDITERRANEAN": {
                "western mediterranean",
                "west mediterranean",
                "western med",
            },
            "CENTRAL_MEDITERRANEAN": {
                "central mediterranean",
                "central med",
            },
            "EASTERN_MEDITERRANEAN": {
                "eastern mediterranean",
                "east mediterranean",
                "eastern med",
            },
            "WESTERN_BALKANS": {
                "western balkans",
                "balkan route",
                "western balkan route",
            },
            "EASTERN_EU_BORDER": {
                "eastern eu border",
                "eastern border",
                "eu eastern border",
            },
            "BLACK_SEA": {
                "black sea",
            },
            "CAUCASUS": {
                "caucasus",
                "south caucasus",
            },
            "MIDDLE_EAST": {
                "middle east",
            },
            "HORN_OF_AFRICA": {
                "horn of africa",
            },
            "SAHEL": {
                "sahel",
            },
            "AMERICAS": {
                "americas",
                "central america",
                "north america",
                "south america",
            },
            "ASIA_PACIFIC": {
                "asia pacific",
                "asia-pacific",
            },
        }

        return aliases.get(
            region_id,
            set(),
        )

    def _select_primary_region(
        self,
        matched_regions: List[str],
    ) -> Optional[str]:
        """
        Selects the highest-priority configured region.
        """

        if not matched_regions:
            return None

        ranked_regions = sorted(
            matched_regions,
            key=lambda region_id: self.regions.get(
                region_id,
                {},
            ).get(
                "priority",
                999,
            ),
        )

        return ranked_regions[0]

    def _calculate_confidence(
        self,
        *,
        matched_regions: List[str],
        matched_countries: Set[str],
        matched_region_terms: Set[str],
    ) -> float:
        """
        Calculates region resolution confidence.
        """

        if not matched_regions:
            return 0.20

        confidence = 0.45

        if matched_countries:
            confidence += 0.25

        if len(matched_countries) >= 2:
            confidence += 0.10

        if matched_region_terms:
            confidence += 0.15

        if len(matched_regions) == 1:
            confidence += 0.05

        return round(
            min(confidence, 0.95),
            2,
        )
