"""Unified Hungarian editorial AI for every archived source, including Telegram.

Editorial only: does not affect Source Intelligence, operational classification,
or publication decisions. Results are append-only in the editorial repository.
"""
from __future__ import annotations
import base64
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

REPO = os.getenv('EDITORIAL_PRIVATE_REPO', 'mikloshetzer-sketch/Migration-OSINT-Editorial-Private')
GITHUB_TOKEN = os.getenv('EDITORIAL_GITHUB_TOKEN', '')
OPENAI_KEY = os.getenv('OPENAI_API_KEY', '')
MODEL = os.getenv('OPENAI_EDITORIAL_MODEL', 'gpt-4.1-mini')
MAX_RECORDS = int(os.getenv('EDITORIAL_AI_MAX_RECORDS', '40'))
LOOKBACK_DAYS = int(os.getenv('EDITORIAL_AI_LOOKBACK_DAYS', '7'))
BATCH_SIZE = 6
SCHEMA_VERSION = 2
TZ = ZoneInfo('Europe/Budapest')
SECTIONS = ('information_signals', 'live_events', 'event_groups', 'influence_signals',
            'early_warning_signals', 'crossing_access_signals', 'access_signals',
            'top_crossing_access_posts', 'high_priority_intelligence', 'telegram_posts')
CATEGORIES = {'MIGRATION_EVENT', 'MOVEMENT_INTENT', 'FACILITATION', 'BORDER_SECURITY',
              'POLICY_LEGAL', 'SOCIAL_DISCOURSE', 'HUMANITARIAN', 'BACKGROUND_HISTORICAL', 'IRRELEVANT'}
VERIFICATION = {'UNVERIFIED', 'PARTIALLY_VERIFIED', 'VERIFIED', 'CONTRADICTED', 'MANIPULATION_SUSPECTED'}
PRIORITIES = {'HIGH', 'MEDIUM', 'LOW'}


