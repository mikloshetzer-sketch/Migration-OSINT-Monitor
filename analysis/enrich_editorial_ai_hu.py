"""AI-assisted Hungarian editorial suggestions for archived migration records.

Run only on GitHub Actions (server-side secrets). No auto-publishing decisions.
Results stored in editorial repo: ai_reviews/YYYY-MM-DD.json.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = os.environ.get('EDITORIAL_PRIVATE_REPO', 'mikloshetzer-sketch/Migration-OSINT-Editorial-Private')
GITHUB_TOKEN = os.environ.get('EDITORIAL_GITHUB_TOKEN', '')
OPENAI_KEY = os.environ.get('OPENAI_API_KEY', '')
MODEL = os.environ.get('OPENAI_EDITORIAL_MODEL', 'gpt-4.1-mini')
MAX_RECORDS = int(os.environ.get('EDITORIAL_AI_MAX_RECORDS', '80'))
BATCH_SIZE = 6
SECTIONS = ('information_signals', 'live_events', 'event_groups', 'influence_signals', 'early_warning_signals', 'crossing_access_signals', 'access_signals', 'top_crossing_access_posts', 'high_priority_intelligence')


def github(method, path, payload=None):
    url = f'https://api.github.com/repos/{REPO}/contents/{quote(path, safe="/")}'
    headers = {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'migration-editorial-ai-hu', 'X-GitHub-Api-Version': '2022-11-28'}
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = Request(url, headers=headers, data=body, method=method)
    try:
        with urlopen(req, timeout=60) as res:
            return json.load(res)
    except HTTPError as e:
        if method == 'GET' and e.code == 404:
            return None
        raise RuntimeError(f'GitHub {method} {path}: HTTP {e.code}') from e


def read_json(path):
    result = github('GET', path)
    if not result:
        return None, None
    return json.loads(base64.b64decode(result['content']).decode()), result['sha']


def save_json(path, obj, sha):
    content = base64.b64encode((json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode()).decode()
    data = {'message': f'Update Hungarian AI editorial suggestions: {path}', 'content': content}
    if sha:
        data['sha'] = sha
    github('PUT', path, data)


def record_id(section, item):
    if section == 'information_signals':
        value = item.get('timeline_id') or item.get('source_post_id') or item.get('id')
        return f'information:{value}' if value else None
    if section == 'event_groups':
        value = item.get('group_id') or item.get('id')
        return f'group:{value}' if value else None
    value = item.get('source_post_id') or item.get('event_id') or item.get('id') or item.get('record_id') or item.get('uuid') or item.get('post_id')
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
            txt = str(item.get('text') or item.get('representative_text') or item.get('text_excerpt') or item.get('description') or '')
            if not txt.strip():
                continue
            seen[rid] = {'id': rid, 'source': str(item.get('source') or ''), 'type': str(item.get('signal_type') or item.get('event_type') or ''), 'text': txt[:1600]}
    return list(seen.values())


CATEGORIES = {'EVENT', 'EARLY_WARNING', 'POLITICAL_DISCOURSE', 'MISINFORMATION_SUSPECTED', 'IRRELEVANT'}


def analyze_batch(batch):
    system = ("Migrációs OSINT szerkesztői előértékelő vagy. Csak a kapott posztok alapján dolgozz. "
              "Minden rekordhoz készíts pontos, közérthető magyar fordítást vagy hosszú szövegnél hű, 2-4 mondatos magyar összefoglalót. "
              "Ne találj ki tényeket. Kategóriák: EVENT (konkrét esemény), EARLY_WARNING (ellenőrzendő korai jelzés), "
              "POLITICAL_DISCOURSE (vélemény, politikai/társadalmi vita), MISINFORMATION_SUSPECTED (konkrétan megindokolt ellenőrzési gyanú), "
              "IRRELEVANT (nem a jelenkori migrációs monitor tárgya). "
              "A dezinformációgyanú nem tényellenőrzés és nem cáfolat. Egy állítás puszta politikai jellege nem dezinformáció. "
              "Soha ne javasolj automatikus publikálást. "
              "JSON objektumot adj vissza, 'results' tömbbel. Minden elem: id, hu_text, category, reason_hu, verification_needed (boolean). "
              "Az id mezőt pontosan másold át. Minden bemeneti rekord szerepeljen a válaszban.")
    body = {'model': MODEL, 'temperature': 0, 'response_format': {'type': 'json_object'}, 'messages': [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': json.dumps({'records': batch}, ensure_ascii=False)}]}
    req = Request('https://api.openai.com/v1/chat/completions', data=json.dumps(body, ensure_ascii=False).encode(),
                  headers={'Authorization': f'Bearer {OPENAI_KEY}', 'Content-Type': 'application/json'}, method='POST')
    with urlopen(req, timeout=120) as res:
        result = json.load(res)
    parsed = json.loads(result['choices'][0]['message']['content'])
    items = parsed.get('results', [])
    if not isinstance(items, list):
        raise ValueError('AI results must be an array')
    valid_ids = {r['id'] for r in batch}
    output = {}
    for item in items:
        if not isinstance(item, dict) or item.get('id') not in valid_ids:
            continue
        category = str(item.get('category', '')).upper()
        hu = str(item.get('hu_text') or '').strip()
        reason = str(item.get('reason_hu') or '').strip()
        if category not in CATEGORIES or not hu or not reason:
            continue
        output[item['id']] = {'hu_text': hu, 'category': category, 'reason_hu': reason,
                              'verification_needed': bool(item.get('verification_needed', True)),
                              'model': MODEL, 'analyzed_at': datetime.now(timezone.utc).isoformat()}
    return output


def main():
    if not GITHUB_TOKEN or not OPENAI_KEY:
        raise RuntimeError('EDITORIAL_GITHUB_TOKEN and OPENAI_API_KEY are required')
    if MAX_RECORDS < 1 or MAX_RECORDS > 500:
        raise ValueError('EDITORIAL_AI_MAX_RECORDS must be 1..500')
    today = datetime.now(timezone.utc).date().isoformat()
    # Current + previous day; older dates are intentionally not retroactively AI-reviewed.
    from datetime import timedelta
    days = [(datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat() for i in (1, 0)]
    processed = 0
    for day in days:
        archive, _ = read_json(f'archive/{day}.json')
        if not archive:
            continue
        path = f'ai_reviews/{day}.json'
        previous, sha = read_json(path)
        result = previous if isinstance(previous, dict) and isinstance(previous.get('reviews'), dict) else {'schema_version': 1, 'date': day, 'reviews': {}}
        pending = [r for r in candidates(archive) if r['id'] not in result['reviews']]
        pending = pending[:max(0, MAX_RECORDS - processed)]
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start:start+BATCH_SIZE]
            for attempt in range(3):
                try:
                    additions = analyze_batch(batch)
                    if len(additions) != len(batch):
                        raise RuntimeError(f'Incomplete AI batch: {len(additions)}/{len(batch)}')
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f'AI retry {attempt+1}: {e}', file=sys.stderr)
                    time.sleep(2 ** attempt * 3)
            result['reviews'].update(additions)
            processed += len(additions)
            # Save each batch, so retries and subsequent runs do not repeat paid calls.
            save_json(path, result, sha)
            _, sha = read_json(path)
            print(f'{day}: saved {len(additions)} AI suggestions; total {len(result["reviews"])}')
        if processed >= MAX_RECORDS:
            break
    print(f'AI enrichment complete: {processed} new records')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
