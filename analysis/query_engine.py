"""
Migration OSINT Monitor

File:
query_engine.py

Description:
Loads query definitions from configuration files and provides
platform-independent access to migration monitoring topics.
"""

import json
from pathlib import Path
from typing import Dict, List


class QueryEngine:
    """
    Loads all enabled query configuration files.
    """

    def __init__(self, query_directory: str = "config/queries"):
        self.query_directory = Path(query_directory)

    def load_queries(self) -> List[Dict]:
        """
        Loads every enabled query configuration.

        Returns:
            List of query definitions.
        """

        query_list: List[Dict] = []

        if not self.query_directory.exists():
            return query_list

        for file in sorted(self.query_directory.glob("*.json")):

            with open(file, "r", encoding="utf-8") as f:
                config = json.load(f)

            if not config.get("enabled", False):
                continue

            for query in config.get("queries", []):

                query["query_group"] = config.get(
                    "name",
                    file.stem,
                )

                query_list.append(query)

        return query_list

    def get_query_count(self) -> int:
        """
        Returns the number of enabled queries.
        """

        return len(self.load_queries())

    def get_query_ids(self) -> List[str]:
        """
        Returns every query identifier.
        """

        return [
            query["id"]
            for query in self.load_queries()
        ]