def github(method, path, payload=None):
    url = f'https://api.github.com/repos/{REPO}/contents/{quote(path, safe="/")}'
    headers = {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github+json',
               'User-Agent': 'migration-editorial-ai-hu', 'X-GitHub-Api-Version': '2022-11-28'}
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(url, headers=headers, data=body, method=method)
    try:
        with urlopen(req, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        if method == 'GET' and exc.code == 404:
            return None
        raise RuntimeError(f'GitHub {method} {path}: HTTP {exc.code}') from exc


def read_json(path):
    result = github('GET', path)
    if not result:
        return None, None
    return json.loads(base64.b64decode(result['content']).decode('utf-8')), result['sha']


def save_json(path, obj, sha=None):
    for attempt in range(7):
        latest, current_sha = read_json(path)
        merged = dict(obj)
        if isinstance(latest, dict) and isinstance(latest.get('reviews'), dict):
            merged['reviews'] = {**latest['reviews'], **obj.get('reviews', {})}
            for key, review in latest['reviews'].items():
                if isinstance(review, dict) and review.get('schema_version') == SCHEMA_VERSION:
                    merged['reviews'][key] = review
            merged['legacy_reviews'] = {
                **obj.get('legacy_reviews', {}), **latest.get('legacy_reviews', {})
            } if isinstance(latest.get('legacy_reviews'), dict) else obj.get('legacy_reviews', {})
        merged['schema_version'] = SCHEMA_VERSION
        payload = {'message': f'Update unified Hungarian editorial AI: {path}',
                   'content': base64.b64encode((json.dumps(merged, ensure_ascii=False, indent=2) + '\n').encode('utf-8')).decode('ascii')}
        if current_sha:
            payload['sha'] = current_sha
        try:
            github('PUT', path, payload)
            obj.clear()
            obj.update(merged)
            return
        except RuntimeError as exc:
            if ('HTTP 409' not in str(exc) and 'HTTP 422' not in str(exc)) or attempt == 6:
                raise
            time.sleep(min(2 ** attempt, 12))


def record_id(section, item):
    if section == 'telegram_posts':
        value = item.get('source_post_id') or item.get('post_id')
        return f'telegram:{value}' if value else None
    if section == 'information_signals':
        value = item.get('timeline_id') or item.get('source_post_id') or item.get('id')
        if not value:
            return None
        value = str(value)
        return value if value.startswith('information:') else f'information:{value}'
    if section == 'event_groups':
        value = item.get('group_id') or item.get('id')
        return f'group:{value}' if value else None
    value = (item.get('source_post_id') or item.get('event_id') or item.get('id')
             or item.get('record_id') or item.get('uuid') or item.get('post_id'))
    return f'record:{value}' if value else None


def candidates(archive):
    seen = {}
    for section in SECTIONS:
        for item in archive.get(section, []):
            if not isinstance(item, dict):
                continue
            rid = record_id(section, item)
            if not rid or rid in seen:
                continue
            content = str(item.get('text') or item.get('representative_text') or
                          item.get('text_excerpt') or item.get('description') or '').strip()
            if not content:
                continue
            seen[rid] = {'id': rid, 'source': str(item.get('source') or ''),
                         'type': str(item.get('signal_type') or item.get('event_type') or section),
                         'text': content[:1600]}
    return list(seen.values())


def analyze_batch(batch):
    system = (
        'Migrációs OSINT szerkesztői előértékelő vagy. A bemenet nem ellenőrzött '
        'közösségi médiás állításokat is tartalmaz. MINDEN rekordhoz írj pontos magyar '
        'fordítást vagy hosszabb szöveg esetén hű, 2–4 mondatos magyar összefoglalót. '
        'A tartalmi kategória egyike: MIGRATION_EVENT, MOVEMENT_INTENT, FACILITATION, '
        'BORDER_SECURITY, POLICY_LEGAL, SOCIAL_DISCOURSE, HUMANITARIAN, '
        'BACKGROUND_HISTORICAL, IRRELEVANT. '
        'Ellenőrzöttség: UNVERIFIED, PARTIALLY_VERIFIED, VERIFIED, CONTRADICTED, '
        'MANIPULATION_SUSPECTED. Egyetlen bejegyzés alapján rendszerint UNVERIFIED; '
        'VERIFIED csak valódi bizonyíték esetén. Politikai vélemény önmagában nem manipuláció. '
        'Prioritás: HIGH, MEDIUM, LOW. Ne találj ki tényeket, és ne hozz publikálási döntést. '
        'Az indoklást magyarul add meg. JSON objektumot adj results tömbbel. '
        'Minden rekordhoz kötelező: id, hu_text, content_category, verification_status, '
        'priority, reason_hu, verification_needed (boolean). Az id-t pontosan másold át.'
    )
    body = {'model': MODEL, 'temperature': 0, 'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': json.dumps({'records': batch}, ensure_ascii=False)}]}
    req = Request('https://api.openai.com/v1/chat/completions',
                  data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                  headers={'Authorization': f'Bearer {OPENAI_KEY}', 'Content-Type': 'application/json'},
                  method='POST')
    with urlopen(req, timeout=120) as response:
        answer = json.load(response)
    parsed = json.loads(answer['choices'][0]['message']['content'])
    items = parsed.get('results', [])
    if not isinstance(items, list):
        raise ValueError('AI results must be an array')
    allowed = {x['id'] for x in batch}
    output = {}
    for item in items:
        if not isinstance(item, dict) or item.get('id') not in allowed:
            continue
        category = str(item.get('content_category', '')).upper()
        verification = str(item.get('verification_status', '')).upper()
        priority = str(item.get('priority', '')).upper()
        hu = str(item.get('hu_text') or '').strip()
        reason = str(item.get('reason_hu') or '').strip()
        if category not in CATEGORIES or verification not in VERIFICATION or priority not in PRIORITIES or not hu or not reason:
            continue
        output[item['id']] = {'hu_text': hu, 'content_category': category,
                              'verification_status': verification, 'priority': priority,
                              'reason_hu': reason,
                              'verification_needed': bool(item.get('verification_needed', verification != 'VERIFIED')),
                              'schema_version': SCHEMA_VERSION, 'model': MODEL,
                              'analyzed_at': datetime.now(timezone.utc).isoformat()}
    return output


