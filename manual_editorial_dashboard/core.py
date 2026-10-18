"""Day-scoped editorial record normalization and review identity."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Europe/Budapest')
SECTIONS=('live_events','event_groups','high_confidence_events','influence_signals','early_warning_signals','crossing_access_signals','access_signals','top_crossing_access_posts','high_priority_intelligence')

def parse_time(value):
    if not value:return None
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(TZ)
    except (ValueError,TypeError):return None

def first_date(record):
    for k in ('collected_at','first_collected_at','first_detected_at','created_at','first_seen'):
        t=parse_time(record.get(k))
        if t:return t.date()
    return None

def key_for(section, record):
    # Match ai_editorial_gate.identity semantics for durable overrides.
    if section in ('event_groups','high_confidence_events'): kind='group'
    elif section=='high_priority_intelligence' or 'signal' in section or section=='top_crossing_access_posts': kind='signal'
    else: kind='post'
    rid=record.get('group_id') if kind=='group' else record.get('id')
    rid=rid or record.get('event_id') or record.get('id')
    return f'{kind}:{rid}' if rid is not None else None

def collect(data, chosen_date):
    records={}
    for section in SECTIONS:
        for rec in data.get(section,[]) or []:
            if not isinstance(rec,dict) or first_date(rec)!=chosen_date:continue
            key=key_for(section,rec)
            if not key:continue
            if key not in records or (rec.get('text') and not records[key]['record'].get('text')):
                records[key]={'key':key,'record':rec,'section':section}
    return sorted(records.values(),key=lambda e:e['key'])
