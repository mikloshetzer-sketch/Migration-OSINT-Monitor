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

def relevance_rejection(text):
    """Return narrow reason code or None; preserve uncertain cases for review."""
    if not isinstance(text, str) or not text.strip():
        return None
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
