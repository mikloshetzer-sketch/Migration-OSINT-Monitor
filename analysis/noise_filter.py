"""
Migration OSINT Monitor

File:
noise_filter.py

Description:
Filters out common non-migration uses of migration-related keywords,
such as software, blockchain, genetics, historical population movement,
and other irrelevant contexts.
"""

import re
from typing import Dict, List


class NoiseFilter:
    """
    Detects common false-positive contexts in migration-related posts.
    """

    NOISE_PATTERNS = {
        "TECH_SOFTWARE": [
            r"\bdatabase migration\b",
            r"\bschema migration\b",
            r"\bserver migration\b",
            r"\bcloud migration\b",
            r"\bdata migration\b",
            r"\bsystem migration\b",
            r"\bmigrate to\b.*\bserver\b",
            r"\bmigration script\b",
            r"\bmigration tool\b",
        ],
        "BLOCKCHAIN_CRYPTO": [
            r"\btoken migration\b",
            r"\bwallet migration\b",
            r"\bchain migration\b",
            r"\bblockchain migration\b",
            r"\bmigration event\b.*\btoken\b",
            r"\bmigration pump\b",
            r"\bmigrated\b.*\bwallet\b",
            r"\bmigrated\b.*\bzec\b",
            r"\bsolana\b",
            r"\bethereum\b",
            r"\bcrypto\b",
            r"\btxn hash\b",
            r"\bmarket cap\b",
        ],
        "GENETICS_BIOLOGY": [
            r"\bmtDNA\b",
            r"\by-dna\b",
            r"\bhaplogroup\b",
            r"\bgenetic migration\b",
            r"\bpopulation genetics\b",
            r"\bfounder clade\b",
            r"\blineage\b.*\bmigration\b",
            r"\bout-of-africa migration\b",
        ],
        "ANIMAL_MIGRATION": [
            r"\bbird migration\b",
            r"\banimal migration\b",
            r"\bwhale migration\b",
            r"\bseasonal migration\b",
            r"\bmigratory birds\b",
            r"\bmigration season\b.*\bbirds?\b",
        ],
        "HISTORICAL_CONTEXT": [
            r"\bancient migration\b",
            r"\bhistorical migration\b",
            r"\bprehistoric migration\b",
            r"\bmigration of peoples\b",
            r"\bcenturies ago\b.*\bmigration\b",
            r"\bpopulation movement\b.*\bcentury\b",
        ],
    }

    HUMAN_MIGRATION_ANCHORS = [
        r"\bmigrant\b",
        r"\bmigrants\b",
        r"\brefugee\b",
        r"\brefugees\b",
        r"\basylum\b",
        r"\billegal migration\b",
        r"\birregular migration\b",
        r"\billegal immigrant\b",
        r"\billegal immigrants\b",
        r"\bimmigrant\b",
        r"\bimmigrants\b",
        r"\bpeople smuggler\b",
        r"\bpeople smugglers\b",
        r"\bmigrant smuggling\b",
        r"\bborder crossing\b",
        r"\bsmall boat\b",
        r"\bdinghy\b",
        r"\bcoast guard\b",
        r"\bfrontex\b",
    ]

    def analyze(self, text: str) -> Dict[str, object]:
        """
        Determines whether a post is likely noise.

        Returns:
            {
                "is_noise": bool,
                "noise_categories": [...],
                "matched_noise_phrases": [...],
                "has_human_migration_anchor": bool
            }
        """

        if not text:
            return {
                "is_noise": True,
                "noise_categories": ["EMPTY_TEXT"],
                "matched_noise_phrases": [],
                "has_human_migration_anchor": False,
            }

        matched_categories: List[str] = []
        matched_phrases: List[str] = []

        for category, patterns in self.NOISE_PATTERNS.items():
            for pattern in patterns:
                match = re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )

                if match:
                    if category not in matched_categories:
                        matched_categories.append(category)

                    matched_phrases.append(match.group(0))

        has_human_anchor = any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            for pattern in self.HUMAN_MIGRATION_ANCHORS
        )

        is_noise = bool(matched_categories) and not has_human_anchor

        return {
            "is_noise": is_noise,
            "noise_categories": matched_categories,
            "matched_noise_phrases": matched_phrases,
            "has_human_migration_anchor": has_human_anchor,
        }

    def is_noise(self, text: str) -> bool:
        """
        Convenience method returning only the noise decision.
        """
        return bool(self.analyze(text).get("is_noise"))
