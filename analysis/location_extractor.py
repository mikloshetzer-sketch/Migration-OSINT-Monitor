"""Configured multilingual location matching with token boundaries and context ordering."""
import json
import re
from pathlib import Path
from typing import List, Dict

class LocationExtractor:
    def __init__(self):
        config_dir = Path(__file__).resolve().parent.parent / "config"
        with open(config_dir / "locations.json", "r", encoding="utf-8") as file:
            self.locations = json.load(file)

    def extract_locations(self, text: str) -> List[Dict]:
        if not text:
            return []
        matches = []
        for location in self.locations:
            aliases = location.get("aliases", []) + [location.get("name", "")]
            best = None
            for alias in aliases:
                if not alias or len(alias.strip()) < 3:
                    continue
                # Unicode-aware: avoid matching inside other words.
                pattern = r"(?<!\w)" + re.escape(alias.strip()) + r"(?!\w)"
                for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                    score = len(alias.strip()) / 100
                    window = text[max(0,match.start()-90):min(len(text),match.end()+90)].casefold()
                    if re.search(r"\b(?:arrested|detained|rescued|raid|operation|рейд|рейдлар|ўтказилган|ҳалок|died|muertos|rescatados)\b",window):
                        score += 2
                    if re.search(r"\b(?:from|desde|из|из-за|departed from)\b", text[max(0,match.start()-25):match.start()].casefold()):
                        score -= 1
                    candidate = (score, -match.start())
                    if best is None or candidate > best:
                        best = candidate
            if best is not None:
                matches.append((best,location))
        matches.sort(key=lambda item: item[0],reverse=True)
        return [location for _,location in matches]

