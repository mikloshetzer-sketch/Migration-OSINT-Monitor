"""One-time historical migration OSINT audit. Read-only: never changes source DB.

Usage:
 python -m analysis.historical_revalidation --db database/migration_osint_monitor.db
 python -m analysis.historical_revalidation --db database/migration_osint_monitor.db --out historical-review

Outputs CSV and JSON review proposals. NO automatic removal or relabeling.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

NATURE = re.compile(r'\b(monarch butterfl(?:y|ies)|butterfly migration|bird migration|migratory birds|animal migration|wildlife migration)\b', re.I)
FICTION = re.compile(r'\b(\[qcrit\]|speculative fiction novel|fantasy novel|fanfiction|headcanon|tower lore|kingdom rush|worldbuilding|fictional kingdom)\b', re.I)
EDUCATION = re.compile(r'\b(student protests?|school protests?|teacher shortages?|underfunded schools?|university admissions?|education funding|protesteerders|leerlingen|docenten)\b', re.I)
MIGRATION_PROTEST = re.compile(r'\b(anti[- ]immigration|pro[- ]migrant|migrant rights|refugee rights|asylum seekers rights)\b', re.I)
HISTORICAL = re.compile(r'\b(\d{1,2}(?:st|nd|rd|th) century|centuries ago|in 19\d\d|in 18\d\d|historical migration|middle ages|medieval)\b', re.I)
OPINION = re.compile(r'\b(i want|i wish|should be deported|must be deported|would be deported|if (?:she|he|they|it) (?:is|are|were) deported|there will be trouble until)\b', re.I)
CONDITIONAL = re.compile(r'\b(if .*? (?:is|are|were) deported|could be deported|might be deported|may be deported)\b', re.I)
EVENT_TYPES = {'BORDER_CROSSING','DEPORTATION','DETENTION','BORDER_MEASURE','SMUGGLING_ACTIVITY','CASUALTY','RESCUE','INTERCEPTION'}
COLUMNS = ['record_type','record_id','event_type','decision','reason','confidence','group_id','source','source_post_id','text_excerpt']

def classify(text: str, event_type: str = '') -> tuple[str, str, float]:
    text = text or ''
    if NATURE.search(text):
        return 'EXCLUDE', 'NON_HUMAN_MIGRATION', 0.99
    if FICTION.search(text):
        return 'EXCLUDE', 'FICTIONAL_CONTENT', 0.99
    if EDUCATION.search(text) and not MIGRATION_PROTEST.search(text):
        return 'REVIEW', 'EDUCATION_PROTEST_NOT_MIGRATION_FOCUSED', 0.90
    if HISTORICAL.search(text) and event_type in EVENT_TYPES:
        return 'REVIEW', 'HISTORICAL_REFERENCE_NOT_CURRENT_EVENT', 0.85
    if CONDITIONAL.search(text) and event_type in EVENT_TYPES:
        return 'RECLASSIFY', 'CONDITIONAL_NOT_COMPLETED_EVENT', 0.90
    if OPINION.search(text) and event_type in EVENT_TYPES:
        return 'RECLASSIFY', 'OPINION_OR_DEMAND_NOT_COMPLETED_EVENT', 0.90
    if event_type in EVENT_TYPES and not re.search(r'\b(arrived|crossed|rescued|intercepted|arrested|detained|deported|repatriated|charged|closed|closure|transferred|entered|died|killed|entraron|detenido|expulsado|deportado)\b', text, re.I):
        return 'REVIEW', 'EVENT_ASSERTION_NOT_DEMONSTRATED', 0.65
    return 'KEEP_CANDIDATE', 'NO_CLEAR_RULE_VIOLATION_NOT_VERIFIED', 0.40

def table_names(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def columns(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}

def rows(con, table):
    return con.execute(f'SELECT * FROM "{table}"').fetchall()

def value(record, *names):
    for name in names:
        if name in record.keys() and record[name] is not None:
            return record[name]
    return None

def audit(db: Path, out: Path):
    if not db.is_file():
        raise FileNotFoundError(f'Database missing: {db}')
    out.mkdir(parents=True, exist_ok=True)
    # SQLite URI mode=ro prevents accidental writes, including SQLAlchemy side effects.
    uri = f'{db.resolve().as_uri()}?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        tables = table_names(con)
        if 'posts' not in tables:
            raise RuntimeError('Expected posts table not found; audit stopped')
        audit_rows = []
        by_post_id = {}
        for p in rows(con, 'posts'):
            rid = value(p, 'id')
            decision, reason, confidence = classify(value(p,'text') or '', value(p,'signal_type') or '')
            by_post_id[rid] = (decision, reason)
            audit_rows.append({'record_type':'post','record_id':rid,'event_type':value(p,'signal_type') or '', 'decision':decision,'reason':reason,'confidence':confidence,'group_id':'','source':value(p,'source') or '', 'source_post_id':value(p,'post_id') or '', 'text_excerpt':(value(p,'text') or '')[:300]})
        links = defaultdict(list)
        if 'event_group_sources' in tables:
            for link in rows(con, 'event_group_sources'):
                gid = value(link,'event_group_id')
                post_id = value(link,'post_id')
                if post_id in by_post_id:
                    links[gid].append(by_post_id[post_id])
                else:
                    links[gid].append(classify(value(link,'text') or '', value(link,'event_type') or ''))
        if 'event_groups' in tables:
            for group in rows(con, 'event_groups'):
                gid = value(group,'id')
                decisions = [x[0] for x in links.get(gid, [])]
                decision, reason, confidence = classify(value(group,'representative_text') or '', value(group,'event_type') or '')
                if decisions and all(x == 'EXCLUDE' for x in decisions):
                    decision, reason, confidence = 'REVIEW','ALL_LINKED_SOURCES_EXCLUDED',0.95
                elif any(x in ('EXCLUDE','RECLASSIFY','REVIEW') for x in decisions):
                    decision, reason, confidence = 'REVIEW','LINKED_SOURCES_REQUIRE_REVALIDATION',0.85
                audit_rows.append({'record_type':'event_group','record_id':gid,'event_type':value(group,'event_type') or '', 'decision':decision,'reason':reason,'confidence':confidence,'group_id':gid,'source':'','source_post_id':'','text_excerpt':(value(group,'representative_text') or '')[:300]})
        # Influence history is included as a separate review layer; no source categories are changed.
        if 'influence_signals' in tables:
            for signal in rows(con,'influence_signals'):
                txt = value(signal,'text','content','post_text') or ''
                decision, reason, confidence = classify(txt, value(signal,'signal_type') or '')
                if not txt:
                    decision, reason, confidence = 'REVIEW','NO_TEXT_IN_SIGNAL_RECORD',0.2
                audit_rows.append({'record_type':'influence_signal','record_id':value(signal,'id') or '', 'event_type':value(signal,'signal_type') or '', 'decision':decision,'reason':reason,'confidence':confidence,'group_id':'','source':value(signal,'source') or '', 'source_post_id':value(signal,'source_post_id') or '', 'text_excerpt':txt[:300]})
        with (out/'historical_revalidation_review.csv').open('w',newline='',encoding='utf-8-sig') as fh:
            writer=csv.DictWriter(fh,fieldnames=COLUMNS)
            writer.writeheader();writer.writerows(audit_rows)
        summary={'created_at':datetime.now(timezone.utc).isoformat(),'mode':'READ_ONLY_DRY_RUN','database':str(db),'tables_found':sorted(tables),'records_reviewed':len(audit_rows),'by_decision':dict(Counter(r['decision'] for r in audit_rows)),'by_record_type':dict(Counter(r['record_type'] for r in audit_rows)),'by_reason':dict(Counter(r['reason'] for r in audit_rows)),'warnings':['No database modifications made','KEEP_CANDIDATE is not independent source verification','Event groups and daily metrics must be rebuilt only after approved migration']}
        (out/'historical_revalidation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False,indent=2))
    finally:
        con.close()

def main():
    parser=argparse.ArgumentParser(description='Read-only historical event revalidation audit')
    parser.add_argument('--db',default='database/migration_osint_monitor.db',type=Path)
    parser.add_argument('--out',default='historical-review',type=Path)
    args=parser.parse_args()
    audit(args.db,args.out)
if __name__=='__main__':
    main()