def main():
    if not GITHUB_TOKEN or not OPENAI_KEY:
        raise RuntimeError('EDITORIAL_GITHUB_TOKEN and OPENAI_API_KEY are required')
    if not 1 <= MAX_RECORDS <= 500 or not 1 <= LOOKBACK_DAYS <= 30:
        raise ValueError('EDITORIAL_AI_MAX_RECORDS must be 1..500 and LOOKBACK_DAYS 1..30')

    today = datetime.now(TZ).date()
    days = [(today - timedelta(days=i)).isoformat()
            for i in range(LOOKBACK_DAYS - 1, -1, -1)]
    day_states = {}
    # Load archives once; the entire lookback period shares one processing queue.
    for day in days:
        archive, _ = read_json(f'archive/{day}.json')
        if not archive:
            continue
        path = f'ai_reviews/{day}.json'
        previous, sha = read_json(path)
        result = (previous if isinstance(previous, dict) and isinstance(previous.get('reviews'), dict)
                  else {'schema_version': SCHEMA_VERSION, 'date': day, 'reviews': {}})
        if result.get('schema_version', 1) < SCHEMA_VERSION:
            result['legacy_reviews'] = {**result.get('reviews', {}), **result.get('legacy_reviews', {})}
            result['schema_version'] = SCHEMA_VERSION
        # Reuse previously paid AI results under legacy double-prefixed keys.
        # Never call AI again solely because the identifier format changed.
        migrated = 0
        for record in candidates(archive):
            rid = record['id']
            existing = result['reviews'].get(rid)
            if isinstance(existing, dict) and str(existing.get('hu_text') or '').strip():
                continue
            legacy = result['reviews'].get(rid.split(':', 1)[0] + ':' + rid)
            if isinstance(legacy, dict) and str(legacy.get('hu_text') or '').strip():
                result['reviews'][rid] = dict(legacy)
                migrated += 1
        if migrated:
            save_json(path, result, sha)
            _, sha = read_json(path)
            print(f'{day}: recovered {migrated} legacy AI reviews without API calls')
        pending = [r for r in candidates(archive)
                   if not isinstance(result['reviews'].get(r['id']), dict)
                   or result['reviews'][r['id']].get('schema_version') != SCHEMA_VERSION
                   or not str(result['reviews'][r['id']].get('hu_text') or '').strip()]
        day_states[day] = {'path': path, 'result': result, 'sha': sha, 'pending': pending}

    # Reserve capacity for fresh posts of ALL sources, while gradually backfilling
    # older Telegram and other historical records. No source can monopolize the run.
    current_day = today.isoformat()
    fresh = [(current_day, r) for r in day_states.get(current_day, {}).get('pending', [])]
    fresh.sort(key=lambda pair: (pair[1]['id'].startswith('telegram:'), pair[1]['id']))
    backlog = []
    for day in days:
        if day == current_day or day not in day_states:
            continue
        backlog.extend((day, r) for r in day_states[day]['pending'])
    backlog.sort(key=lambda pair: (not pair[1]['id'].startswith('telegram:'), pair[0], pair[1]['id']))
    # At least half of the budget is available for today's posts; unused slots
    # are reallocated to the other queue.
    fresh_budget = (MAX_RECORDS + 1) // 2
    queue = fresh[:fresh_budget] + backlog[:MAX_RECORDS - min(fresh_budget, len(fresh))]
    if len(queue) < MAX_RECORDS:
        queue += fresh[fresh_budget:][:MAX_RECORDS - len(queue)]
    if len(queue) < MAX_RECORDS:
        queue += backlog[MAX_RECORDS - min(fresh_budget, len(fresh)):][:MAX_RECORDS - len(queue)]
    processed = 0
    telegram_processed = 0
    # Batch by day to write to the matching daily review JSON without changing its schema.
    for day in days:
        items = [record for d, record in queue if d == day]
        if not items:
            continue
        state = day_states[day]
        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start:start + BATCH_SIZE]
            for attempt in range(3):
                try:
                    additions = analyze_batch(batch)
                    if len(additions) != len(batch):
                        raise RuntimeError(f'Incomplete AI batch {len(additions)}/{len(batch)}')
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise
                    print(f'AI retry {attempt + 1}: {exc}', file=sys.stderr)
                    time.sleep(3 * (2 ** attempt))
            state['result']['reviews'].update(additions)
            save_json(state['path'], state['result'], state['sha'])
            _, state['sha'] = read_json(state['path'])
            processed += len(additions)
            telegram_processed += sum(x['id'].startswith('telegram:') for x in batch)
            print(f'{day}: saved {len(additions)} shared editorial AI reviews')
    print(f'Unified editorial AI complete: {processed} new reviews; '
          f'Telegram: {telegram_processed}; lookback: {LOOKBACK_DAYS} days')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'EDITORIAL AI ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
