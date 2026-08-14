"""
Migration OSINT Monitor

File:
analysis/early_warning_review_detector.py

Purpose:
Generic migration early-warning / analyst-review detector.

V1.2 precision model
--------------------
This detector is deliberately NOT route-specific and NOT Ceuta-specific.

It runs only after a post has failed the strict operational-event gate.
Its job is to preserve weaker but still analyst-useful migration signals
without promoting them to operational events.

V1.2 adds two precision controls:

1. LOCAL EVIDENCE WINDOW
   Signal groups are scored only when migration context and event structure
   occur in the same short text window. Signals found in distant paragraphs
   of a long article are not accumulated together.

2. ACTUALITY / ASSERTION GATE
   A structural keyword match is not enough. The best local window must also
   contain evidence of a real recent/current development, a concrete
   enforcement/facilitation action, or a quantified migration-pressure trend.

This is intended to reject:
- books / historical narratives,
- hypothetical or policy debate,
- long unrelated articles where migration terms appear far apart,
- political commentary about what migrants "could" or "would" do,
while keeping:
- concrete movement / arrival / gathering reports,
- border or route changes tied to real activity,
- migrant smuggling/facilitation reporting,
- raids, interceptions, detentions and returns,
- quantified increases/decreases that may indicate route pressure changes.

Locations are context only. No location receives a scoring bonus.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple


class EarlyWarningReviewDetector:
    RULES_VERSION = "EARLY_WARNING_REVIEW_V1_3_6_FINAL"

    MIN_SCORE = 5.0
    WINDOW_MAX_CHARS = 460

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
        r"\bмуҳожир\w*\b",
        r"\bхорижлик\w*\b",
        r"\bчет\s+эл\s+фуқарос\w*\b",

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

        # Russian / CIS
        r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,120}\b(?:прибы\w*|прибыл\w*|едут|движ\w*|направ\w*|собира\w*|скоп\w*|пересек\w*|переш\w*|въех\w*|выех\w*|наплыв\w*|нашеств\w*)\b",
        r"\b(?:наплыв\w*|нашеств\w*|прибыл\w*|пересек\w*|въех\w*|собира\w*)\b.{0,120}\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b",

        # Arabic
        r"(?:مهاجر|لاجئ).{0,90}(?:تجمع|وصول|غادر|مغادرة|عبور|دخل|يتجه)",
    )

    ROUTE_PATTERNS = (
        r"\b(?:border|frontier|checkpoint|crossing\s+point|route|corridor|coast|shore|sea|boat|vessel)\b",
        r"\b(?:frontera|puesto\s+fronterizo|ruta|costa|mar|patera|cayuco|embarcaci[oó]n)\b",
        r"\b(?:fronti[èe]re|route|c[oô]te|mer|bateau|navire)\b",
        r"\b(?:confine|rotta|costa|mare|barca|nave)\b",
        r"\b(?:границ\w*|погран\w*|маршрут\w*|переход\w*|берег\w*|мор\w*|лодк\w*|судн\w*)\b",
        r"(?:الحدود|معبر|طريق|مسار|ساحل|البحر|قارب|سفينة|السلك)",
        r"(?:دخلت|دخل|يعبر|عبور).{0,80}(?:طريق|الحدود|السلك)",
    )

    FACILITATION_PATTERNS = (
        # Human / migrant smuggling only. Generic "trafficking" is NOT
        # sufficient because it frequently refers to drugs, wildlife or goods.
        r"\b(?:human|people|migrant|migrants|refugee|refugees)\s+(?:smuggl\w*|traffick\w*)\b",
        r"\b(?:smuggl\w*|traffick\w*)\s+(?:of\s+)?(?:people|persons|migrants?|refugees?)\b",

        # Reverse-order journalistic wording, e.g.
        # "network accused of trafficking underage migrant girls".
        r"\b(?:smuggl\w*|traffick\w*)\b.{0,110}\b(?:migrants?|refugees?|persons?|girls?|children)\b",
        r"\b(?:criminal\s+network|network|ring|gang)\b.{0,120}\b(?:smuggl\w*|traffick\w*)\b.{0,120}\b(?:migrants?|refugees?|persons?|girls?|children)\b",

        r"\b(?:smuggling|trafficking)\s+(?:network|ring|gang)\b.{0,100}\b(?:migrants?|refugees?|people)\b",
        r"\b(?:migrants?|refugees?)\b.{0,100}\b(?:smuggling|trafficking)\s+(?:network|ring|gang)\b",
        r"\b(?:facilitat\w*|transport\w*|driver|boat\s+available|seats?\s+available|fake\s+contract|false\s+document|forged\s+document)\b.{0,100}\b(?:migrants?|refugees?|border|crossing|illegal\s+entry)\b",
        r"\b(?:migrants?|refugees?|border|crossing|illegal\s+entry)\b.{0,100}\b(?:facilitat\w*|transport\w*|driver|boat\s+available|seats?\s+available|fake\s+contract|false\s+document|forged\s+document)\b",

        # Spanish / French / Italian
        r"\b(?:tr[aá]fico|trata)\s+de\s+(?:migrantes|personas)\b",
        r"\b(?:migrantes?|refugiados?)\b.{0,100}\b(?:transporte|conductor|documentos?\s+falsos?|contrato\s+falso)\b",
        r"\b(?:passeur\w*|trafic\s+de\s+migrants?|faux\s+documents?)\b",
        r"\b(?:scafist\w*|traffico\s+di\s+migranti|documenti\s+falsi)\b",

        # Russian / CIS
        r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,120}\b(?:контрабанд\w*|перевоз\w*|водител\w*|поддельн\w*.{0,30}(?:документ|договор)|фиктивн\w*.{0,30}(?:документ|договор))\b",
        r"\b(?:контрабанд\w*|перевоз\w*)\b.{0,120}\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b",

        # Arabic. The slightly larger local distance is intentional because
        # colloquial Telegram posts often introduce the smugglers first and
        # describe the migrant/route consequence in the following sentence.
        r"(?:تهريب المهاجرين|مهربو المهاجرين|مهربين|مهرب).{0,420}(?:مهاجر|لاجئ|الحدود|طريق|السلك)",
        r"(?:مهاجر|لاجئ).{0,420}(?:تهريب|مهربين|مهرب|نقل المهاجرين|وثائق مزورة|عقد مزور)",
    )

    ENFORCEMENT_PATTERNS = (
        r"\b(?:intercepted|detained|arrested|rescued|deported|expelled|returned|raid|border\s+guards?|coast\s+guard|police\s+operation)\b",
        r"\b(?:interceptad\w*|detenid\w*|arrestad\w*|rescatad\w*|deportad\w*|expulsad\w*|redada|guardia\s+civil|guardia\s+costera)\b",
        r"\b(?:intercept[ée]\w*|arr[êe]t[ée]\w*|expuls[ée]\w*|secour\w*|garde-c[oô]tes|police)\b",
        r"\b(?:intercettat\w*|arrestat\w*|espuls\w*|soccors\w*|guardia\s+costiera)\b",
        r"\b(?:задерж\w*|выдвор\w*|депорт\w*|перехват\w*|рейд\w*|пограничн\w*|полици\w*|қайтар\w*)\b",
        r"(?:اعتراض|اعتقال|احتجاز|ترحيل|إبعاد|إنقاذ|حرس الحدود|خفر السواحل|كبسة)",
    )

    PRESSURE_PATTERNS = (
        # Increase / surge
        r"\b(?:surge|influx|wave|mass\s+arrival|sharp\s+increase|rapid\s+increase|record\s+(?:number|level)|border\s+pressure|migration\s+pressure)\b",
        r"\b(?:increase|increased|increasing|rise|rose|rising)\b.{0,70}\b(?:migrant|migration|refugee|arrival|crossing)\w*",
        r"\b(?:migrant|migration|refugee|arrival|crossing)\w*\b.{0,70}\b(?:increase|increased|increasing|rise|rose|rising)\b",

        # Decrease / route displacement
        r"\b(?:decrease|decreased|decline|declined|drop|dropped|fall|fell)\b.{0,70}\b(?:migrant|migration|refugee|arrival|crossing)\w*",
        r"\b(?:migrant|migration|refugee|arrival|crossing)\w*\b.{0,70}\b(?:decrease|decreased|decline|declined|drop|dropped|fall|fell)\b",

        # Spanish / French / Italian
        r"\b(?:afluencia|oleada|llegada\s+masiva|aumento\s+brusco|descenso|disminuci[oó]n|presi[oó]n\s+migratoria)\b",
        r"\b(?:afflux|vague\s+de\s+migrants|hausse|baisse|diminution|pression\s+migratoire)\b",
        r"\b(?:ondata|afflusso|aumento|calo|diminuzione|pressione\s+migratoria)\b",

        # Russian / CIS Cyrillic
        r"\b(?:наплыв\w*|массов\w*.{0,30}(?:прибыт|миграц)|резк\w*.{0,30}(?:рост|увелич)|миграционн\w*.{0,30}давлен)\b",
        r"\b(?:мигрант\w*|миграц\w*)\b.{0,80}\b(?:сократ\w*|сниз\w*|уменьш\w*|вырос\w*|увелич\w*|рост\w*|камай\w*|ош\w*)\b",
        r"\b(?:сократ\w*|сниз\w*|уменьш\w*|вырос\w*|увелич\w*|камай\w*|ош\w*)\b.{0,80}\b(?:мигрант\w*|миграц\w*)\b",
        r"\b(?:мигрант\w*|муҳожир\w*)\b.{0,90}\b(?:оқим\w*|поток\w*)\b.{0,60}\b(?:ош\w*|камай\w*|вырос\w*|увелич\w*|сниз\w*)\b",
        r"\b(?:оқим\w*|поток\w*)\b.{0,90}\b(?:ош\w*|камай\w*|вырос\w*|увелич\w*|сниз\w*)\b.{0,60}\b(?:мигрант\w*|муҳожир\w*)\b",

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

    # ------------------------------------------------------
    # ACTUALITY / ASSERTION EVIDENCE
    # ------------------------------------------------------

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

    # Concrete real-world action forms. Gerunds such as "migrants crossing"
    # are deliberately NOT enough on their own because they frequently appear
    # in policy debate or hypothetical statements.
    EVENT_ASSERTION_PATTERNS = (
        # English
        r"\b(?:migrants?|refugees?)\s+(?:have\s+)?(?:arrived|crossed|entered|reached|gathered|departed|left)\b",
        r"\b(?:arrived|crossed|entered|reached|gathered|departed|left)\b.{0,80}\b(?:migrants?|refugees?)\b",
        r"\b(?:were|was|have\s+been|has\s+been)\s+(?:intercepted|detained|arrested|rescued|deported|expelled|returned)\b",
        r"\b(?:police|border\s+guards?|coast\s+guard|authorities)\b.{0,100}\b(?:detained|arrested|intercepted|rescued|deported|returned|expelled)\b",
        r"\b(?:raid|operation)\s+(?:was\s+)?(?:conducted|carried\s+out|took\s+place)\b",

        # Spanish / French / Italian
        r"\b(?:migrantes?|refugiados?)\b.{0,80}\b(?:llegaron|cruzaron|entraron|alcanzaron|salieron|partieron)\b",
        r"\b(?:fueron|han\s+sido)\s+(?:detenid\w*|interceptad\w*|rescatad\w*|expulsad\w*|deportad\w*)\b",
        r"\b(?:migrants?|r[ée]fugi[ée]s?)\b.{0,80}\b(?:sont\s+arriv[ée]s|ont\s+travers[ée]|ont\s+quitt[ée])\b",
        r"\b(?:ont\s+[ée]t[ée]|a\s+[ée]t[ée])\s+(?:arr[êe]t[ée]\w*|intercept[ée]\w*|expuls[ée]\w*|secour\w*)\b",
        r"\b(?:migranti|rifugiati)\b.{0,80}\b(?:sono\s+arrivati|hanno\s+attraversato|sono\s+entrati|sono\s+partiti)\b",

        # Russian / CIS
        r"\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b.{0,110}\b(?:прибыли|прибыв\w*|пересек\w*|въех\w*|выех\w*|задерж\w*|выдвор\w*|депорт\w*)\b",
        r"\b(?:задерж\w*|выдвор\w*|депорт\w*|перехват\w*|рейд\w*)\b.{0,110}\b(?:мигрант\w*|бежен\w*|муҳожир\w*)\b",
        r"\b(?:рейд\w*).{0,140}\b(?:полици\w*|мигрант\w*|муҳожир\w*)\b",
        r"\b(?:полици\w*|миграционн\w*|пограничн\w*)\b.{0,150}\b(?:провер\w*|задерж\w*|рейд\w*)\b.{0,150}\b(?:мигрант\w*|муҳожир\w*|иностранц\w*)\b",
        r"\b(?:мигрант\w*|муҳожир\w*|иностранц\w*|хорижлик\w*|чет\s+эл\s+фуқарос\w*|фуқаро\w*)\b.{0,160}\b(?:провер\w*|текшир\w*|задерж\w*|выдвор\w*|депорт\w*|қайтарил\w*|чиқариб\s+юборил\w*)\b",
        r"\b(?:миграция\s+рейд\w*|миграция\s+текширув\w*)\b.{0,180}\b(?:фуқаро\w*|мигрант\w*|хорижлик\w*)\b",
        r"\b(?:чартерн\w*.{0,40}рейс\w*|чартер\s+рейс\w*|махсус\s+чартер\s+рейс\w*)\b.{0,180}\b(?:возвращ\w*|депорт\w*|выдвор\w*|қайтар\w*)\b",

        # Arabic
        r"(?:مهاجر|لاجئ).{0,100}(?:وصل|عبر|دخل|غادر|اعتقل|احتجز|رحل|أبعد)",
        r"(?:اعتقال|احتجاز|ترحيل|إبعاد|اعتراض|إنقاذ|كبسة).{0,120}(?:مهاجر|لاجئ)",
    )

    QUANTITATIVE_PATTERNS = (
        r"\b\d{2,6}\b",
        r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|per\s+cent)\b",
        r"\b(?:dozens?|hundreds?|thousands?)\b",
        r"\b(?:decenas|cientos|miles)\b",
        r"\b(?:десятки|сотни|тысячи)\b",
        r"(?:عشرات|مئات|آلاف)",
    )

    TREND_COMPARISON_PATTERNS = (
        r"\b(?:year[-\s]on[-\s]year|compared\s+with|compared\s+to|versus|vs\.?|from\s+last\s+year|since\s+last\s+year)\b",
        r"\b(?:respecto\s+al\s+año\s+pasado|en\s+comparaci[oó]n\s+con|interanual)\b",
        r"\b(?:par\s+rapport\s+[àa]|sur\s+un\s+an)\b",
        r"\b(?:rispetto\s+all['’]anno\s+scorso|su\s+base\s+annua)\b",
        r"\b(?:по\s+сравнению\s+с|год\s+к\s+году|за\s+год|ўтган\s+йил|нисбатан)\b",
        r"(?:مقارنة بالعام الماضي|على أساس سنوي)",
    )

    # ------------------------------------------------------
    # MIGRATION-SPECIFIC ENFORCEMENT CONTEXT
    # ------------------------------------------------------

    MIGRATION_ENFORCEMENT_PATTERNS = (
        r"\b(?:immigration|migration|border|asylum)\s+(?:raid|operation|enforcement|police|officers?|authorities)\b",
        r"\b(?:ICE|Border\s+Patrol|border\s+guards?|coast\s+guard|immigration\s+officers?)\b",
        r"\b(?:illegal|irregular|undocumented)\s+(?:migrants?|immigrants?|entry|stay|crossing)\b",
        r"\b(?:deportation|removal|expulsion|return)\s+(?:order|flight|operation|of\s+migrants?)\b",
        r"\b(?:migrants?|refugees?)\b.{0,100}\b(?:deported|expelled|returned|removed|intercepted|detained\s+for\s+illegal\s+entry)\b",

        r"\b(?:migraci[oó]n|frontera|extranjer[ií]a)\b.{0,80}\b(?:operativo|redada|control|polic[ií]a)\b",
        r"\b(?:migrantes?|inmigrantes?)\b.{0,100}\b(?:expulsad\w*|deportad\w*|interceptad\w*|devuelt\w*)\b",

        r"\b(?:миграционн\w*|пограничн\w*)\b.{0,100}\b(?:рейд\w*|контрол\w*|полици\w*|провер\w*)\b",
        r"\b(?:нелегальн\w*|незаконн\w*)\b.{0,50}\b(?:мигрант\w*|пребыван\w*|въезд\w*)\b",
        r"\b(?:мигрант\w*|муҳожир\w*)\b.{0,100}\b(?:выдвор\w*|депорт\w*|провер\w*.{0,30}документ)\b",

        r"(?:شرطة الهجرة|حرس الحدود|خفر السواحل|هجرة غير شرعية|مهاجر غير شرعي|ترحيل المهاجرين|إبعاد المهاجرين)",
    )

    STRONG_MIGRATION_ENFORCEMENT_PATTERNS = (
        r"\b(?:immigration|migration|border|asylum)\s+(?:raid|operation|enforcement|police|officers?|authorities)\b",
        r"\b(?:illegal|irregular|undocumented)\s+(?:migrants?|immigrants?|entry|stay|crossing)\b",
        r"\b(?:deportation|removal|return|repatriation)\s+(?:flight|operation|order)\b",
        r"\b(?:миграционн\w*|пограничн\w*)\b.{0,120}\b(?:рейд\w*|контрол\w*|полици\w*|провер\w*)\b",
        r"\b(?:нелегальн\w*|незаконн\w*)\b.{0,60}\b(?:мигрант\w*|пребыван\w*|въезд\w*)\b",
        r"\b(?:рейд\w*|провер\w*)\b.{0,150}\b(?:мигрант\w*|муҳожир\w*|иностранц\w*)\b",
        r"\b(?:чартерн\w*.{0,40}рейс\w*|чартер\s+рейс\w*|махсус\s+чартер\s+рейс\w*)\b.{0,180}\b(?:возвращ\w*|депорт\w*|выдвор\w*|қайтар\w*)\b",
        r"(?:شرطة الهجرة|حرس الحدود|خفر السواحل|هجرة غير شرعية|ترحيل المهاجرين|إبعاد المهاجرين)",
    )

    HISTORICAL_YEAR_PATTERN = r"\b(?:19|20)\d{2}\b"

    # ------------------------------------------------------
    # REJECTION / DOWN-RANKING CONTEXT
    # ------------------------------------------------------

    COMMENTARY_PATTERNS = (
        r"\b(?:opinion|commentary|analysis|explainer|essay|debate)\b",
        r"\b(?:according\s+to\s+my\s+opinion|i\s+think|i\s+believe)\b",
        r"\b(?:мнение|аналитик\w*|считаю|думаю)\b",
        r"\b(?:opinión|analisis|análisis)\b",
    )


    POLICY_CONTEXT_PATTERNS = (
        r"\b(?:policy|law|legislation|pact|proposal|rules?|regulations?|government\s+plan)\b",
        r"\b(?:migration|asylum)\s+(?:policy|pact|rules?|law|legislation)\b",
        r"\b(?:қонун\w*|қоида\w*|пакт\w*|сиёсат\w*|таклиф\w*|чора\w*)\b",
        r"\b(?:закон\w*|политик\w*|пакт\w*|правил\w*|предложен\w*|мер\w*)\b",
        r"(?:قانون|سياسة|قواعد|اتفاق|مقترح|إجراءات)",
    )

    POLICY_INTENT_PRESSURE_PATTERNS = (
        r"\b(?:goal|aim|objective|purpose)\b.{0,120}\b(?:reduce|decrease|limit|curb)\b.{0,80}\b(?:migration|migrants?|immigration)\b",
        r"\b(?:reduce|decrease|limit|curb)\b.{0,80}\b(?:migration|migrants?|immigration)\b.{0,120}\b(?:policy|goal|aim|measure|deportation)\b",
        r"\b(?:мақсад\w*)\b.{0,140}\b(?:миграция\w*|мигрант\w*)\b.{0,100}\b(?:камайтир\w*|чекла\w*)\b",
        r"\b(?:миграция\w*|мигрант\w*)\b.{0,100}\b(?:камайтир\w*|чекла\w*)\b.{0,120}\b(?:мақсад\w*|депортация\w*|чора\w*)\b",
        r"\b(?:депортация\w*)\b.{0,80}\b(?:осонлаштир\w*|енгиллаштир\w*)\b",
        r"\b(?:цель|задача)\b.{0,140}\b(?:сниз\w*|сократ\w*|огранич\w*)\b.{0,80}\b(?:миграц\w*|мигрант\w*)\b",
        r"\b(?:сниз\w*|сократ\w*|огранич\w*)\b.{0,80}\b(?:миграц\w*|мигрант\w*)\b.{0,120}\b(?:цель|мера|депортац\w*)\b",
        r"(?:الهدف|الغرض).{0,120}(?:خفض|تقليل|الحد من).{0,80}(?:الهجرة|المهاجرين)",
    )

    NON_FLOW_PRESSURE_PATTERNS = (
        r"\b(?:number|capacity|use|usage)\s+of\s+(?:deportation|detention|reception|migration)\s+(?:centres?|centers?|facilities?)\b",
        r"\b(?:deportation|detention|reception|migration)\s+(?:centres?|centers?|facilities?)\b.{0,100}\b(?:increas\w*|expand\w*|grow\w*)\b",
        r"\b(?:депортационн\w*|миграционн\w*)\s+(?:центр\w*|лагер\w*)\b.{0,100}\b(?:увелич\w*|расшир\w*|вырос\w*)\b",
        r"\b(?:депортация|миграция)\s+марказ\w*\b.{0,100}\b(?:сон\w*|фойдаланиш\w*)\b.{0,100}\b(?:ош\w*|кенгайтир\w*)\b",
        r"\b(?:марказ\w*|центр\w*)\b.{0,100}\b(?:оширил\w*|увелич\w*|кенгайтир\w*|расшир\w*)\b",
        r"(?:مراكز الترحيل|مراكز الاحتجاز|مراكز الاستقبال).{0,100}(?:زيادة|توسيع)",
    )

    SYSTEMIC_ENFORCEMENT_PATTERNS = (
        r"\b(?:raid|sweep|operation|checkpoint|mass\s+deportation|deportation\s+flight)\b",
        r"\b(?:dozens?|hundreds?|thousands?)\b.{0,100}\b(?:migrants?|immigrants?|foreigners?)\b",
        r"\b(?:рейд\w*|облав\w*|операци\w*|массов\w*.{0,40}(?:выдвор\w*|депорт\w*))\b",
        r"\b(?:миграция\s+рейд\w*|текширув\w*)\b",
        r"\b(?:ўнлаб|юзлаб|минглаб)\b.{0,100}\b(?:мигрант\w*|хорижлик\w*|фуқаро\w*)\b",
        r"(?:حملة|مداهمة|عملية|ترحيل جماعي|عشرات|مئات|آلاف)",
    )

    INDIVIDUAL_CASE_PATTERNS = (
        r"\b(?:a|one|single)\s+(?:migrant|immigrant|foreigner)\b",
        r"\b\d{1,2}[-\s]year[-\s]old\s+(?:migrant|immigrant|foreigner)\b",
        r"\b\d{1,2}\s+ёшли\s+мигрант\b",
        r"\b(?:бир|1)\s+нафар\s+(?:мигрант|хорижлик|фуқаро)\b",
        r"\b(?:один|одного|одному)\s+(?:мигрант\w*|иностранц\w*)\b",
    )

    NEGATED_ENFORCEMENT_PATTERNS = (
        r"\b(?:no|without|neither)\s+(?:deportation|removal|expulsion)\b",
        r"\b(?:was|were|is|are)\s+not\s+(?:deported|removed|expelled)\b",

        r"\bни\s+(?:депортаци\w*|выдворени\w*)\b",
        r"\bбез\s+(?:депортаци\w*|выдворени\w*)\b",
        r"\b(?:депортаци\w*|выдворени\w*)\s+не\s+(?:было|будет|произошло)\b",

        r"\b(?:депортация|чиқариб\s+юбориш)\s+(?:бўлмади|қилинмади|йўқ)\b",

        r"\b(?:sin|ninguna)\s+(?:deportaci[oó]n|expulsi[oó]n)\b",
        r"\bsans\s+(?:expulsion|déportation)\b",

        r"(?:لم يتم ترحيل|دون ترحيل|لا يوجد ترحيل)",
    )

    CRIMINAL_SENTENCE_DEPORTATION_PATTERNS = (
        r"\b(?:faces?|could\s+face|may\s+face|risks?|could\s+receive)\b.{0,120}\b(?:prison|jail|sentence)\b.{0,120}\b(?:deportation|removal|expulsion)\b",
        r"\b(?:prison|jail|sentence)\b.{0,120}\b(?:with|and)\s+(?:deportation|removal|expulsion)\b",

        r"\b(?:грозит|светит|может\s+получить|приговорен\w*)\b.{0,160}\b(?:тюрьм\w*|срок\w*|лишени\w+\s+свобод\w*)\b.{0,140}\b(?:депортаци\w*|выдворени\w*)\b",
        r"\b(?:тюрьм\w*|срок\w*|лишени\w+\s+свобод\w*)\b.{0,120}\b(?:с\s+депортаци\w*|и\s+депортаци\w*)\b",

        r"\b(?:prisi[oó]n|condena)\b.{0,120}\b(?:con|y)\s+(?:deportaci[oó]n|expulsi[oó]n)\b",

        r"(?:السجن|عقوبة بالسجن).{0,120}(?:والترحيل|مع الترحيل)",
    )

    AMBIGUOUS_AUTHORITY_ACTION_PATTERNS = (
        # Concrete authority action in a migration-related text, but without
        # enough evidence to label it an operational immigration raid.
        r"\b(?:police|officers?|authorities)\b.{0,160}\b(?:took|removed|escorted|led|brought)\b.{0,100}\b(?:two|three|several|\d+)\b",

        r"\b(?:полици\w*|полицейск\w*)\b.{0,180}\b(?:вывел\w*|увез\w*|забрал\w*|сопровод\w*|достав\w*)\b.{0,100}\b(?:двоих|троих|нескольк\w*|\d+)\b",
        r"\b(?:двоих|троих|нескольк\w*|\d+)\b.{0,120}\b(?:вывел\w*|увез\w*|забрал\w*|достав\w*)\b.{0,120}\b(?:полици\w*|полицейск\w*)\b",
    )

    SPECULATIVE_PATTERNS = (
        r"\b(?:could|would|should|might|may)\b",
        r"\b(?:believe|believes|believed)\b.{0,80}\b(?:would|could|might|migrants?\s+crossing)\b",
        r"\b(?:proposal|proposed|plan\s+to|plans\s+to|would\s+ban|would\s+allow)\b",
        r"\b(?:if\s+migrants?|if\s+refugees?)\b",
        r"\b(?:deber[ií]a|podr[ií]a|propuesta)\b",
        r"\b(?:должн\w*|мог\w*\s+бы|предлага\w*)\b",
    )

    HYPOTHETICAL_POLICY_EXAMPLE_PATTERNS = (
        r"\bthere\s+should\s+be\b",
        r"\bthere\s+ought\s+to\s+be\b",
        r"\bfor\s+example\b",
        r"\bfor\s+instance\b",
        r"\bi\s+would\b",
        r"\bwe\s+should\b",
        r"\bthey\s+should\b",
        r"\bshould\s+then\b",
        r"\bimagine\s+(?:that|if)\b",
        r"\bsuppose\s+(?:that|if)\b",
        r"\blet['’]s\s+say\b",
        r"\b(?:deber[ií]a|deberían|por\s+ejemplo)\b",
        r"\b(?:должн\w*\s+бы|например)\b",
    )

    # Generic credibility gate for highly implausible/parodic logistics claims.
    # It is deliberately narrow: one odd phrase is not enough. A window must
    # contain at least TWO independent cues.
    IMPLAUSIBILITY_PATTERNS = (
        r"\bhalf[-\s]?kilomet(?:er|re)\b.{0,80}\b(?:dinghy|boat|vessel)\b",
        r"\b(?:500|1,000|1000)\s*(?:metres?|meters?)\b.{0,80}\b(?:dinghy|boat|vessel|inflatable)\b",
        r"\bkilomet(?:er|re)[-\s]long\b.{0,80}\b(?:dinghy|boat|vessel|model)\b",
        r"\b(?:coffee\s+kiosk|selfie\s+booth|premium\s+passenger\s+experience|starlink\s+wi[- ]?fi)\b",
        r"\bcommercial\s+social\s+experience\s+of\s+hardship\s+and\s+fun\b",
        r"\burgent\s+talks\b.{0,60}\bsometime\s+next\s+year\b",
    )

    HISTORICAL_NARRATIVE_PATTERNS = (
        r"\b(?:book|chapter|history|historical|century|dynasty|empire|colonial|treaty)\b",
        r"\b(?:in\s+the\s+18\d{2}s|in\s+the\s+19\d{2}s|in\s+the\s+20th\s+century)\b",
        r"\b(?:libro|cap[ií]tulo|historia|hist[oó]rico|siglo|dinast[ií]a|imperio|colonial)\b",
        r"\b(?:livre|chapitre|histoire|historique|si[èe]cle|empire|colonial)\b",
        r"\b(?:книг\w*|глав\w*|истори\w*|век\w*|импери\w*|колони\w*)\b",
    )

    GENERIC_CRIME_PATTERNS = (
        r"\b(?:assault|murder|rape|robbery|arson|fight|stabbing|stabbed|shooting|drug\s+trafficking|drug\s+smuggling|pills?|narcotics?|terror\s+attack)\b",
        r"\b(?:напал|убил|изнасил|ограб|драк|поджог|теракт|наркотик|украл|украли|краж\w*|воров\w*|мошеннич\w*|осудил\w*)\w*",
        r"\b(?:жиноят\w*|фирибгар\w*|ўғир\w*|зўравон\w*|пора\w*|взятк\w*)\b",
        r"\b(?:bribe|bribery|corruption)\b",
        r"\b(?:agresi[oó]n|asesin|violaci[oó]n|robo|pelea|apuñal|drogas?)\w*",
    )

    NON_HUMAN_TRAFFICKING_PATTERNS = (
        r"\b(?:drug|drugs|pills?|narcotics?|cocaine|heroin|meth|fentanyl)\b.{0,80}\b(?:traffick\w*|smuggl\w*)\b",
        r"\b(?:traffick\w*|smuggl\w*)\b.{0,80}\b(?:drug|drugs|pills?|narcotics?|cocaine|heroin|meth|fentanyl)\b",
        r"\b(?:wildlife|lizard|lizards|animal|animals|weapons?|guns?|cigarettes?|tobacco|goods)\b.{0,80}\b(?:traffick\w*|smuggl\w*)\b",
        r"\b(?:traffick\w*|smuggl\w*)\b.{0,80}\b(?:wildlife|lizard|lizards|animal|animals|weapons?|guns?|cigarettes?|tobacco|goods)\b",
    )

    # ------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------

    def detect(
        self,
        text: str,
    ) -> Dict[str, Any]:
        value = self._normalize_text(
            text
        )

        if not value:
            return self._empty()

        all_migration_matches = self._matches(
            value,
            self.MIGRATION_PATTERNS,
        )

        if not all_migration_matches:
            return self._empty(
                rejection_reason="NO_HUMAN_MIGRATION_CONTEXT"
            )

        # --------------------------------------------------
        # V1.3.6 DOCUMENT-LEVEL ENFORCEMENT PRECISION
        # --------------------------------------------------

        document_negated_enforcement = self._matches(
            value,
            self.NEGATED_ENFORCEMENT_PATTERNS,
        )

        document_criminal_sentence = self._matches(
            value,
            self.CRIMINAL_SENTENCE_DEPORTATION_PATTERNS,
        )

        document_generic_crime = self._matches(
            value,
            self.GENERIC_CRIME_PATTERNS,
        )

        document_strong_migration_enforcement = self._matches(
            value,
            self.STRONG_MIGRATION_ENFORCEMENT_PATTERNS,
        )

        # Explicitly negated removal is not an enforcement warning.
        if (
            document_negated_enforcement
            and not document_strong_migration_enforcement
        ):
            return self._empty(
                migration_context=True,
                context_matches=all_migration_matches,
                rejection_reason="NEGATED_ENFORCEMENT_NOT_EARLY_WARNING",
            )

        # A deportation mentioned only as an additional/possible criminal
        # sentence is ordinary criminal justice, not migration enforcement.
        if (
            document_criminal_sentence
            and document_generic_crime
            and not document_strong_migration_enforcement
        ):
            return self._empty(
                migration_context=True,
                context_matches=all_migration_matches,
                rejection_reason="CRIMINAL_SENTENCE_NOT_MIGRATION_ENFORCEMENT",
            )

        # A concrete police intervention can still be analytically useful even
        # when the text does not prove that it was an immigration raid.
        # Surface it only for analyst review, never as an operational event.
        document_ambiguous_authority_action = self._matches(
            value,
            self.AMBIGUOUS_AUTHORITY_ACTION_PATTERNS,
        )

        if (
            document_ambiguous_authority_action
            and not document_generic_crime
            and not document_negated_enforcement
        ):
            return {
                "detected": True,
                "primary_signal": "ENFORCEMENT_EARLY_WARNING",
                "signal_mode": "ANALYST_REVIEW",
                "signal_intent": "ENFORCEMENT_EARLY_WARNING",
                "confidence": 0.62,
                "score": 5.25,
                "matched_signals": [
                    "ENFORCEMENT_EARLY_WARNING",
                ],
                "matched_phrases": [
                    [
                        "enforcement",
                        value,
                    ],
                ],
                "matched_groups": [
                    "ENFORCEMENT",
                ],
                "context_matches":
                    all_migration_matches,
                "high_value_matches":
                    document_ambiguous_authority_action,
                "signal_context_rejections": [],
                "migration_context": True,
                "human_migration_context": True,
                "historical_reference": False,
                "historical_reason": None,
                "historical_reference_text": None,
                "rules_version":
                    self.RULES_VERSION,
                "current_cues": [],
                "quantitative_cues": [],
                "event_assertion_cues":
                    document_ambiguous_authority_action,
                "trend_comparison_cues": [],
                "actuality_gate_passed": True,
                "actuality_reason":
                    "CONCRETE_AUTHORITY_ACTION_REQUIRES_REVIEW",
                "evidence_window":
                    value,
                "review_reason":
                    "STRUCTURED_MIGRATION_EARLY_WARNING",
            }

        # Document-level credibility check for very narrow, compound
        # implausibility patterns. This is intentionally evaluated before
        # local-window scoring because a satirical article may place the
        # absurd claim and the otherwise-real migration sentence in adjacent
        # windows. Two independent implausibility cues are required.
        document_implausibility_matches = self._matches(
            value,
            self.IMPLAUSIBILITY_PATTERNS,
        )

        if len(
            document_implausibility_matches
        ) >= 2:
            return self._empty(
                migration_context=True,
                context_matches=all_migration_matches,
                rejection_reason="LOW_CREDIBILITY_IMPLAUSIBLE_CLAIM"
            )

        windows = self._build_windows(
            value
        )

        candidates = []

        for index, window in enumerate(
            windows
        ):
            candidate = self._score_window(
                window
            )

            if candidate is None:
                continue

            candidate[
                "window_index"
            ] = index

            candidates.append(
                candidate
            )

        if not candidates:
            return self._empty(
                migration_context=True,
                context_matches=all_migration_matches,
                rejection_reason="NO_LOCAL_EVENT_STRUCTURE"
            )

        candidates.sort(
            key=lambda item: (
                bool(
                    item.get(
                        "actuality_gate_passed"
                    )
                ),
                float(
                    item.get(
                        "score",
                        0.0,
                    )
                ),
                len(
                    item.get(
                        "matched_groups",
                        [],
                    )
                ),
            ),
            reverse=True,
        )

        best = candidates[
            0
        ]

        # Classification tie-break:
        # if any LOCAL evidence window independently passes the actuality gate
        # and contains FACILITATION, prefer the strongest such window.
        #
        # This prevents a nearby enforcement/movement sentence from masking
        # the analytically more specific smuggling/facilitation signal in
        # multilingual Telegram posts. It does NOT relax detection.
        facilitation_candidates = [
            item
            for item
            in candidates
            if (
                item.get(
                    "actuality_gate_passed"
                )
                and "FACILITATION"
                in item.get(
                    "matched_groups",
                    [],
                )
            )
        ]

        if facilitation_candidates:
            facilitation_candidates.sort(
                key=lambda item: (
                    float(
                        item.get(
                            "score",
                            0.0,
                        )
                    ),
                    len(
                        item.get(
                            "matched_groups",
                            [],
                        )
                    ),
                ),
                reverse=True,
            )

            best_facilitation = (
                facilitation_candidates[
                    0
                ]
            )

            # Keep the original highest-score candidate if facilitation is
            # substantially weaker. The 2.0-point tolerance is only a
            # classification preference, not a threshold reduction.
            if (
                float(
                    best_facilitation.get(
                        "score",
                        0.0,
                    )
                )
                >= float(
                    best.get(
                        "score",
                        0.0,
                    )
                )
                - 2.0
            ):
                best = best_facilitation

        detected = bool(
            best.get(
                "actuality_gate_passed"
            )
            and float(
                best.get(
                    "score",
                    0.0,
                )
            )
            >= self.MIN_SCORE
        )

        primary_signal = (
            self._primary_signal(
                best.get(
                    "matched_groups",
                    [],
                )
            )
            if detected
            else None
        )

        confidence = (
            self._confidence(
                float(
                    best.get(
                        "score",
                        0.0,
                    )
                )
            )
            if detected
            else 0.35
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
                    float(
                        best.get(
                            "score",
                            0.0,
                        )
                    ),
                    2,
                ),
            "matched_signals":
                [
                    primary_signal
                ]
                if detected
                else [],
            "matched_phrases":
                best.get(
                    "matched_phrases",
                    [],
                ),
            "matched_groups":
                best.get(
                    "matched_groups",
                    [],
                ),
            "context_matches":
                best.get(
                    "migration_matches",
                    [],
                ),
            "high_value_matches":
                best.get(
                    "high_value_matches",
                    [],
                ),
            "signal_context_rejections":
                best.get(
                    "rejection_matches",
                    [],
                ),
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
                best.get(
                    "current_matches",
                    [],
                ),
            "quantitative_cues":
                best.get(
                    "quantitative_matches",
                    [],
                ),
            "event_assertion_cues":
                best.get(
                    "event_assertion_matches",
                    [],
                ),
            "trend_comparison_cues":
                best.get(
                    "trend_comparison_matches",
                    [],
                ),
            "actuality_gate_passed":
                bool(
                    best.get(
                        "actuality_gate_passed"
                    )
                ),
            "actuality_reason":
                best.get(
                    "actuality_reason"
                ),
            "evidence_window":
                best.get(
                    "window",
                    ""
                ),
            "review_reason":
                (
                    "STRUCTURED_MIGRATION_EARLY_WARNING"
                    if detected
                    else (
                        best.get(
                            "actuality_reason"
                        )
                        or "BELOW_EARLY_WARNING_THRESHOLD"
                    )
                ),
        }

    # ------------------------------------------------------
    # LOCAL WINDOW SCORING
    # ------------------------------------------------------

    def _score_window(
        self,
        window: str,
    ) -> Dict[str, Any] | None:
        migration_matches = self._matches(
            window,
            self.MIGRATION_PATTERNS,
        )

        if not migration_matches:
            return None

        groups = {
            "MOVEMENT": self._matches(
                window,
                self.MOVEMENT_PATTERNS,
            ),
            "ROUTE": self._matches(
                window,
                self.ROUTE_PATTERNS,
            ),
            "FACILITATION": self._matches(
                window,
                self.FACILITATION_PATTERNS,
            ),
            "ENFORCEMENT": self._matches(
                window,
                self.ENFORCEMENT_PATTERNS,
            ),
            "PRESSURE": self._matches(
                window,
                self.PRESSURE_PATTERNS,
            ),
            "POLICY_ACCESS": self._matches(
                window,
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
            return None

        current_matches = self._matches(
            window,
            self.CURRENT_PATTERNS,
        )
        event_assertion_matches = self._matches(
            window,
            self.EVENT_ASSERTION_PATTERNS,
        )
        quantitative_matches = self._matches(
            window,
            self.QUANTITATIVE_PATTERNS,
        )
        trend_comparison_matches = self._matches(
            window,
            self.TREND_COMPARISON_PATTERNS,
        )

        commentary_matches = self._matches(
            window,
            self.COMMENTARY_PATTERNS,
        )

        policy_context_matches = self._matches(
            window,
            self.POLICY_CONTEXT_PATTERNS,
        )

        policy_intent_pressure_matches = self._matches(
            window,
            self.POLICY_INTENT_PRESSURE_PATTERNS,
        )

        non_flow_pressure_matches = self._matches(
            window,
            self.NON_FLOW_PRESSURE_PATTERNS,
        )

        systemic_enforcement_matches = self._matches(
            window,
            self.SYSTEMIC_ENFORCEMENT_PATTERNS,
        )

        individual_case_matches = self._matches(
            window,
            self.INDIVIDUAL_CASE_PATTERNS,
        )
        speculative_matches = self._matches(
            window,
            self.SPECULATIVE_PATTERNS,
        )

        hypothetical_policy_matches = self._matches(
            window,
            self.HYPOTHETICAL_POLICY_EXAMPLE_PATTERNS,
        )

        implausibility_matches = self._matches(
            window,
            self.IMPLAUSIBILITY_PATTERNS,
        )

        historical_matches = self._matches(
            window,
            self.HISTORICAL_NARRATIVE_PATTERNS,
        )
        generic_crime_matches = self._matches(
            window,
            self.GENERIC_CRIME_PATTERNS,
        )

        non_human_trafficking_matches = self._matches(
            window,
            self.NON_HUMAN_TRAFFICKING_PATTERNS,
        )

        migration_enforcement_matches = self._matches(
            window,
            self.MIGRATION_ENFORCEMENT_PATTERNS,
        )

        strong_migration_enforcement_matches = self._matches(
            window,
            self.STRONG_MIGRATION_ENFORCEMENT_PATTERNS,
        )

        historical_years = self._historical_years(
            window
        )

        recent_date_cues = self._recent_date_cues(
            window
        )

        # Policy intent is not migration pressure.
        # Keep enforcement/policy-access context, but remove PRESSURE unless
        # the text reports an actual measured/explicit migration-flow trend.
        if (
            "PRESSURE"
            in matched_groups
            and (
                policy_context_matches
                or policy_intent_pressure_matches
                or non_flow_pressure_matches
            )
            and not (
                quantitative_matches
                and trend_comparison_matches
            )
            and not self._matches(
                window,
                (
                    r"\b(?:migrant|migration|refugee)\w*\b.{0,90}\b(?:increasing|rising|decreasing|declining|growing|falling)\b",
                    r"\b(?:мигрант\w*|муҳожир\w*)\b.{0,90}\b(?:оқим\w*|поток\w*)\b.{0,60}\b(?:ош\w*|камай\w*|вырос\w*|увелич\w*|сниз\w*)\b",
                ),
            )
        ):
            matched_groups = [
                group
                for group in matched_groups
                if group != "PRESSURE"
            ]
            groups["PRESSURE"] = []

        actuality_gate_passed = False
        actuality_reason = "NO_CURRENT_EVENT_EVIDENCE"

        # Strongest gate: explicit real-world action.
        if event_assertion_matches:
            actuality_gate_passed = True
            actuality_reason = "CONCRETE_EVENT_ASSERTION"

        # Quantified pressure/trend can be useful early warning even if it is
        # not an operational incident.
        elif (
            "PRESSURE"
            in matched_groups
            and quantitative_matches
            and trend_comparison_matches
        ):
            actuality_gate_passed = True
            actuality_reason = "QUANTIFIED_MIGRATION_TREND"

        # Concise asserted migration-flow trend. Useful for short Telegram
        # statements that report a current increase/decrease without a number.
        elif (
            "PRESSURE"
            in matched_groups
            and self._matches(
                window,
                (
                    r"\b(?:migrant|migration|refugee)\w*\b.{0,90}\b(?:increasing|rising|decreasing|declining|growing|falling)\b",
                    r"\b(?:мигрант\w*|муҳожир\w*)\b.{0,90}\b(?:оқим\w*|поток\w*)\b.{0,60}\b(?:ош\w*|камай\w*|вырос\w*|увелич\w*|сниз\w*)\b",
                    r"\b(?:оқим\w*|поток\w*)\b.{0,90}\b(?:ош\w*|камай\w*|вырос\w*|увелич\w*|сниз\w*)\b",
                ),
            )
            and not speculative_matches
            and not historical_matches
        ):
            actuality_gate_passed = True
            actuality_reason = "ASSERTED_MIGRATION_FLOW_TREND"

        # Current cue + strong action class. Route alone is not enough.
        elif (
            current_matches
            and any(
                group in matched_groups
                for group in (
                    "MOVEMENT",
                    "FACILITATION",
                    "ENFORCEMENT",
                    "PRESSURE",
                    "POLICY_ACCESS",
                )
            )
        ):
            actuality_gate_passed = True
            actuality_reason = "CURRENT_STRUCTURED_MIGRATION_SIGNAL"

        # A current-year dated quantitative movement report can be a useful
        # early-warning signal even without words such as "today". Example:
        # "13,687 migrants arrived in Yemen in July 2026."
        elif (
            recent_date_cues
            and quantitative_matches
            and any(
                group in matched_groups
                for group in (
                    "MOVEMENT",
                    "PRESSURE",
                    "ENFORCEMENT",
                )
            )
        ):
            actuality_gate_passed = True
            actuality_reason = "RECENT_DATED_QUANTIFIED_MIGRATION_SIGNAL"

        # Strong facilitation or enforcement reporting can be useful even
        # without an explicit "today" token, but only when it is framed as
        # concrete activity rather than generic discussion.
        elif (
            any(
                group in matched_groups
                for group in (
                    "FACILITATION",
                    "ENFORCEMENT",
                )
            )
            and not speculative_matches
            and not historical_matches
            and quantitative_matches
        ):
            actuality_gate_passed = True
            actuality_reason = "CONCRETE_ACTION_WITH_QUANTITY"

        # Historical/narrative material cannot pass without a concrete event
        # assertion in the same local window.
        if (
            historical_matches
            and not event_assertion_matches
        ):
            actuality_gate_passed = False
            actuality_reason = "HISTORICAL_OR_NARRATIVE_CONTEXT"

        # Hypothetical / proposal language blocks weak movement/route claims
        # unless a separate concrete event assertion is present.
        if (
            speculative_matches
            and not event_assertion_matches
            and not (
                "PRESSURE"
                in matched_groups
                and quantitative_matches
                and trend_comparison_matches
            )
        ):
            actuality_gate_passed = False
            actuality_reason = "SPECULATIVE_OR_POLICY_DEBATE"

        # Explicit old-year references are a strong retrospective cue.
        # A current cue or a clearly separate current-event assertion is
        # required to override this gate.
        if (
            historical_years
            and not current_matches
        ):
            actuality_gate_passed = False
            actuality_reason = "EXPLICIT_HISTORICAL_YEAR"

        # Ordinary crime committed by a migrant is not migration enforcement.
        if (
            "ENFORCEMENT"
            in matched_groups
            and generic_crime_matches
            and not strong_migration_enforcement_matches
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
            actuality_gate_passed = False
            actuality_reason = "ORDINARY_CRIME_NOT_MIGRATION_ENFORCEMENT"

        if (
            "ENFORCEMENT"
            in matched_groups
            and individual_case_matches
            and not systemic_enforcement_matches
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
            actuality_gate_passed = False
            actuality_reason = "INDIVIDUAL_CASE_NOT_SYSTEMIC_ENFORCEMENT"

        # Crime-rate statistics involving migrants are not migration-flow
        # pressure.
        if (
            "PRESSURE"
            in matched_groups
            and generic_crime_matches
            and not any(
                group in matched_groups
                for group in (
                    "MOVEMENT",
                    "ROUTE",
                    "FACILITATION",
                )
            )
        ):
            actuality_gate_passed = False
            actuality_reason = "CRIME_STATISTICS_NOT_MIGRATION_PRESSURE"

        # Drug / wildlife / goods trafficking is not migrant facilitation.
        # V1.3.1 uses proximity instead of poisoning the entire window:
        # a clean human-smuggling/facilitation phrase elsewhere in the same
        # article remains valid.
        if (
            "FACILITATION"
            in matched_groups
            and non_human_trafficking_matches
            and not self._has_clean_human_facilitation_context(
                window
            )
        ):
            actuality_gate_passed = False
            actuality_reason = "NON_HUMAN_TRAFFICKING_CONTEXT"

        # Policy examples and hypothetical constructions are not observations.
        if (
            hypothetical_policy_matches
            and not current_matches
            and not event_assertion_matches
        ):
            actuality_gate_passed = False
            actuality_reason = "HYPOTHETICAL_POLICY_EXAMPLE"

        # Narrow implausibility gate: require at least two separate cues.
        if len(
            implausibility_matches
        ) >= 2:
            actuality_gate_passed = False
            actuality_reason = "LOW_CREDIBILITY_IMPLAUSIBLE_CLAIM"

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

        if event_assertion_matches:
            score += 2.0

        if current_matches:
            score += 0.75

        if quantitative_matches:
            score += 0.75

        if trend_comparison_matches:
            score += 1.0

        if len(
            matched_groups
        ) >= 2:
            score += 1.0

        if commentary_matches:
            score -= min(
                2.0,
                0.75
                * len(
                    commentary_matches
                ),
            )

        if speculative_matches:
            score -= min(
                3.0,
                1.0
                * len(
                    speculative_matches
                ),
            )

        if historical_matches:
            score -= min(
                4.0,
                1.0
                * len(
                    historical_matches
                ),
            )

        if hypothetical_policy_matches:
            score -= min(
                3.0,
                1.0
                * len(
                    hypothetical_policy_matches
                ),
            )

        if implausibility_matches:
            score -= min(
                4.0,
                1.5
                * len(
                    implausibility_matches
                ),
            )

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

        rejection_matches = (
            commentary_matches
            + speculative_matches
            + hypothetical_policy_matches
            + implausibility_matches
            + historical_matches
            + generic_crime_matches
            + non_human_trafficking_matches
        )

        return {
            "window":
                window,
            "score":
                round(
                    score,
                    2,
                ),
            "matched_groups":
                matched_groups,
            "matched_phrases":
                matched_phrases,
            "migration_matches":
                migration_matches,
            "current_matches":
                current_matches,
            "event_assertion_matches":
                event_assertion_matches,
            "quantitative_matches":
                quantitative_matches,
            "trend_comparison_matches":
                trend_comparison_matches,
            "migration_enforcement_matches":
                migration_enforcement_matches,
            "strong_migration_enforcement_matches":
                strong_migration_enforcement_matches,
            "historical_years":
                historical_years,
            "recent_date_cues":
                recent_date_cues,
            "non_human_trafficking_matches":
                non_human_trafficking_matches,
            "hypothetical_policy_matches":
                hypothetical_policy_matches,
            "implausibility_matches":
                implausibility_matches,
            "high_value_matches":
                high_value_matches,
            "rejection_matches":
                rejection_matches,
            "actuality_gate_passed":
                actuality_gate_passed,
            "actuality_reason":
                actuality_reason,
        }

    # ------------------------------------------------------
    # WINDOW BUILDER
    # ------------------------------------------------------

    def _build_windows(
        self,
        text: str,
    ) -> List[str]:
        """
        Builds short local evidence windows.

        We first split on paragraph boundaries and sentence endings. Then we
        combine at most two neighboring units, capped at WINDOW_MAX_CHARS.
        This keeps related statements together while preventing distant
        paragraphs in long articles from accumulating unrelated signal groups.
        """

        raw_units = re.split(
            r"(?:\n{2,}|(?<=[.!?。！？])\s+)",
            text,
        )

        units = []

        for raw in raw_units:
            value = (
                raw.strip()
            )

            if not value:
                continue

            if len(
                value
            ) <= self.WINDOW_MAX_CHARS:
                units.append(
                    value
                )
                continue

            # Long sentence/paragraph: chunk conservatively with overlap.
            step = max(
                180,
                self.WINDOW_MAX_CHARS
                - 120,
            )

            start = 0

            while start < len(
                value
            ):
                chunk = value[
                    start:
                    start
                    + self.WINDOW_MAX_CHARS
                ].strip()

                if chunk:
                    units.append(
                        chunk
                    )

                start += step

        windows = []

        for index, unit in enumerate(
            units
        ):
            windows.append(
                unit
            )

            if (
                index
                + 1
                < len(
                    units
                )
            ):
                combined = (
                    unit
                    + " "
                    + units[
                        index
                        + 1
                    ]
                )

                if len(
                    combined
                ) <= self.WINDOW_MAX_CHARS:
                    windows.append(
                        combined
                    )

        # Stable de-duplication.
        seen = set()
        unique = []

        for window in windows:
            key = window.lower()

            if key in seen:
                continue

            seen.add(
                key
            )
            unique.append(
                window
            )

        return unique

    # ------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------

    def _has_clean_human_facilitation_context(
        self,
        text: str,
    ) -> bool:
        """
        Return True when at least one human-migration facilitation phrase has a
        local neighbourhood that is not contaminated by drug/wildlife/goods
        trafficking language.

        This prevents a long article mentioning both migrant smuggling and,
        much later, drug smuggling from being rejected as a whole.
        """

        candidate_patterns = (
            r"\b(?:human|people|migrant|migrants|refugee|refugees)\s+(?:smuggl\w*|traffick\w*)\b",
            r"\b(?:smuggl\w*|traffick\w*)\s+(?:of\s+)?(?:people|persons|migrants?|refugees?)\b",
            r"\b(?:people|migrant)\s+smugglers?\b",
            r"\b(?:fake\s+contract|false\s+document|forged\s+document|fake\s+passport|fake\s+passports)\b",
            r"\b(?:tr[aá]fico|trata)\s+de\s+(?:migrantes|personas)\b",
            r"\b(?:تهريب المهاجرين|مهربو المهاجرين|مهربين)\b",
        )

        for pattern in candidate_patterns:
            for match in re.finditer(
                pattern,
                text,
                flags=re.IGNORECASE
                | re.UNICODE,
            ):
                start = max(
                    0,
                    match.start()
                    - 140,
                )
                end = min(
                    len(text),
                    match.end()
                    + 140,
                )

                local = text[
                    start:end
                ]

                if not self._matches(
                    local,
                    self.NON_HUMAN_TRAFFICKING_PATTERNS,
                ):
                    return True

        return False

    def _recent_date_cues(
        self,
        text: str,
    ) -> List[str]:
        current_year = datetime.now(
            timezone.utc
        ).year

        patterns = (
            rf"\b{current_year}\b",
            rf"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+{current_year}\b",
            rf"\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+{current_year}\b",
        )

        return self._matches(
            text,
            patterns,
        )

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

            # Keep the current year and immediately previous year available
            # for recent-event context. Older explicit years are treated as
            # retrospective evidence.
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

    def _primary_signal(
        self,
        matched_groups: Sequence[str],
    ) -> str:
        priority = (
            (
                "FACILITATION",
                "FACILITATION_EARLY_WARNING",
            ),
            (
                "MOVEMENT",
                "MOVEMENT_EARLY_WARNING",
            ),
            (
                "PRESSURE",
                "PRESSURE_EARLY_WARNING",
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
    def _normalize_text(
        text: str,
    ) -> str:
        value = str(
            text
            or ""
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

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
            "event_assertion_cues":
                [],
            "trend_comparison_cues":
                [],
            "actuality_gate_passed":
                False,
            "actuality_reason":
                rejection_reason,
            "evidence_window":
                "",
            "review_reason":
                rejection_reason,
        }
