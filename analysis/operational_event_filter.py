"""
Migration OSINT Monitor

File:
operational_event_filter.py

Description:
Strict first-pass detector for concrete migration operational events.

V2 multilingual precision update:
- English, Spanish, French, Italian, Russian/CIS Cyrillic and Arabic;
- generic migration/police/crime words are not sufficient;
- concrete event structures are required;
- EventAssertionFilter remains the second precision gate.
"""

import re
from typing import Dict, List


class OperationalEventFilter:

    OPERATIONAL_PATTERNS = {
        "MOVEMENT": [
            r"\bmigrants? crossed\b",
            r"\brefugees? crossed\b",
            r"\bcrossing the border\b",
            r"\battempted crossing\b",
            r"\battempting to enter\b",
            r"\bmigrants? arrived\b",
            r"\brefugees? arrived\b",
            r"\bmass arrival\b",
            r"\bboat departed\b",
            r"\bvessel departed\b",
            r"\bset off from\b",
            r"\bleft the coast\b",
            r"\b(?:migrantes?|refugiados?)\b.{0,90}\b(?:llegaron|cruzaron|entraron|salieron|partieron)\b",
            r"\b(?:migrants?|r[ée]fugi[ée]s?)\b.{0,90}\b(?:sont\s+arriv[ée]s|ont\s+travers[ée]|sont\s+entr[ée]s|sont\s+partis)\b",
            r"\b(?:migranti|rifugiati)\b.{0,90}\b(?:sono\s+arrivati|hanno\s+attraversato|sono\s+entrati|sono\s+partiti)\b",
            r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,120}\b(?:прибыли|прибыл\w*|пересек\w*|въех\w*|выех\w*|направ\w*|движ\w*)\b",
            r"(?:مهاجر|لاجئ).{0,100}(?:وصل|عبر|دخل|غادر|يتجه)",
        ],
        "RESCUE": [
            r"\bmigrants? rescued\b",
            r"\brefugees? rescued\b",
            r"\brescue operation\b",
            r"\bcoast guard rescued\b",
            r"\bsaved from drowning\b",
            r"\b(?:migrantes?|refugiados?)\b.{0,90}\b(?:rescatad\w*|salvad\w*)\b",
            r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,120}\bспас\w*\b",
            r"(?:مهاجر|لاجئ).{0,100}(?:إنقاذ|أنقذ)",
        ],
        "INTERCEPTION": [
            r"\bmigrants? intercepted\b",
            r"\brefugees? intercepted\b",
            r"\bboat intercepted\b",
            r"\bvessel intercepted\b",
            r"\bprevented from crossing\b",
            r"\bstopped at the border\b",
            r"\b(?:migrantes?|refugiados?)\b.{0,90}\binterceptad\w*\b",
            r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,120}\bперехват\w*\b",
            r"(?:مهاجر|لاجئ).{0,100}(?:اعتراض|منع.{0,30}عبور)",
        ],
        "ARREST_DETENTION": [
            r"\bmigrants? arrested\b",
            r"\brefugees? arrested\b",
            r"\bmigrants? detained\b",
            r"\brefugees? detained\b",
            r"\bsmugglers? arrested\b",
            r"\bsuspected smugglers? arrested\b",
            r"\bpolice arrested\b",
            r"\b(?:migrantes?|refugiados?)\b.{0,100}\b(?:detenid\w*|arrestad\w*)\b",
            r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*|иностранц\w*)\b.{0,130}\b(?:задерж\w*|арест\w*|провер\w*)\b",
            r"\b(?:рейд\w*|провер\w*|текширув\w*)\b.{0,170}\b(?:мигрант\w*|муҳожир\w*|иностранц\w*|хорижлик\w*|чет\s+эл\s+фуқарос\w*)\b",
            r"\b(?:миграция\s+рейд\w*|миграция\s+текширув\w*)\b",
            r"(?:мухаҷир|مهاجر|لاجئ).{0,100}(?:اعتقال|احتجاز|أوقف)",
        ],
        "DEPORTATION_RETURN": [
            r"\b(?:migrants?|refugees?|immigrants?)\b.{0,110}\b(?:were\s+)?(?:deported|expelled|removed|repatriated)\b",
            r"\b(?:deportation|removal|repatriation)\s+(?:flight|operation)\b",
            r"\b(?:migrantes?|inmigrantes?|refugiados?)\b.{0,110}\b(?:deportad\w*|expulsad\w*|repatriad\w*)\b",
            r"\b(?:migrants?|r[ée]fugi[ée]s?)\b.{0,110}\b(?:expuls[ée]\w*|rapatri[ée]\w*)\b",
            r"\b(?:migranti|rifugiati)\b.{0,110}\b(?:espuls\w*|rimpatri\w*)\b",
            r"\b(?:мигрант\w*|муҳожир\w*|иностранц\w*|хорижлик\w*|чет\s+эл\s+фуқарос\w*)\b.{0,150}\b(?:депортирован\w*|выдворен\w*|возвращен\w*|қайтарил\w*|чиқариб\s+юборил\w*)\b",
            r"\b(?:депортирован\w*|выдворен\w*|возвращен\w*|қайтарил\w*|чиқариб\s+юборил\w*)\b.{0,150}\b(?:мигрант\w*|муҳожир\w*|иностранц\w*|хорижлик\w*|чет\s+эл\s+фуқарос\w*)\b",
            r"\b(?:махсус\s+)?чартер\s+рейс\w*\b.{0,180}\b(?:қайтарил\w*|депортация\s+қилинган|олиб\s+келин\w*)\b",
            r"\b(?:депортация\s+қилинган|чиқариб\s+юборилган)\b.{0,140}\b(?:фуқаро\w*|мигрант\w*|муҳожир\w*)\b",
            r"(?:مهاجر|لاجئ).{0,110}(?:تم\s+ترحيل|رُحّل|تم\s+إبعاد|أُبعد)",
        ],
        "SMUGGLING": [
            r"\bmigrant smuggling\b",
            r"\bpeople smuggling\b",
            r"\bpeople smugglers\b",
            r"\bmigrant smugglers\b",
            r"\bhuman smuggling\b",
            r"\bsmuggling network\b.{0,100}\b(?:migrants?|refugees?|people)\b",
            r"\b(?:migrants?|refugees?|people)\b.{0,100}\bsmuggling (?:network|gang|ring)\b",
            r"\b(?:tr[aá]fico|trata)\s+de\s+(?:migrantes|personas)\b",
            r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,120}\b(?:контрабанд\w*|перевоз\w*)\b",
            r"(?:تهريب المهاجرين|مهربو المهاجرين|مهربين).{0,180}(?:مهاجر|لاجئ|الحدود|طريق)",
        ],
        "CASUALTY": [
            r"\bmigrant died\b",
            r"\bmigrants died\b",
            r"\brefugee died\b",
            r"\brefugees died\b",
            r"\bdrowned migrants\b",
            r"\bdrowned refugees\b",
            r"\bbody recovered\b",
            r"\bbodies recovered\b",
            r"\bmissing migrants\b",
            r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,100}\b(?:погиб\w*|утон\w*|пропал\w*)\b",
            r"(?:مهاجر|لاجئ).{0,100}(?:\bغرق\b|\bمفقود\b|(?:^|[\s،,.])مات(?:$|[\s،,.]))",
        ],
        "BORDER_ACTION": [
            r"\bborder closed\b",
            r"\bclosed the border\b",
            r"\bborder closure\b",
            r"\bnew border controls\b",
            r"\bborder restrictions\b",
            r"\breinforced border\b",
            r"\bdeployed to the border\b",
            r"\bfence construction\b",
            r"\bnew fence\b",
            r"\b(?:границ\w*|погран\w*)\b.{0,110}\b(?:закрыт\w*|усилен\w*|контрол\w*|огранич\w*)\b",
            r"(?:الحدود|المعبر).{0,100}(?:إغلاق|أغلق|تشديد\s+(?:الرقابة|الحراسة)|تعزيز\s+(?:الحراسة|الانتشار)|فرض\s+رقابة)",
        ],
        "HUMANITARIAN": [
            r"\bmigrant camp\b",
            r"\brefugee camp\b",
            r"\breception centre\b",
            r"\breception center\b",
            r"\bmigrant shelter\b",
            r"\brefugee shelter\b",
            r"\bsleeping rough\b",
            r"\btemporary accommodation\b",
        ],
        "COORDINATION_ADVICE": [
            r"\bmeeting point\b",
            r"\bcontact me\b",
            r"\bdm me\b",
            r"\bjoin the group\b",
            r"\bwhatsapp\b",
            r"\btelegram\b",
            r"\bhow to cross\b",
            r"\bbest route\b",
            r"\bsafest route\b",
            r"\bleave tonight\b",
            r"\bleaving tonight\b",
            r"\bleave tomorrow\b",
            r"\bleaving tomorrow\b",
        ],
    }

    NON_OPERATIONAL_PATTERNS = {
        "POLITICAL_OPINION": [
            r"\bi think\b",
            r"\bi believe\b",
            r"\bgovernment should\b",
            r"\bpoliticians\b",
            r"\belection\b",
            r"\bcampaign\b",
            r"\btraitor\b",
            r"\binvaders\b",
            r"\breplacement migration\b",
        ],
        "GENERAL_DEBATE": [
            r"\bmigration debate\b",
            r"\bimmigration debate\b",
            r"\bmigration policy debate\b",
            r"\bpublic opinion\b",
            r"\bwhat do you think\b",
            r"\bdiscussion about migration\b",
        ],
        "PERSONAL_COMMENTARY": [
            r"\bi hate migrants\b",
            r"\bi support migrants\b",
            r"\bi oppose migration\b",
            r"\bmy opinion\b",
            r"\bthis is wrong\b",
            r"\bthis is disgusting\b",
        ],
    }


    POLICY_PROPOSAL_PATTERNS = [
        r"\b(?:proposal|proposed|would\s+deport|should\s+deport|plan\s+to\s+deport|new\s+law|draft\s+law)\b",
        r"\b(?:таклиф|таклиф\s+қилин|таклиф\s+этил|предлага\w*|проект\s+закона|закон\s+о\s+выдворении|депортировать)\b",
        r"\b(?:қонун|таклиф)\b.{0,120}\b(?:депортация|чиқариб\s+юбориш)\b",
        r"\b(?:قانون|مقترح|اقتراح|سياسة)\b.{0,100}\b(?:ترحيل|إبعاد)\b",
    ]

    NEGATED_REMOVAL_PATTERNS = [
        r"\b(?:no|without)\s+deportation\b",
        r"\bни\s+депортаци\w*\b",
        r"\bдепортаци\w*\s+не\s+будет\b",
        r"\bдепортация\s+қилинмай\w*\b",
    ]

    GENERIC_CRIME_PATTERNS = [
        r"\b(?:assault|murder|rape|robbery|arson|fight|stabbing|shooting|terror\s+attack|fraud|theft)\b",
        r"\b(?:напал|убил|изнасил|ограб|драк|поджог|теракт|мошеннич|украл|украли|краж\w*|воров\w*)\w*",
        r"\b(?:жиноят\w*|фирибгар\w*|ўғир\w*|зўравон\w*)\b",
    ]

    STRONG_MIGRATION_ENFORCEMENT_PATTERNS = [
        r"\b(?:immigration|migration|border|asylum)\s+(?:raid|operation|enforcement|police|officers?|authorities)\b",
        r"\b(?:illegal|irregular|undocumented)\s+(?:migrants?|immigrants?|entry|stay|crossing)\b",
        r"\b(?:миграционн\w*|пограничн\w*|миграция\s+рейд\w*)\b.{0,130}\b(?:рейд\w*|провер\w*|задерж\w*|выдвор\w*|депорт\w*)\b",
        r"\b(?:миграция\s+қонунчилиг\w*|ҳужжатсиз|ноқонуний\s+мигрант\w*)\b",
        r"\b(?:махсус\s+)?чартер\s+рейс\w*\b.{0,180}\b(?:қайтарил\w*|депортация\s+қилинган|олиб\s+келин\w*)\b",
        r"(?:شرطة الهجرة|حرس الحدود|خفر السواحل|هجرة غير شرعية|ترحيل المهاجرين|إبعاد المهاجرين)",
    ]

    def analyze(self, text: str) -> Dict[str, object]:
        if not text:
            return {
                "is_operational": False,
                "operational_categories": [],
                "matched_operational_phrases": [],
                "non_operational_categories": ["EMPTY_TEXT"],
                "matched_non_operational_phrases": [],
                "confidence": 0.0,
            }

        operational_categories: List[str] = []
        operational_phrases: List[str] = []
        non_operational_categories: List[str] = []
        non_operational_phrases: List[str] = []

        for category, patterns in self.OPERATIONAL_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
                if match:
                    if category not in operational_categories:
                        operational_categories.append(category)
                    operational_phrases.append(match.group(0))

        for category, patterns in self.NON_OPERATIONAL_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
                if match:
                    if category not in non_operational_categories:
                        non_operational_categories.append(category)
                    non_operational_phrases.append(match.group(0))

        policy_or_proposal = any(
            re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
            for pattern in self.POLICY_PROPOSAL_PATTERNS
        )
        negated_removal = any(
            re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
            for pattern in self.NEGATED_REMOVAL_PATTERNS
        )
        generic_crime = any(
            re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
            for pattern in self.GENERIC_CRIME_PATTERNS
        )
        strong_migration_enforcement = any(
            re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
            for pattern in self.STRONG_MIGRATION_ENFORCEMENT_PATTERNS
        )

        if "DEPORTATION_RETURN" in operational_categories:
            if policy_or_proposal or negated_removal:
                operational_categories = [
                    category
                    for category in operational_categories
                    if category != "DEPORTATION_RETURN"
                ]

        if generic_crime and not strong_migration_enforcement:
            operational_categories = [
                category
                for category in operational_categories
                if category not in {
                    "DEPORTATION_RETURN",
                    "ARREST_DETENTION",
                }
            ]

        is_operational = bool(operational_categories)
        confidence = self._calculate_confidence(
            operational_categories=operational_categories,
            operational_phrases=operational_phrases,
            non_operational_categories=non_operational_categories,
        )

        return {
            "is_operational": is_operational,
            "operational_categories": operational_categories,
            "matched_operational_phrases": operational_phrases,
            "non_operational_categories": non_operational_categories,
            "matched_non_operational_phrases": non_operational_phrases,
            "confidence": confidence,
        }

    def _calculate_confidence(
        self,
        *,
        operational_categories: List[str],
        operational_phrases: List[str],
        non_operational_categories: List[str],
    ) -> float:
        if not operational_categories:
            return 0.10

        confidence = 0.60
        if len(operational_categories) >= 2:
            confidence += 0.10
        if len(operational_phrases) >= 2:
            confidence += 0.10
        if len(operational_phrases) >= 3:
            confidence += 0.05
        if non_operational_categories:
            confidence -= 0.10

        return round(max(0.0, min(confidence, 0.95)), 2)

    def is_operational(self, text: str) -> bool:
        return bool(self.analyze(text).get("is_operational"))
