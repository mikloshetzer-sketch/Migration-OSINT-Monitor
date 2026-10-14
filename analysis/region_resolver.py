"""Migration OSINT Monitor: multilingual, evidence-weighted region resolution.

Drop-in replacement for region_resolver.py. Keeps the original resolve() output
contract and the existing config/regions.json region taxonomy unchanged.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class RegionResolver:
    # Aliases are used only when the canonical country exists in regions.json.
    COUNTRY_ALIASES = {
        "Russia": ("россия", "россии", "россию", "российской", "rossiya", "rusia", "russie", "россияда", "россиядан"),
        "Morocco": ("maroc", "marruecos", "المغرب", "marokko"),
        "Spain": ("espana", "españa", "espagne", "إسبانيا"),
        "Djibouti": ("جيبوتي", "djibuti", "djiboutí"),
        "Yemen": ("اليمن",),
        "Greece": ("ελλάδα", "grecia", "grèce", "اليونان"),
        "Italy": ("italia", "italie", "إيطاليا"),
        "Libya": ("libia", "libye", "ليبيا"),
        "Tunisia": ("tunisie", "túnez", "تونس"),
        "Poland": ("polska", "polonia", "польша", "بولندا"),
        "Germany": ("deutschland", "alemania", "allemagne", "германия"),
        "Turkey": ("türkiye", "turquía", "turquie", "تركيا"),
        "Serbia": ("srbija", "сербия", "srbije"),
        "Hungary": ("magyarország", "hongrie", "hungría", "венгрия"),
        "Ukraine": ("украина", "україна", "ucrania", "أوكرانيا"),
        "Belarus": ("беларусь", "белоруссия", "bielorrusia"),
        "Romania": ("românia", "rumanía", "румыния"),
        "Sudan": ("السودان", "soudan"),
        "Ethiopia": ("إثيوبيا", "ethiopie", "etiopía"),
        "Somalia": ("الصومال", "somalie"),
        "United States": ("usa", "u.s.a.", "estados unidos", "états-unis", "сша", "الولايات المتحدة"),
    }

    # High-specificity locations. Generic words such as "border" are excluded.
    # Every city maps to a country, not directly to a region.
    CITY_COUNTRIES = {
        "Russia": ("москва", "москве", "москвы", "moscow", "moskva", "москвада", "котельники", "котельникида", "kotelniki"),
        "Spain": ("ceuta", "melilla", "сеута", "سبتة", "مليلية"),
        "Morocco": ("fnideq", "الفنيدق", "tétouan", "tetouan", "تطوان", "tanger", "tangier", "طنجة"),
        "Djibouti": ("djibouti city", "ville de djibouti", "مدينة جيبوتي"),
        "Greece": ("crete", "κρήτη", "creta", "kaloi limenes", "treis ekklisies"),
        "Italy": ("lampedusa", "lampедуза", "sicilia", "sicily"),
        "Poland": ("warsaw", "warszawa", "варшава"),
        "Libya": ("tripoli libya", "طرابلس ليبيا", "benghazi", "بنغازي"),
    }

    REGION_ALIASES = {
        "WESTERN_MEDITERRANEAN": ("western mediterranean", "west mediterranean", "western med", "mediterráneo occidental", "méditerranée occidentale"),
        "CENTRAL_MEDITERRANEAN": ("central mediterranean", "central med", "mediterráneo central", "méditerranée centrale"),
        "EASTERN_MEDITERRANEAN": ("eastern mediterranean", "east mediterranean", "eastern med", "mediterráneo oriental"),
        "WESTERN_BALKANS": ("western balkans", "balkan route", "western balkan route", "balcanes occidentales"),
        "EASTERN_EU_BORDER": ("eastern eu border", "eu eastern border"),
        "BLACK_SEA": ("black sea", "черное море", "чёрное море", "mar negro"),
        "CAUCASUS": ("caucasus", "south caucasus", "кавказ"),
        "MIDDLE_EAST": ("middle east", "medio oriente", "الشرق الأوسط"),
        "HORN_OF_AFRICA": ("horn of africa", "cuerno de áfrica", "القرن الأفريقي"),
        "SAHEL": ("sahel", "الساحل الأفريقي"),
        "AMERICAS": ("americas", "central america", "north america", "south america"),
        "ASIA_PACIFIC": ("asia pacific", "asia-pacific"),
    }

    def __init__(self, regions_file: str = "config/regions.json"):
        self.regions_file = Path(regions_file)
        self.regions = self._load_regions()
        self._country_lookup = {
            str(c).casefold(): str(c)
            for region in self.regions.values()
            for c in region.get("countries", [])
        }

    @staticmethod
    def _normalize(text: Any) -> str:
        return unicodedata.normalize("NFKC", str(text or "")).casefold()

    @classmethod
    def _contains(cls, text: str, term: str) -> bool:
        term = cls._normalize(term).strip()
        if not term:
            return False
        return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.UNICODE))

    def _load_regions(self) -> Dict[str, Dict[str, Any]]:
        if not self.regions_file.exists():
            return {}
        with self.regions_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("regions.json must contain an object")
        return data

    def _canonical_country(self, value: Any) -> Optional[str]:
        key = self._normalize(value).strip()
        if key in self._country_lookup:
            return self._country_lookup[key]
        for canonical, aliases in self.COUNTRY_ALIASES.items():
            if canonical.casefold() in self._country_lookup and key in [self._normalize(x) for x in aliases]:
                return self._country_lookup[canonical.casefold()]
        return None

    def _structured_countries(self, event: Dict[str, Any]) -> Set[str]:
        result: Set[str] = set()
        locations = event.get("locations") or []
        if isinstance(locations, dict):
            locations = [locations]
        primary = event.get("primary_location")
        if isinstance(primary, dict):
            locations = [primary] + list(locations)
        for location in locations:
            if not isinstance(location, dict):
                continue
            country = self._canonical_country(location.get("country"))
            if country:
                result.add(country)
        return result

    def _text_country_evidence(self, text: str) -> Tuple[Set[str], Set[str]]:
        countries: Set[str] = set()
        cities: Set[str] = set()
        for canonical in self._country_lookup.values():
            aliases = (canonical,) + self.COUNTRY_ALIASES.get(canonical, ())
            if any(self._contains(text, alias) for alias in aliases):
                countries.add(canonical)
        for canonical, aliases in self.CITY_COUNTRIES.items():
            if canonical.casefold() not in self._country_lookup:
                continue
            if any(self._contains(text, alias) for alias in aliases):
                cities.add(self._country_lookup[canonical.casefold()])
        return countries, cities

    def _explicit_regions(self, text: str) -> Set[str]:
        found = set()
        for region_id, region_data in self.regions.items():
            if region_id == "GLOBAL":
                continue
            aliases = (region_data.get("name", ""),) + self.REGION_ALIASES.get(region_id, ())
            if any(self._contains(text, alias) for alias in aliases):
                found.add(region_id)
        return found

    def resolve(self, event: Dict[str, Any]) -> Dict[str, Any]:
        text = self._normalize(event.get("text", ""))
        structured = self._structured_countries(event)
        mentioned, cities = self._text_country_evidence(text)
        explicit = self._explicit_regions(text)
        detected = structured | mentioned | cities

        region_scores: Dict[str, int] = {}
        region_countries: Dict[str, Set[str]] = {}
        for region_id, region_data in self.regions.items():
            if region_id == "GLOBAL":
                continue
            configured = {self._normalize(c) for c in region_data.get("countries", [])}
            overlap = {c for c in detected if self._normalize(c) in configured}
            score = (5 if region_id in explicit else 0)
            score += 7 * len([c for c in structured if c in overlap])
            score += 4 * len([c for c in cities if c in overlap])
            score += 2 * len([c for c in mentioned if c in overlap])
            if score:
                region_scores[region_id] = score
                region_countries[region_id] = overlap

        if not region_scores:
            return {
                "primary_region": "GLOBAL", "matched_regions": ["GLOBAL"],
                "region_names": [self.regions.get("GLOBAL", {}).get("name", "Global")],
                "matched_countries": [], "matched_region_terms": [], "confidence": 0.20,
            }

        # Prefer specific structured location, then city, then explicit region,
        # then generic country mention. Existing config priority breaks ties.
        def rank(region_id: str):
            return (-region_scores[region_id], self.regions[region_id].get("priority", 999), region_id)

        matched = sorted(region_scores, key=rank)
        primary = matched[0]
        primary_countries = region_countries.get(primary, set())
        confidence = 0.45
        if primary_countries:
            confidence += 0.15
        if structured & primary_countries:
            confidence += 0.20
        elif cities & primary_countries:
            confidence += 0.15
        if primary in explicit:
            confidence += 0.10
        if len(matched) == 1:
            confidence += 0.05
        return {
            "primary_region": primary,
            "matched_regions": matched,
            "region_names": [self.regions[r].get("name", r) for r in matched],
            "matched_countries": sorted({c.casefold() for c in detected if any(c in region_countries[r] for r in matched)}),
            "matched_region_terms": sorted({self.regions[r].get("name", r) for r in explicit if r in matched}),
            "confidence": round(min(confidence, 0.95), 2),
        }

    # Preserve methods that other modules or tests may call.
    def _extract_event_countries(self, event: Dict[str, Any]) -> Set[str]:
        text = self._normalize(event.get("text", ""))
        mentioned, cities = self._text_country_evidence(text)
        return {c.casefold() for c in self._structured_countries(event) | mentioned | cities}

    def _extract_explicit_region_terms(self, event: Dict[str, Any]) -> Set[str]:
        return {self.regions[r].get("name", r) for r in self._explicit_regions(self._normalize(event.get("text", "")))}

    def _region_term_matches(self, *, event: Dict[str, Any], region_id: str, region_data: Dict[str, Any]) -> bool:
        return region_id in self._explicit_regions(self._normalize(event.get("text", "")))

    def _get_region_aliases(self, region_id: str) -> Set[str]:
        return set(self.REGION_ALIASES.get(region_id, ()))

    def _select_primary_region(self, matched_regions: List[str]) -> Optional[str]:
        if not matched_regions:
            return None
        return sorted(matched_regions, key=lambda r: (self.regions.get(r, {}).get("priority", 999), r))[0]

    def _calculate_confidence(self, *, matched_regions: List[str], matched_countries: Set[str], matched_region_terms: Set[str]) -> float:
        if not matched_regions:
            return 0.20
        confidence = 0.45 + (0.25 if matched_countries else 0) + (0.10 if len(matched_countries) >= 2 else 0) + (0.15 if matched_region_terms else 0) + (0.05 if len(matched_regions) == 1 else 0)
        return round(min(confidence, 0.95), 2)
