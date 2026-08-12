"""
Migration OSINT Monitor

File:
event_assertion_filter.py

Description:
Precision gate between operational phrase detection and persistent event
creation. V1.3.1 adds proximity-aware trafficking disambiguation while preserving
V1.3 historical and migration-enforcement gates. It rejects selected analytical, retrospective, hypothetical,
comparative and weak generic coordination contexts while preserving concrete
current event reports.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List


class EventAssertionFilter:

    CONTEXT_SENSITIVE_TYPES = {
        "INTERCEPTION",
        "COORDINATION",
        "ROUTE_INFORMATION",
        "TRAVEL_ADVICE",
        "BORDER_CONDITION",
        "MIGRANT_CAMP",
        "GENERAL_DISCUSSION",
        "SMUGGLING_ACTIVITY",
    }

    CURRENT_CUE_PATTERNS = [
        r"\btoday\b",
        r"\btonight\b",
        r"\bnow\b",
        r"\bcurrently\b",
        r"\bongoing\b",
        r"\bbreaking\b",
        r"\blatest\b",
        r"\bovernight\b",
        r"\bthis\s+morning\b",
        r"\bthis\s+afternoon\b",
        r"\bthis\s+evening\b",
        r"\bthis\s+week\b",
        r"\bjust\s+(?:arrived|crossed|intercepted|detained|arrested|rescued)\b",
        r"\bminutes?\s+ago\b",
        r"\bhours?\s+ago\b",
        r"\baujourd['’]hui\b",
        r"\bmaintenant\b",
        r"\bhoy\b",
        r"\bahora\b",
        r"\boggi\b",
        r"\badesso\b",
        r"\búltima\s+hora\b",
        r"\bсегодня\b",
        r"\bсейчас\b",
        r"\bвчера\b",
        r"(?:اليوم|الآن|أمس)",
    ]

    ANALYTICAL_CUE_PATTERNS = [
        r"\bdebunk(?:ing|ed)?\b",
        r"\bexplainer\b",
        r"\banalysis\b",
        r"\banalytical\b",
        r"\bbackground\b",
        r"\bcontext\b",
        r"\btimeline\b",
        r"\bstep[-\s]+by[-\s]+step\s+breakdown\b",
        r"\bwhat\s+really\s+happened\b",
        r"\bthis\s+thread\b",
        r"\bin\s+this\s+thread\b",
        r"\bthe\s+author\s+of\s+this\s+article\b",
        r"\bhistorical\s+overview\b",
        r"\bcase\s+study\b",
        r"\blong[-\s]+term\b",
        r"\bpreviously\b",
        r"\ba\s+few\s+years\s+ago\b",
        r"\byears?\s+ago\b",
    ]

    NON_ASSERTIVE_PATTERNS = [
        r"\bused\s+to\s+assume\b",
        r"\bi\s+(?:used\s+to\s+)?(?:think|assume|imagine)\b",
        r"\bimagine(?:d|s|ing)?\b",
        r"\bhypothetical(?:ly)?\b",
        r"\bsuppose(?:d|s|ing)?\b",
        r"\bas\s+if\b",
        r"\bmetaphor(?:ical|ically)?\b",
        r"\bcompared?\s+to\b",
        r"\b(?:like|as)\s+(?:a\s+)?(?:migrant|refugee)\s+camp\b",
        r"\bwhat\s+if\b",
    ]

    DIRECT_EVENT_PATTERNS = [
        r"\b(?:migrants?|refugees?)\s+(?:arrived|crossed|landed|departed)\b",
        r"\b(?:migrants?|refugees?)\s+(?:were\s+)?(?:intercepted|detained|arrested|rescued)\b",
        r"\b(?:migrant|refugee)\s+(?:died|drowned)\b",
        r"\b(?:smuggler|smugglers)\s+(?:was|were)?\s*arrested\b",
        r"\b(?:police|authorities|coast\s+guard)\s+(?:arrested|detained|intercepted|rescued)\b",
    ]

    HISTORICAL_YEAR_PATTERN = r"\b(?:19|20)\d{2}\b"

    MIGRATION_ENFORCEMENT_PATTERNS = [
        r"\b(?:immigration|migration|border|asylum)\s+(?:raid|operation|enforcement|police|officers?|authorities)\b",
        r"\b(?:ICE|Border\s+Patrol|border\s+guards?|coast\s+guard|immigration\s+officers?)\b",
        r"\b(?:illegal|irregular|undocumented)\s+(?:migrants?|immigrants?|entry|stay|crossing)\b",
        r"\b(?:migrants?|refugees?)\b.{0,100}\b(?:deported|expelled|returned|removed|intercepted|detained\s+for\s+illegal\s+entry)\b",
        r"\b(?:миграционн\w*|пограничн\w*)\b.{0,100}\b(?:рейд\w*|контрол\w*|полици\w*|провер\w*)\b",
        r"\b(?:нелегальн\w*|незаконн\w*)\b.{0,50}\b(?:мигрант\w*|пребыван\w*|въезд\w*)\b",
        r"(?:شرطة الهجرة|حرس الحدود|خفر السواحل|هجرة غير شرعية|ترحيل المهاجرين|إبعاد المهاجرين)",
    ]

    HUMAN_SMUGGLING_CONTEXT_PATTERNS = [
        r"\b(?:human|people|migrant|migrants|refugee|refugees)\s+(?:smuggl\w*|traffick\w*)\b",
        r"\b(?:smuggl\w*|traffick\w*)\s+(?:of\s+)?(?:people|persons|migrants?|refugees?)\b",
        r"\b(?:smuggling|trafficking)\s+(?:network|ring|gang)\b.{0,100}\b(?:migrants?|refugees?|people)\b",
        r"\b(?:migrants?|refugees?|people)\b.{0,100}\b(?:smuggling|trafficking)\s+(?:network|ring|gang)\b",
        r"\b(?:people|migrant)\s+smugglers?\b",
        r"\b(?:tr[aá]fico|trata)\s+de\s+(?:migrantes|personas)\b",
        r"\b(?:мигрант\w*|бежен\w*)\b.{0,100}\b(?:контрабанд\w*|перевоз\w*)\b",
        r"(?:تهريب المهاجرين|مهربو المهاجرين|مهربين).{0,100}(?:مهاجر|لاجئ|الحدود)",
    ]

    SMUGGLING_ACTION_PATTERNS = [
        r"\b(?:police|authorities|border\s+guards?|coast\s+guard)\b.{0,120}\b(?:arrested|detained|dismantled|busted|disrupted|intercepted)\b.{0,120}\b(?:smuggl\w*|traffick\w*)\b",
        r"\b(?:smuggl\w*|traffick\w*)\s+(?:network|ring|gang)\b.{0,120}\b(?:dismantled|busted|disrupted|arrested|detained|charged|convicted)\b",
        r"\b(?:arrested|detained|charged|convicted)\b.{0,100}\b(?:smuggler|smugglers|trafficker|traffickers)\b",
        r"\b(?:network|ring|gang)\b.{0,120}\b(?:moved|transported|smuggled|brought|carried)\b.{0,100}\b(?:migrants?|refugees?|people)\b",
        r"\b(?:migrants?|refugees?|people)\b.{0,100}\b(?:were\s+)?(?:smuggled|transported|moved|brought|carried)\b",

        # Concrete commercial/facilitation offer or claimed method.
        r"\b(?:people|migrant)\s+smuggler\b.{0,140}\b(?:claim\w*|offer\w*|arrang\w*|bring\w*|transport\w*|use\w*)\b",
        r"\b(?:claim\w*|offer\w*|arrang\w*|bring\w*|transport\w*)\b.{0,140}\b(?:migrant|migrants|refugee|refugees)\b",
        r"\b(?:fake|false|forged)\s+(?:passport|passports|document|documents)\b.{0,140}\b(?:bring|move|transport|smuggl)\w*\b.{0,100}\b(?:migrant|migrants|people)\b",
        r"\b(?:migrant|migrants|people)\b.{0,120}\b(?:fake|false|forged)\s+(?:passport|passports|document|documents)\b",
        r"(?:£|\$|€)\s*\d[\d,\.]*\b.{0,120}\b(?:arrang\w*|bring\w*|transport\w*)\b.{0,100}\b(?:migrant|migrants|people)\b",
    ]

    NON_HUMAN_TRAFFICKING_PATTERNS = [
        r"\b(?:drug|drugs|pills?|narcotics?|cocaine|heroin|meth|fentanyl)\b.{0,80}\b(?:traffick\w*|smuggl\w*)\b",
        r"\b(?:traffick\w*|smuggl\w*)\b.{0,80}\b(?:drug|drugs|pills?|narcotics?|cocaine|heroin|meth|fentanyl)\b",
        r"\b(?:wildlife|lizard|lizards|animal|animals|weapons?|guns?|cigarettes?|tobacco|goods)\b.{0,80}\b(?:traffick\w*|smuggl\w*)\b",
        r"\b(?:traffick\w*|smuggl\w*)\b.{0,80}\b(?:wildlife|lizard|lizards|animal|animals|weapons?|guns?|cigarettes?|tobacco|goods)\b",
    ]

    GENERIC_CRIME_PATTERNS = [
        r"\b(?:assault|murder|rape|robbery|arson|fight|stabbing|stabbed|shooting)\b",
        r"\b(?:напал|убил|изнасил|ограб|драк|поджог|теракт)\w*",
        r"\b(?:agresi[oó]n|asesin|violaci[oó]n|robo|pelea|apuñal)\w*",
    ]

    # Generic phrases such as "contact me" and "recommend" occur constantly
    # in unrelated web content. They must not be sufficient to create a
    # migration COORDINATION / TRAVEL_ADVICE event.
    WEAK_COORDINATION_PHRASES = {
        "contact me",
        "contact us",
        "recommend",
        "recommended",
        "telegram",
        "whatsapp",
        "signal",
    }

    STRONG_COORDINATION_PATTERNS = [
        r"\bcontact\s+(?:me|us)\s+on\s+(?:telegram|whatsapp|signal)\b",
        r"\b(?:join|message|dm)\s+(?:me|us|the\s+group)\s+(?:on\s+)?(?:telegram|whatsapp|signal)\b",
        r"\b(?:telegram|whatsapp|signal)\s+(?:group|channel|chat)\b",
        r"\b(?:telegram|whatsapp|signal)\b.{0,120}\b(?:crossing|border|route|boat|transport|smuggl|fake\s+contract|work\s+contract|documents?|illegal\s+stay)\b",
        r"\b(?:crossing|border|route|boat|transport|smuggl|fake\s+contract|work\s+contract|documents?|illegal\s+stay)\b.{0,120}\b(?:telegram|whatsapp|signal)\b",
        r"\bmeeting\s+point\b",
        r"\bpickup\s+point\b",
        r"\bgathering\s+point\b",
        r"\bdeparture\s+point\b",
        r"\btransport\s+available\b",
        r"\bboat\s+available\b",
        r"\bdriver\s+available\b",
        r"\bseats?\s+available\b",
        r"\b(?:cross|crossing|route|border|boat|transport).{0,80}\bcontact\s+(?:me|us)\b",
        r"\bcontact\s+(?:me|us)\b.{0,80}\b(?:cross|crossing|route|border|boat|transport)\b",
        r"\b(?:migrants?|refugees?).{0,100}\b(?:telegram|whatsapp|meeting\s+point|pickup\s+point|transport\s+available|boat\s+available)\b",
        r"\b(?:telegram|whatsapp|meeting\s+point|pickup\s+point|transport\s+available|boat\s+available).{0,100}\b(?:migrants?|refugees?)\b",
    ]

    MIGRATION_CONTEXT_PATTERNS = [
        r"\bmigrants?\b",
        r"\brefugees?\b",
        r"\basylum\s+seekers?\b",
        r"\billegal\s+immigration\b",
        r"\birregular\s+migration\b",
        r"\bborder\s+crossing\b",
        r"\bmigrant\s+boat\b",
        r"\brefugee\s+boat\b",
        r"\bsmuggl(?:er|ers|ing)\b",
        r"\bmigrantes?\b",
        r"\brefugiados?\b",
        r"\binmigrantes?\b",
        r"\bcruce\s+fronterizo\b",
        r"\bpateras?\b",
        r"\bcayucos?\b",
        r"\bmigrants?\b",
        r"\bréfugiés?\b",
        r"\bfrontière\b",
        r"الهجرة",
        r"مهاجر",
        r"لاجئ",
        r"мигрант",
        r"бежен",
    ]

    LONG_TEXT_THRESHOLD = 1800
    VERY_LONG_TEXT_THRESHOLD = 4500

    def analyze(
        self,
        *,
        post: Dict[str, Any],
        event: Dict[str, Any],
        operational_result: Dict[str, Any],
    ) -> Dict[str, Any]:

        text = str(
            post.get("text")
            or event.get("text")
            or ""
        )

        event_type = str(
            event.get("event_type")
            or "GENERAL_DISCUSSION"
        ).upper()

        matched_signals = {
            str(value).upper()
            for value in (event.get("matched_signals") or [])
            if value
        }

        operational_categories = {
            str(value).upper()
            for value in (
                operational_result.get("operational_categories")
                or []
            )
            if value
        }

        current_cues = self._find_matches(
            text,
            self.CURRENT_CUE_PATTERNS,
        )
        analytical_cues = self._find_matches(
            text,
            self.ANALYTICAL_CUE_PATTERNS,
        )
        non_assertive_cues = self._find_matches(
            text,
            self.NON_ASSERTIVE_PATTERNS,
        )
        direct_event_cues = self._find_matches(
            text,
            self.DIRECT_EVENT_PATTERNS,
        )

        migration_context_cues = self._find_matches(
            text,
            self.MIGRATION_CONTEXT_PATTERNS,
        )

        strong_coordination_cues = self._find_matches(
            text,
            self.STRONG_COORDINATION_PATTERNS,
        )

        migration_enforcement_cues = self._find_matches(
            text,
            self.MIGRATION_ENFORCEMENT_PATTERNS,
        )

        human_smuggling_cues = self._find_matches(
            text,
            self.HUMAN_SMUGGLING_CONTEXT_PATTERNS,
        )

        smuggling_action_cues = self._find_matches(
            text,
            self.SMUGGLING_ACTION_PATTERNS,
        )

        non_human_trafficking_cues = self._find_matches(
            text,
            self.NON_HUMAN_TRAFFICKING_PATTERNS,
        )

        generic_crime_cues = self._find_matches(
            text,
            self.GENERIC_CRIME_PATTERNS,
        )

        historical_years = self._historical_years(
            text
        )

        matched_operational_phrases = {
            str(value).strip().lower()
            for value in (
                operational_result.get(
                    "matched_operational_phrases"
                )
                or []
            )
            if value
        }

        weak_coordination_only = bool(
            matched_operational_phrases
        ) and matched_operational_phrases.issubset(
            self.WEAK_COORDINATION_PHRASES
        )

        coordination_sensitive = bool(
            event_type in {
                "COORDINATION",
                "TRAVEL_ADVICE",
                "ROUTE_INFORMATION",
            }
            or "COORDINATION_ADVICE"
            in operational_categories
        )

        context_sensitive = (
            event_type in self.CONTEXT_SENSITIVE_TYPES
            or bool(
                matched_signals
                & self.CONTEXT_SENSITIVE_TYPES
            )
            or "COORDINATION_ADVICE"
            in operational_categories
        )

        smuggling_sensitive = bool(
            event_type == "SMUGGLING_ACTIVITY"
            or "SMUGGLING_ACTIVITY"
            in matched_signals
            or "SMUGGLING"
            in operational_categories
        )

        enforcement_sensitive = bool(
            event_type in {
                "INTERCEPTION",
                "DEPORTATION",
                "DETENTION",
            }
            or bool(
                matched_signals
                & {
                    "INTERCEPTION",
                    "DEPORTATION",
                    "DETENTION",
                }
            )
        )

        # --------------------------------------------------
        # V1.3 OPERATIONAL ACTUALITY / HUMAN-SMUGGLING GATES
        # --------------------------------------------------

        # Explicit old-year references indicate retrospective material unless
        # the same post also contains a strong current cue.
        if (
            historical_years
            and not current_cues
            and (
                smuggling_sensitive
                or context_sensitive
            )
        ):
            return self._reject(
                "EXPLICIT_HISTORICAL_YEAR",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        # Drug / wildlife / goods trafficking must never become a human
        # migration-smuggling event merely because the word "migrant" appears
        # elsewhere in the post.
        if (
            smuggling_sensitive
            and non_human_trafficking_cues
            and not self._has_clean_human_smuggling_context(
                text
            )
        ):
            return self._reject(
                "NON_HUMAN_TRAFFICKING_CONTEXT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        # Smuggling nouns alone ("people smugglers", "smuggling network") are
        # not enough. Require both human-migration context AND a concrete
        # smuggling action/assertion.
        if (
            smuggling_sensitive
            and (
                not human_smuggling_cues
                or not smuggling_action_cues
            )
            and not direct_event_cues
        ):
            return self._reject(
                "SMUGGLING_NOUN_WITHOUT_CONCRETE_ACTION",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        # Ordinary crime by a person described as a migrant is not migration
        # enforcement. Enforcement must be tied to immigration/border status.
        if (
            enforcement_sensitive
            and generic_crime_cues
            and not migration_enforcement_cues
            and not direct_event_cues
        ):
            return self._reject(
                "ORDINARY_CRIME_NOT_MIGRATION_ENFORCEMENT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        # Precision gate for the recurring false positive seen in the live
        # monitor: generic article/blog language such as "contact me" and
        # "recommend" must not become a migration coordination event.
        if (
            coordination_sensitive
            and not strong_coordination_cues
            and (
                weak_coordination_only
                or not migration_context_cues
            )
            and not direct_event_cues
        ):
            return self._reject(
                "WEAK_COORDINATION_WITHOUT_MIGRATION_OPERATIONAL_CONTEXT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        if (
            non_assertive_cues
            and event_type in {
                "MIGRANT_CAMP",
                "GENERAL_DISCUSSION",
                "BORDER_CONDITION",
                "COORDINATION",
                "ROUTE_INFORMATION",
                "TRAVEL_ADVICE",
            }
            and not current_cues
            and not direct_event_cues
        ):
            return self._reject(
                "NON_ASSERTIVE_OR_COMPARATIVE_CONTEXT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        if (
            len(text) >= self.LONG_TEXT_THRESHOLD
            and len(analytical_cues) >= 2
            and context_sensitive
            and not current_cues
        ):
            return self._reject(
                "ANALYTICAL_OR_RETROSPECTIVE_CONTEXT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        if (
            len(text) >= self.VERY_LONG_TEXT_THRESHOLD
            and analytical_cues
            and event_type in self.CONTEXT_SENSITIVE_TYPES
            and not current_cues
        ):
            return self._reject(
                "VERY_LONG_CONTEXT_DOCUMENT",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        if (
            event_type == "GENERAL_DISCUSSION"
            and analytical_cues
            and not direct_event_cues
            and not current_cues
        ):
            return self._reject(
                "GENERAL_DISCUSSION_WITHOUT_DIRECT_ASSERTION",
                analytical_cues,
                current_cues,
                non_assertive_cues,
                direct_event_cues,
            )

        return {
            "accepted": True,
            "reason": None,
            "analytical_cues": analytical_cues,
            "current_cues": current_cues,
            "non_assertive_cues": non_assertive_cues,
            "direct_event_cues": direct_event_cues,
        }

    def _has_clean_human_smuggling_context(
        self,
        text: str,
    ) -> bool:
        """
        True if at least one human-smuggling cue has a clean local context.

        This is intentionally local. A later paragraph about drug smuggling
        must not invalidate an earlier, concrete migrant-smuggling account.
        """

        for pattern in self.HUMAN_SMUGGLING_CONTEXT_PATTERNS:
            for match in re.finditer(
                pattern,
                text,
                flags=re.IGNORECASE
                | re.UNICODE,
            ):
                start = max(
                    0,
                    match.start()
                    - 160,
                )
                end = min(
                    len(text),
                    match.end()
                    + 160,
                )

                local = text[
                    start:end
                ]

                if not self._find_matches(
                    local,
                    self.NON_HUMAN_TRAFFICKING_PATTERNS,
                ):
                    return True

        return False

    def _historical_years(
        self,
        text: str,
    ) -> List[str]:

        current_year = datetime.now(
            timezone.utc
        ).year

        years = []

        for value in re.findall(
            self.HISTORICAL_YEAR_PATTERN,
            text,
        ):
            try:
                year = int(
                    value
                )
            except ValueError:
                continue

            if year <= (
                current_year
                - 2
            ):
                years.append(
                    value
                )

        return list(
            dict.fromkeys(
                years
            )
        )

    def _find_matches(
        self,
        text: str,
        patterns: List[str],
    ) -> List[str]:

        results: List[str] = []

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                value = match.group(0)

                if value not in results:
                    results.append(value)

        return results

    def _reject(
        self,
        reason,
        analytical_cues,
        current_cues,
        non_assertive_cues,
        direct_event_cues,
    ):
        return {
            "accepted": False,
            "reason": reason,
            "analytical_cues": analytical_cues,
            "current_cues": current_cues,
            "non_assertive_cues": non_assertive_cues,
            "direct_event_cues": direct_event_cues,
        }

