"""
Migration OSINT Monitor

File:
keyword_filter.py

Description:
Loads migration keywords and checks whether a text contains any configured keywords.
"""

import json
from pathlib import Path


class KeywordFilter:
    def __init__(self):
        config_dir = Path(__file__).resolve().parent.parent / "config"
        keywords_file = config_dir / "keywords.json"

        with open(keywords_file, "r", encoding="utf-8") as file:
            self.keywords = json.load(file)

    def contains_migration_keyword(self, text: str) -> bool:
        """
        Returns True if the text contains at least one migration keyword.
        """
        if not text:
            return False

        text = text.lower()

        for keyword in self.keywords.get("migration", []):
            if keyword.lower() in text:
                return True

        return False
