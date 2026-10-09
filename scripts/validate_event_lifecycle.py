"""Conservative Baltic lifecycle gate. Run after scoring, before snapshot.

Preserves all events; only unambiguous historical follow-up articles are
reclassified as assessments. Ambiguous articles are flagged for review.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/baltic_hybrid_scored_news.json'
MIRROR = ROOT / 'docs/data/baltic_hybrid_scored_news.json'

# These phrases explicitly describe follow-ups, not a new physical incident.
FOLLOW_UP = re.compile(
    r'\b(?:investigation (?:into|of) .{0,100}? (?:closed|concluded|completed)|'
    r'(?:prosecutors?|authorities) (?:closed|concluded|dropped) (?:the |an? )?(?:investigation|case)|'
    r'(?:case|investigation) (?:has been |was )?(?:closed|dropped)|'
    r'(?:anniversary|commemorat(?:ion|es|ed)) of (?:the )?(?:attack|incident)|'
    r'(?:report|review) (?:into|on) (?:the )?(?:20\d{2} )?(?:attack|incident))\b',
    re.IGNORECASE,
)
YEAR = re.compile(r'\b20\d{2}\b')


def classify(event):
    e = dict(event)
    title = str(e.get('title') or '')
    summary = str(e.get('summary') or '')
    text = f'{title} {summary}'
    published = str(e.get('published_at') or '')
    publication_year = published[:4] if len(published) >= 4 else ''
    mentioned_years = set(YEAR.findall(text))
    old_year = bool(publication_year and any(y < publication_year for y in mentioned_years))
    explicit_followup = bool(FOLLOW_UP.search(text))
    e['lifecycle_review'] = {
        'status': 'historical_follow_up' if explicit_followup and old_year else (
            'needs_review' if explicit_followup or old_year else 'not_determined'),
        'reason': 'explicit_followup_and_prior_year' if explicit_followup and old_year else (
            'date_or_followup_signal' if explicit_followup or old_year else 'insufficient_evidence'),
        'reviewed_at': datetime.now(timezone.utc).isoformat(),
    }
    if explicit_followup and old_year and str(e.get('event_subtype')) in {'incident', 'activity'}:
        e['original_event_subtype'] = e['event_subtype']
        e['original_hybrid_threat_score'] = e.get('hybrid_threat_score', 0)
        e['event_subtype'] = 'assessment'
        e['hybrid_threat_score'] = 0
        e['hybrid_threat_level'] = 'Low'
    return e


def main():
    data = json.loads(SOURCE.read_text(encoding='utf-8'))
    key = 'events' if isinstance(data.get('events'), list) else 'items'
    if not isinstance(data.get(key), list):
        raise ValueError('No events/items list in scored data')
    data[key] = [classify(e) for e in data[key]]
    # Atomic writes; the workflow already commits both copies.
    for target in (SOURCE, MIRROR):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(target)
    flagged = sum(e['lifecycle_review']['status'] == 'historical_follow_up' for e in data[key])
    print(f'Lifecycle validation: {len(data[key])} events; {flagged} confirmed historical follow-ups')


if __name__ == '__main__':
    main()
