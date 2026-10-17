"""Conservative historical suppression overlay for Migration OSINT dashboard.

Never changes source database or source-intelligence.json. A reviewed ID manifest is
versioned in Git. Suppression is applied to published JSON at every export because
normal runs regenerate the dashboard; the review itself is NOT rerun.

Derived risk/assessment fields are flagged as unverified rather than fabricated.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'analysis' / 'historical_suppression_manifest.json'
DB = ROOT / 'database' / 'migration_osint_monitor.db'
DASHBOARD = ROOT / 'dashboard-data.json'


def load_manifest(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1:
        raise ValueError('Unexpected suppression manifest schema')
    ids = {}
    for name in ('post', 'influence_signal'):
        values = data.get('suppressed', {}).get(name, [])
        if any(type(v) is not int or v <= 0 for v in values) or len(values) != len(set(values)):
            raise ValueError('Invalid or duplicated record IDs: '+name)
        ids[name] = set(values)
    return ids


def linked_groups(db_path, post_ids):
    """Suppress only groups for which every linked post has been suppressed.

    A group with missing or unmatched source links is left visible for review.
    """
    if not db_path.exists():
        raise FileNotFoundError('Database required for safe group linkage: '+str(db_path))
    con = sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)
    try:
        groups = {}
        for gid, pid in con.execute('SELECT event_group_id, post_id FROM event_group_sources'):
            groups.setdefault(gid, []).append(pid)
        return {gid for gid, sources in groups.items() if sources and all(pid is not None and pid in post_ids for pid in sources)}
    finally:
        con.close()


def layer_key(item):
    tid = str(item.get('timeline_id') or '')
    if ':' not in tid:
        return None, None
    kind, number = tid.split(':', 1)
    try:
        number = int(number)
    except ValueError:
        return None, None
    if kind in ('operational', 'post'):
        return 'post', number
    if kind in ('early_warning', 'influence', 'influence_signal'):
        return 'influence_signal', number
    if kind in ('correlated', 'event_group'):
        return 'event_group', number
    return None, None


def filter_list(obj, ids, id_keys=('id',)):
    if not isinstance(obj, list):
        return obj, 0
    retained = []
    removed = 0
    for entry in obj:
        if isinstance(entry, dict) and any(entry.get(k) in ids for k in id_keys):
            removed += 1
        else:
            retained.append(entry)
    return retained, removed


def clean(data, ids, groups):
    out = json.loads(json.dumps(data))
    counts = Counter()
    post_keys = ['live_events', 'high_confidence_events']
    signal_keys = ['influence_signals', 'early_warning_signals', 'high_priority_intelligence', 'top_crossing_access_posts', 'crossing_access_signals', 'access_signals']
    group_keys = ['event_groups']
    for key in post_keys:
        if key in out:
            out[key], n = filter_list(out[key], ids['post'], ('id', 'event_id'))
            counts[key] = n
    for key in signal_keys:
        if key in out:
            out[key], n = filter_list(out[key], ids['influence_signal'])
            counts[key] = n
    for key in group_keys:
        if key in out:
            out[key], n = filter_list(out[key], groups, ('id', 'group_id'))
            counts[key] = n
    timeline = out.get('signal_timeline')
    if isinstance(timeline, dict) and isinstance(timeline.get('items'), list):
        kept = []
        for item in timeline['items']:
            kind, rid = layer_key(item)
            if (kind == 'post' and rid in ids['post']) or (kind == 'influence_signal' and rid in ids['influence_signal']) or (kind == 'event_group' and rid in groups):
                counts['timeline'] += 1
            else:
                kept.append(item)
        timeline['items'] = kept
        layers = Counter(str(item.get('layer') or '') for item in kept)
        sources = Counter(str(item.get('source') or '') for item in kept if item.get('source'))
        types = Counter(str(item.get('type') or '') for item in kept if item.get('type'))
        timeline['total_items'] = len(kept)
        timeline['layer_counts'] = dict(layers)
        timeline['source_counts'] = dict(sources)
        timeline['type_counts'] = dict(types)
        for field, layer in [('information_count','INFORMATION'),('early_warning_count','EARLY_WARNING'),('operational_count','OPERATIONAL'),('correlated_count','CORRELATED')]:
            timeline[field] = layers[layer]
    # Crucial: existing risk metrics aggregate full history and must not be presented
    # as recalculated. Preserve originals but explicitly mark them provisional.
    out['historical_revalidation'] = {
        'mode': 'REVIEWED_SUPPRESSION_OVERLAY',
        'suppressed_post_ids': sorted(ids['post']),
        'suppressed_influence_ids': sorted(ids['influence_signal']),
        'suppressed_group_ids': sorted(groups),
        'removed_display_items': dict(counts),
        'risk_metrics_recalculated': False,
        'warning': 'Legacy KPIs, regional aggregates, correlation and risk scores are NOT recalculated and may include suppressed history. Do not treat them as validated.',
    }
    # Clear qualitative conclusions rather than display stale HIGH/CRITICAL as clean.
    for key in ('operational_assessment', 'analytical_assessment'):
        if isinstance(out.get(key), dict):
            out[key]['historical_review_status'] = 'PROVISIONAL_UNRECALCULATED'
            out[key]['historical_review_warning'] = out['historical_revalidation']['warning']
    return out, dict(counts)


def run(db, manifest, dashboard, out, report):
    ids = load_manifest(manifest)
    groups = linked_groups(db, ids['post'])
    original = json.loads(dashboard.read_text(encoding='utf-8'))
    cleaned, counts = clean(original, ids, groups)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    result = {'manifest':str(manifest),'input':str(dashboard),'output':str(out),'suppressed_post_ids':sorted(ids['post']),'suppressed_influence_ids':sorted(ids['influence_signal']),'fully_suppressed_groups':sorted(groups),'removed_display_items':counts,'risk_metrics_recalculated':False}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db',type=Path,default=DB)
    p.add_argument('--manifest',type=Path,default=MANIFEST)
    p.add_argument('--dashboard',type=Path,default=DASHBOARD)
    p.add_argument('--out',type=Path,default=DASHBOARD)
    p.add_argument('--report',type=Path,default=ROOT/'historical-cleanup-report.json')
    a = p.parse_args()
    print(json.dumps(run(a.db,a.manifest,a.dashboard,a.out,a.report),indent=2))

if __name__ == '__main__':
    main()
