"""Archive pre-AI-gate migration records and full INFORMATION timeline.

Run after dashboard export / historical cleanup, before AI editorial gate.
Existing archived evidence is append-only; source classifications are untouched.
"""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo('Europe/Budapest')
SECTIONS = (
    'live_events', 'event_groups', 'high_confidence_events',
    'influence_signals', 'early_warning_signals', 'crossing_access_signals',
    'access_signals', 'top_crossing_access_posts', 'high_priority_intelligence',
)
TIME_KEYS = ('collected_at', 'first_collected_at', 'first_detected_at', 'created_at', 'first_seen')


def parse_day(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(TZ).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def recorded_day(record):
    for key in TIME_KEYS:
        day = parse_day(record.get(key))
        if day:
            return day
    return None


def stable_id(section, rec):
    if section == 'information_signals':
        value = rec.get('timeline_id')
        if value is not None and str(value).strip():
            return f'{section}:timeline_id:{value}'
        source = rec.get('source') or 'UNKNOWN'
        post = rec.get('source_post_id')
        if post is not None and str(post).strip():
            return f'{section}:source_post_id:{source}:{post}'
        return None
    for field in ('group_id', 'event_id', 'id', 'post_id', 'signal_id'):
        value = rec.get(field)
        if value is not None and str(value).strip():
            return f'{section}:{field}:{value}'
    return None


def api(method, repo, path, token, payload=None):
    url = f'https://api.github.com/repos/{repo}/contents/{quote(path, safe="/")}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'migration-editorial-archiver',
    }
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=45) as res:
            return json.load(res)
    except HTTPError as exc:
        if method == 'GET' and exc.code == 404:
            return None
        raise RuntimeError(f'Editorial GitHub API {method} {path}: HTTP {exc.code}') from exc
    except URLError as exc:
        raise RuntimeError(f'Editorial GitHub API connection failure: {exc.reason}') from exc


def collect_by_day(data):
    by_day = defaultdict(lambda: defaultdict(dict))
    skipped = 0
    for section in SECTIONS:
        items = data.get(section, [])
        if not isinstance(items, list):
            continue
        for rec in items:
            if not isinstance(rec, dict):
                continue
            day = recorded_day(rec)
            ident = stable_id(section, rec)
            if not day or not ident:
                skipped += 1
                continue
            by_day[day][section][ident] = rec

    timeline = data.get('signal_timeline')
    if not isinstance(timeline, dict) or not isinstance(timeline.get('items'), list):
        raise RuntimeError('Missing signal_timeline.items: refusing incomplete Information Signal export')
    information_seen = 0
    for rec in timeline['items']:
        if not isinstance(rec, dict) or str(rec.get('layer', '')).upper() != 'INFORMATION':
            continue
        information_seen += 1
        # The public weekly matrix uses timestamp, not the collection date.
        day = parse_day(rec.get('timestamp'))
        ident = stable_id('information_signals', rec)
        if not day or not ident:
            skipped += 1
            continue
        by_day[day]['information_signals'][ident] = rec
    print(f'Information timeline records considered: {information_seen}')
    return by_day, skipped


def main():
    repo = os.environ.get('EDITORIAL_PRIVATE_REPO', '').strip()
    token = os.environ.get('EDITORIAL_GITHUB_TOKEN', '').strip()
    if not repo or repo.count('/') != 1 or not token:
        raise RuntimeError('EDITORIAL_PRIVATE_REPO / EDITORIAL_GITHUB_TOKEN missing')
    source = ROOT / 'dashboard-data.json'
    if not source.is_file():
        raise RuntimeError('Missing pre-gate dashboard-data.json')
    data = json.loads(source.read_text(encoding='utf-8'))
    if 'ai_editorial_gate' in data:
        raise RuntimeError('Refusing archive: source already contains AI gate metadata')
    by_day, skipped = collect_by_day(data)
    updated = 0
    for day in sorted(by_day):
        path = f'archive/{day}.json'
        existing = api('GET', repo, path, token)
        sha = existing.get('sha') if existing else None
        if existing:
            old = json.loads(base64.b64decode(existing['content']).decode('utf-8'))
            if old.get('date') != day or old.get('schema_version') != 1:
                raise RuntimeError(f'Unexpected existing archive structure: {path}')
        else:
            old = {'schema_version': 1, 'date': day}
        added = 0
        for section, records in by_day[day].items():
            dest = old.setdefault(section, [])
            if not isinstance(dest, list):
                raise RuntimeError(f'Invalid section {section} in {path}')
            existing_ids = {stable_id(section, rec) for rec in dest if isinstance(rec, dict)}
            for ident, rec in records.items():
                if ident not in existing_ids:
                    dest.append(rec)
                    added += 1
                    existing_ids.add(ident)
        if not added:
            continue
        old['last_archived_at'] = datetime.now(timezone.utc).isoformat()
        content = base64.b64encode((json.dumps(old, ensure_ascii=False, indent=2) + '\n').encode('utf-8')).decode('ascii')
        payload = {'message': f'Archive raw migration editorial records for {day}', 'content': content}
        if sha:
            payload['sha'] = sha
        api('PUT', repo, path, token, payload)
        updated += 1
        print(f'{day}: appended {added} records; information signals total {len(old.get("information_signals", []))}')
    print(f'Editorial archive complete: {updated} day files updated; {skipped} records skipped')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
