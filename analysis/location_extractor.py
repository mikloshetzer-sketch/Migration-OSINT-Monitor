"""
Migration OSINT Monitor

File:
location_extractor.py

Description:
Extracts configured geographic locations from text.
"""

import json
from pathlib import Path
from typing import List, Dict


class LocationExtractor:
    def __init__(self):
        config_dir = Path(__file__).resolve().parent.parent / "config"
        locations_file = config_dir / "locations.json"

        with open(locations_file, "r", encoding="utf-8") as file:
            self.locations = json.load(file)

    def extract_locations(self, text: str) -> List[Dict]:
        """
        Returns all configured locations found in the given text.
        """
        if not text:
            return []

        text_lower = text.lower()
        found_locations = []

        for location in self.locations:
            aliases = location.get("aliases", [])

            for alias in aliases:
                if alias.lower() in text_lower:
                    found_locations.append(location)
                    break

        return found_locations
