"""Migration relevance gate, globally applicable (no location whitelist).

This is a narrow false-positive filter, not a source-verification engine.
Historical genealogy and education-protest coverage should not create
operational migration alerts just because the word 'migration' appears.
"""
import re

_HISTORICAL = re.compile(r"\b(?:paliwal|rajputs?|gotra|ancestral|ancestry|lineage|genealogy|dynasty|medieval|ancient|historical migration|clan origins|centuries ago)\b", re.I)
_EDUCATION = re.compile(r"\b(?:student protests?|high schoolers?|school education|teacher shortages?|university admissions?|underfunded schools?|education funding|school buildings)\b", re.I)
_MIGRATION = re.compile(r"\b(?:migrants?|migration|immigration|refugees?|asylum|migrantes?|refugiados?|migranti|rifugiati|мигрант\w*|бежен\w*)\b|(?:مهاجر|لاجئ)", re.I)
_ACTUAL_MIGRATION = re.compile(
    r"\b(?:migrants?|refugees?|asylum seekers?|migrantes?|refugiados?|migranti|rifugiati)\b.{0,110}\b(?:arriv(?:ed|ing|al)|cross(?:ed|ing)|intercept(?:ed|ion)|rescu(?:ed|e)|detain(?:ed|ment)|deport(?:ed|ation)|expell(?:ed|ed)|land(?:ed|ing)|depart(?:ed|ure)|gather(?:ed|ing)|mobiliz(?:ed|ing)|mobilis(?:ed|ing))\b"
    r"|\b(?:rescu(?:ed|e)|intercept(?:ed|ion)|deport(?:ed|ation)|expell(?:ed|ed)|cross(?:ed|ing))\b.{0,110}\b(?:migrants?|refugees?|asylum seekers?|migrantes?|refugiados?)\b"
    r"|\b(?:immigration|migration|border|asylum)\s+(?:raid|enforcement|operation)\b"
    r"|\b(?:migrant|people|human)\s+smuggl\w*\b"
    r"|\b(?:anti[- ]immigration|anti[- ]migrant|pro[- ]migrant|migrant[- ]rights|refugee[- ]rights)\s+(?:protests?|rall(?:y|ies)|march(?:es)?|demonstrations?)\b"
    r"|\b(?:protests?|rall(?:y|ies)|march(?:es)?|demonstrations?)\s+(?:against|for|over)\s+(?:immigration|migration|migrants?|refugees?|asylum)\b",
    re.I | re.S,
)
_CURRENT_MIGRATION = re.compile(
    r"\b(?:today|yesterday|tonight|this week|last night|currently|breaking|just now)\b.{0,150}\b(?:migrants?|refugees?|asylum|immigration|border)\b"
    r"|\b(?:migrants?|refugees?|asylum|immigration|border)\b.{0,150}\b(?:today|yesterday|tonight|this week|last night|currently|breaking|just now)\b",
    re.I | re.S,
)


_NATURE = re.compile(r"\b(?:monarch butterflies?|butterflies?|butterfly migration|bird migration|migratory birds?|wildlife migration|animal migration|whales?|salmon migration|seasonal bird migration)\b", re.I)
_NATURE_CONTEXT = re.compile(r"\b(?:national park|birding|lake erie|wings?|species|habitat|favourable winds|autumn|trees|wildlife|insects?|butterflies?|monarchs)\b", re.I)
_FICTION = re.compile(r"\b(?:speculative fiction novel|fiction novel|fantasy novel|query crit|qcrit|first 300 words|chapter excerpt|fictional world|fictional kingdom|headcanon|fanfiction|fan fiction|worldbuilding|novel with series potential|kingdom rush|game lore|tower lore)\b", re.I)
_REAL_WORLD = re.compile(r"\b(?:police reported|border police|coast guard|frontex|iom reported|unhcr reported|according to authorities|rescue vessel|border crossing at|arrested by ice)\b", re.I)
_EDUCATION_CONTEXT = re.compile(r"\b(?:student protests?|school protests?|school education|teacher shortages?|university admissions?|underfunded schools?|education funding|school buildings|high schoolers?|protesteerders|leerlingen|docenten|school protesten)\b", re.I)
_MIGRATION_FOCUSED_PROTEST = re.compile(
    r"\b(?:anti[- ]immigration|anti[- ]migrant|pro[- ]migrant|migrant[- ]rights|refugee[- ]rights|asylum[- ]seekers?[- ]rights)\s+(?:protests?|rall(?:y|ies)|march(?:es)?|demonstrations?)\b"
    r"|\b(?:protests?|rall(?:y|ies)|march(?:es)?|demonstrations?)\s+(?:against|for|over)\s+(?:immigration|migration|migrants?|refugees?|asylum)\b", re.I
)

def relevance_rejection(text):
    """Return narrow reason code or None; preserve uncertain cases for review."""
    if not isinstance(text, str) or not text.strip():
        return None
    # Topic exclusions are applied before keyword-based operational matching.
    # A long unrelated story may mention refugees and deportation without
    # reporting a real-world migration event.
    if _NATURE.search(text) and _NATURE_CONTEXT.search(text) and not re.search(
        r"\b(?:human migrants?|refugees?|asylum seekers?|immigration enforcement|border police)\b", text, re.I
    ):
        return "NON_HUMAN_MIGRATION"
    if _FICTION.search(text) and not _REAL_WORLD.search(text):
        return "FICTIONAL_OR_CREATIVE_CONTENT"
    if _EDUCATION_CONTEXT.search(text) and not _MIGRATION_FOCUSED_PROTEST.search(text):
        # Explicit education framing + migration as a political aside is not
        # migration mobilisation. Preserve posts reporting an actual crossing.
        if len(_EDUCATION_CONTEXT.findall(text)) >= 2 and not re.search(
            r"\b(?:migrants?|refugees?|asylum seekers?)\b.{0,85}\b(?:crossed|rescued|intercepted|deported|detained|arrived at the border)\b", text, re.I | re.S
        ):
            return "EDUCATION_PROTEST_NOT_MIGRATION_MOBILIZATION"
    if not _MIGRATION.search(text):
        return None
    if _ACTUAL_MIGRATION.search(text):
        return None
    if _HISTORICAL.search(text) and not _CURRENT_MIGRATION.search(text):
        # Only suppress when historical content dominates the document.
        if len(_HISTORICAL.findall(text)) >= 2:
            return 'HISTORICAL_GENEALOGY_NOT_CURRENT_MIGRATION'
    if _EDUCATION.search(text):
        if len(_EDUCATION.findall(text)) >= 2:
            return 'EDUCATION_PROTEST_NOT_MIGRATION_MOBILIZATION'
    return None
