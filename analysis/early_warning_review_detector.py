"""
Migration OSINT Monitor

File:
analysis/early_warning_review_detector.py

Purpose:
Generic migration early-warning / analyst-review detector.

This detector is deliberately NOT route-specific and NOT Ceuta-specific.
Locations are context only. Scoring is driven by event structure:

- movement / gathering / arrivals / departures
- route or border changes
- facilitation / transport / documents
- enforcement response
- sudden pressure / influx / quantitative change
- policy or access changes
- repeated or current operational reporting

The detector is intended for posts that did NOT pass the strict operational
event filter. A positive detection therefore creates an InfluenceSignal /
EARLY_WARNING layer record, not an operational event.

Design goal:
Recover useful weak signals without weakening the existing false-positive
protection of the operational event pipeline.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple


class EarlyWarningReviewDetector:
    RULES_VERSION = "EARLY_WARNING_REVIEW_V1_1"

    MIN_SCORE = 5.0

    # ------------------------------------------------------
    # HUMAN MIGRATION CONTEXT
    # ------------------------------------------------------

    MIGRATION_PATTERNS = (
        # English
        r"\bmigrants?\b",
        r"\brefugees?\b",
        r"\basylum\s+seekers?\b",
        r"\bimmigrants?\b",
        r"\birregular\s+migration\b",
        r"\billegal\s+migration\b",

        # Spanish
        r"\bmigrantes?\b",
        r"\brefugiados?\b",
        r"\binmigrantes?\b",
        r"\bsolicitantes?\s+de\s+asilo\b",

        # French
        r"\bmigrants?\b",
        r"\br[ée]fugi[ée]s?\b",
        r"\bdemandeurs?\s+d['’]asile\b",

        # Italian
        r"\bmigranti\b",
        r"\brifugiati\b",
        r"\bimmigrati\b",

        # Russian / CIS Cyrillic
        r"\bмигрант\w*\b",
        r"\bбежен\w*\b",
        r"\bиммигрант\w*\b",

        # Arabic
        r"مهاجر",
        r"لاجئ",
        r"الهجرة",
    )

    # ------------------------------------------------------
    # STRUCTURAL SIGNAL GROUPS
    # ------------------------------------------------------

    MOVEMENT_PATTERNS = (
        # English
        r"\b(?:migrants?|refugees?)\b.{0,90}\b(?:gather|gathering|assemble|assembling|move|moving|head(?:ing)?|depart|departing|leave|leaving|arrive|arriving|cross|crossing|enter|entered|reach|reached)\b",
        r"\b(?:gather|gathering|assemble|moving|heading|departing|leaving|arriving|crossing|entered|reached)\b.{0,90}\b(?:migrants?|refugees?)\b",

        # Spanish
        r"\b(?:migrantes?|refugiados?)\b.{0,90}\b(?:reun|concentr|salid|part|lleg|cruz|entr|dirig)\w*",
        r"\b(?:llegada|salida|cruce|concentraci[oó]n)\b.{0,90}\b(?:migrantes?|refugiados?)\b",

        # French / Italian
        r"\b(?:migrants?|r[ée]fugi[ée]s?|migranti|rifugiati)\b.{0,90}\b(?:arriv|d[ée]part|travers|part|sbarc|radun|rassembl)\w*",

        # Russian
        r"\b(?:мигрант\w*|бежен\w*)\b.{0,120}\b(?:прибы\w*|прибыл\w*|едут|движ\w*|направ\w*|собира\w*|скоп\w*|пересек\w*|переш\w*|въех\w*|выех\w*|наплыв\w*|нашеств\w*)\b",
        r"\b(?:наплыв\w*|нашеств\w*|прибыл\w*|пересек\w*|въех\w*|собира\w*)\b.{0,120}\b(?:мигрант\w*|бежен\w*)\b",

        # Arabic
        r"(?:مهاجر|لاجئ).{0,90}(?:تجمع|وصول|غادر|مغادرة|عبور|دخل|يتجه)",
    )

    ROUTE_PATTERNS = (
        r"\b(?:border|frontier|checkpoint|crossing\s+point|route|corridor|coast|shore|sea|boat|vessel)\b",
        r"\b(?:frontera|puesto\s+fronterizo|ruta|costa|mar|patera|cayuco|embarcaci[oó]n)\b",
        r"\b(?:fronti[èe]re|route|c[oô]te|mer|bateau|navire)\b",
        r"\b(?:confine|rotta|costa|mare|barca|nave)\b",
        r"\b(?:границ\w*|погран\w*|маршрут\w*|переход\w*|берег\w*|мор\w*|лодк\w*|судн\w*)\b",
        r"(?:الحدود|معبر|طريق|مسار|ساحل|البحر|قارب|سفينة)",
    )

    FACILITATION_PATTERNS = (
        r"\b(?:smuggl\w*|traffick\w*|facilitat\w*|transport\w*|driver|boat\s+available|seats?\s+available|fake\s+contract|false\s+document|forged\s+document)\b",
        r"\b(?:trafic\w*\s+de\s+migrantes|contrato\s+falso|documentos?\s+falsos?|transporte|conductor)\b",
        r"\b(?:passeur\w*|faux\s+documents?|transport)\b",
        r"\b(?:scafist\w*|documenti\s+falsi|trasporto)\b",
        r"\b(?:контрабанд\w*|перевоз\w*|водител\w*|поддельн\w*.{0,30}(?:документ|договор)|фиктивн\w*.{0,30}(?:документ|договор))\b",
        r"(?:تهريب|نقل المهاجرين|وثائق مزورة|عقد مزور)",
    )

    ENFORCEMENT_PATTERNS = (
        r"\b(?:intercepted|detained|arrested|rescued|deported|expelled|returned|raid|border\s+guards?|coast\s+guard|police\s+operation)\b",
        r"\b(?:interceptad\w*|detenid\w*|arrestad\w*|rescatad\w*|deportad\w*|expulsad\w*|redada|guardia\s+civil|guardia\s+costera)\b",
        r"\b(?:intercept[ée]\w*|arr[êe]t[ée]\w*|expuls[ée]\w*|secour\w*|garde-c[oô]tes|police)\b",
        r"\b(?:intercettat\w*|arrestat\w*|espuls\w*|soccors\w*|guardia\s+costiera)\b",
        r"\b(?:задерж\w*|выдвор\w*|депорт\w*|перехват\w*|рейд\w*|пограничн\w*|полици\w*)\b",
        r"(?:اعتراض|اعتقال|احتجاز|ترحيل|إبعاد|إنقاذ|حرس الحدود|خفر السواحل)",
    )

    PRESSURE_PATTERNS = (
        # Increase / surge
        r"\b(?:surge|influx|wave|mass\s+arrival|sharp\s+increase|rapid\s+increase|record\s+(?:number|level)|border\s+pressure|migration\s+pressure)\b",
        r"\b(?:increase|increased|increasing|rise|rose|rising)\b.{0,70}\b(?:migrant|migration|refugee|arrival|crossing)\w*",
        r"\b(?:migrant|migration|refugee|arrival|crossing)\w*\b.{0,70}\b(?:increase|increased|increasing|rise|rose|rising)\b",

        # Decrease / diversion can also be strategically relevant because it
        # may indicate route displacement rather than reduced total pressure.
        r"\b(?:decrease|decreased|decline|declined|drop|dropped|fall|fell)\b.{0,70}\b(?:migrant|migration|refugee|arrival|crossing)\w*",
        r"\b(?:migrant|migration|refugee|arrival|crossing)\w*\b.{0,70}\b(?:decrease|decreased|decline|declined|drop|dropped|fall|fell)\b",

        # Spanish / French / Italian
        r"\b(?:afluencia|oleada|llegada\s+masiva|aumento\s+brusco|descenso|disminuci[oó]n|presi[oó]n\s+migratoria)\b",
        r"\b(?:afflux|vague\s+de\s+migrants|hausse|baisse|diminution|pression\s+migratoire)\b",
        r"\b(?:ondata|afflusso|aumento|calo|diminuzione|pressione\s+migratoria)\b",

        # Russian / Cyrillic and common Uzbek Cyrillic wording
        r"\b(?:наплыв\w*|массов\w*.{0,30}(?:прибыт|миграц)|резк\w*.{0,30}(?:рост|увелич)|миграционн\w*.{0,30}давлен)\b",
        r"\b(?:мигрант\w*|миграц\w*)\b.{0,80}\b(?:сократ\w*|сниз\w*|уменьш\w*|вырос\w*|увелич\w*|рост\w*|камай\w*|ош\w*)\b",
        r"\b(?:сократ\w*|сниз\w*|уменьш\w*|вырос\w*|увелич\w*|камай\w*|ош\w*)\b.{0,80}\b(?:мигрант\w*|миграц\w*)\b",

        # Arabic
        r"(?:تدفق|موجة مهاجرين|زيادة حادة|انخفاض|تراجع|ضغط الهجرة)",
    )

    POLICY_ACCESS_PATTERNS = (
        r"\b(?:new\s+rule|new\s+law|new\s+requirement|border\s+closure|border\s+reopen|visa\s+change|entry\s+restriction|deportation\s+rule)\b",
        r"\b(?:nueva\s+ley|nueva\s+norma|nuevo\s+requisito|cierre\s+de\s+frontera|restricci[oó]n\s+de\s+entrada)\b",
        r"\b(?:nouvelle\s+loi|nouvelle\s+r[èe]gle|fermeture\s+de\s+fronti[èe]re|restriction\s+d['’]entr[ée]e)\b",
        r"\b(?:nuova\s+legge|nuova\s+regola|chiusura\s+del\s+confine|restrizione\s+all['’]ingresso)\b",
        r"\b(?:нов\w*.{0,25}(?:закон|правил|требован)|закрыт\w*.{0,25}границ|огранич\w*.{0,25}въезд|ужесточ\w*.{0,25}миграц)\b",
        r"(?:قانون جديد|قواعد جديدة|إغلاق الحدود|قيود الدخول)",
    )

    CURRENT_PATTERNS = (
        r"\btoday\b",
        r"\btonight\b",
        r"\bnow\b",
        r"\bcurrently\b",
        r"\bongoing\b",
        r"\bbreaking\b",
        r"\blatest\b",
        r"\bthis\s+(?:morning|afternoon|evening|week)\b",
        r"\byesterday\b",
        r"\bhoy\b",
        r"\bahora\b",
        r"\bayer\b",
        r"\baujourd['’]hui\b",
        r"\bhier\b",
        r"\boggi\b",
        r"\bсегодня\b",
        r"\bсейчас\b",
        r"\bвчера\b",
        r"(?:اليوم|الآن|أمس)",
    )

    QUANTITATIVE_PATTERNS = (
        r"\b\d{2,6}\b",
        r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|per\s+cent)\b",
        r"\b(?:dozens?|hundreds?|thousands?)\b",
        r"\b(?:decenas|cientos|miles)\b",
        r"\b(?:десятки|сотни|тысячи)\b",
        r"(?:عشرات|مئات|آلاف)",
    )

    # Strong commentary / non-event contexts. These do not necessarily reject
    # a post; they subtract from the score.
    COMMENTARY_PATTERNS = (
        r"\b(?:opinion|commentary|analysis|explainer|essay|debate)\b",
        r"\b(?:should|could|would)\b",
        r"\b(?:according\s+to\s+my\s+opinion|i\s+think|i\s+believe)\b",
        r"\b(?:мнение|аналитик\w*|считаю|думаю|должны|следовало\s+бы)\b",
        r"\b(?:opinión|analisis|análisis|deber[ií]a)\b",
    )

    # Explicit examples of content that often mentions migrants but should not
    # become migration early warning merely because an offender is a migrant.
    GENERIC_CRIME_PATTERNS = (
        r"\b(?:assault|murder|rape|robbery|arson|fight|terror attack)\b",
        r"\b(?:напал|убил|изнасил|ограб|драк|поджог|теракт)\w*",
        r"\b(?:agresi[oó]n|asesin|violaci[oó]n|robo|pelea)\w*",
    )

    def detect(
        self,
        text: str,
    ) -> Dict[str, Any]:
        value = str(
            text
            or ""
        ).strip()

        if not value:
            return self._empty()

        migration_matches = self._matches(
            value,
            self.MIGRATION_PATTERNS,
        )

        if not migration_matches:
            return self._empty(
                rejection_reason="NO_HUMAN_MIGRATION_CONTEXT"
            )

        groups = {
            "MOVEMENT": self._matches(
                value,
                self.MOVEMENT_PATTERNS,
            ),
            "ROUTE": self._matches(
                value,
                self.ROUTE_PATTERNS,
            ),
            "FACILITATION": self._matches(
                value,
                self.FACILITATION_PATTERNS,
            ),
            "ENFORCEMENT": self._matches(
                value,
                self.ENFORCEMENT_PATTERNS,
            ),
            "PRESSURE": self._matches(
                value,
                self.PRESSURE_PATTERNS,
            ),
            "POLICY_ACCESS": self._matches(
                value,
                self.POLICY_ACCESS_PATTERNS,
            ),
        }

        matched_groups = [
            key
            for key, matches
            in groups.items()
            if matches
        ]

        if not matched_groups:
            return self._empty(
                migration_context=True,
                context_matches=migration_matches,
                rejection_reason="NO_EVENT_STRUCTURE"
            )

        current_matches = self._matches(
            value,
            self.CURRENT_PATTERNS,
        )
        quantitative_matches = self._matches(
            value,
            self.QUANTITATIVE_PATTERNS,
        )
        commentary_matches = self._matches(
            value,
            self.COMMENTARY_PATTERNS,
        )
        generic_crime_matches = self._matches(
            value,
            self.GENERIC_CRIME_PATTERNS,
        )

        score = 2.0

        weights = {
            "MOVEMENT": 3.0,
            "ROUTE": 1.5,
            "FACILITATION": 3.0,
            "ENFORCEMENT": 2.0,
            "PRESSURE": 3.0,
            "POLICY_ACCESS": 2.0,
        }

        for group in matched_groups:
            score += weights[
                group
            ]

        if current_matches:
            score += 1.0

        if quantitative_matches:
            score += 1.0

        if len(
            matched_groups
        ) >= 2:
            score += 1.5

        if commentary_matches:
            score -= min(
                2.0,
                0.75
                * len(
                    commentary_matches
                ),
            )

        # Migrant-linked ordinary crime is not migration early warning unless
        # movement/route/facilitation/pressure structure is also present.
        if (
            generic_crime_matches
            and not any(
                group in matched_groups
                for group in (
                    "MOVEMENT",
                    "ROUTE",
                    "FACILITATION",
                    "PRESSURE",
                )
            )
        ):
            score -= 3.0

        primary_signal = self._primary_signal(
            matched_groups
        )

        detected = bool(
            score >= self.MIN_SCORE
        )

        confidence = self._confidence(
            score
        )

        matched_phrases: List[
            Tuple[str, str]
        ] = []

        for group, matches in groups.items():
            for match in matches:
                matched_phrases.append(
                    (
                        group.lower(),
                        match,
                    )
                )

        high_value_matches = []

        for group in (
            "MOVEMENT",
            "FACILITATION",
            "PRESSURE",
        ):
            high_value_matches.extend(
                groups.get(
                    group,
                    []
                )
            )

        return {
            "detected":
                detected,
            "primary_signal":
                primary_signal,
            "signal_mode":
                "ANALYST_REVIEW",
            "signal_intent":
                primary_signal,
            "confidence":
                confidence,
            "score":
                round(
                    score,
                    2,
                ),
            "matched_signals":
                [
                    primary_signal
                ]
                if detected
                else [],
            "matched_phrases":
                matched_phrases,
            "matched_groups":
                matched_groups,
            "context_matches":
                migration_matches,
            "high_value_matches":
                high_value_matches,
            "signal_context_rejections":
                commentary_matches
                + generic_crime_matches,
            "migration_context":
                True,
            "human_migration_context":
                True,
            "historical_reference":
                False,
            "historical_reason":
                None,
            "historical_reference_text":
                None,
            "rules_version":
                self.RULES_VERSION,
            "current_cues":
                current_matches,
            "quantitative_cues":
                quantitative_matches,
            "review_reason":
                (
                    "STRUCTURED_MIGRATION_EARLY_WARNING"
                    if detected
                    else "BELOW_EARLY_WARNING_THRESHOLD"
                ),
        }

    def _primary_signal(
        self,
        matched_groups: Sequence[str],
    ) -> str:
        priority = (
            (
                "MOVEMENT",
                "MOVEMENT_EARLY_WARNING",
            ),
            (
                "PRESSURE",
                "PRESSURE_EARLY_WARNING",
            ),
            (
                "FACILITATION",
                "FACILITATION_EARLY_WARNING",
            ),
            (
                "ROUTE",
                "ROUTE_EARLY_WARNING",
            ),
            (
                "ENFORCEMENT",
                "ENFORCEMENT_EARLY_WARNING",
            ),
            (
                "POLICY_ACCESS",
                "POLICY_ACCESS_EARLY_WARNING",
            ),
        )

        group_set = set(
            matched_groups
        )

        for group, signal in priority:
            if group in group_set:
                return signal

        return "ANALYST_REVIEW_SIGNAL"

    def _confidence(
        self,
        score: float,
    ) -> float:
        if score >= 10:
            return 0.9

        if score >= 8:
            return 0.8

        if score >= 6.5:
            return 0.72

        if score >= self.MIN_SCORE:
            return 0.62

        return 0.35

    @staticmethod
    def _matches(
        text: str,
        patterns: Sequence[str],
    ) -> List[str]:
        results: List[str] = []

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                text,
                flags=re.IGNORECASE
                | re.UNICODE,
            ):
                value = (
                    match.group(0)
                    .strip()
                )

                if (
                    value
                    and value not in results
                ):
                    results.append(
                        value
                    )

        return results

    def _empty(
        self,
        *,
        migration_context: bool = False,
        context_matches: List[str] | None = None,
        rejection_reason: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "detected":
                False,
            "primary_signal":
                None,
            "signal_mode":
                "ANALYST_REVIEW",
            "signal_intent":
                None,
            "confidence":
                0.0,
            "score":
                0.0,
            "matched_signals":
                [],
            "matched_phrases":
                [],
            "matched_groups":
                [],
            "context_matches":
                context_matches
                or [],
            "high_value_matches":
                [],
            "signal_context_rejections":
                (
                    [
                        rejection_reason
                    ]
                    if rejection_reason
                    else []
                ),
            "migration_context":
                migration_context,
            "human_migration_context":
                migration_context,
            "historical_reference":
                False,
            "historical_reason":
                None,
            "historical_reference_text":
                None,
            "rules_version":
                self.RULES_VERSION,
            "current_cues":
                [],
            "quantitative_cues":
                [],
            "review_reason":
                rejection_reason,
        }
