"""Editorial-only Telegram bridge. Source Intelligence remains untouched."""
import base64
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
import sys
from zoneinfo import ZoneInfo

from database.database import get_session
from database.models import CollectedPost
from analysis.enrich_editorial_ai_hu import analyze_batch, read_json, save_json, github, SCHEMA_VERSION

TZ = ZoneInfo('Europe/Budapest')
MAX_POSTS = max(1, min(500, int(os.getenv('TELEGRAM_EDITORIAL_MAX_POSTS', '150'))))
MAX_AI = max(0, min(80, int(os.getenv('TELEGRAM_EDITORIAL_MAX_AI', '12'))))

def iso(value):
    if value is None: return None
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()

def key(item):
    return 'TELEGRAM:' + str(item['source_post_id'])

def collect():
    session = get_session()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).replace(tzinfo=None)
        posts = (session.query(CollectedPost)
                 .filter(CollectedPost.source == 'TELEGRAM')
                 .filter(CollectedPost.last_collected_at >= cutoff)
                 .order_by(CollectedPost.last_collected_at.desc()).limit(MAX_POSTS).all())
        by_day = defaultdict(dict)
        for p in posts:
            if not p.source_post_id or not (p.text or '').strip(): continue
            stamp = p.first_collected_at or p.published_at or p.last_collected_at
            if not stamp: continue
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
            day = stamp.astimezone(TZ).date().isoformat()
            item = {'source':'TELEGRAM', 'source_post_id':str(p.source_post_id),
                    'post_id':str(p.source_post_id), 'author':p.author,
                    'text':p.text, 'language':p.language,
                    'published_at':iso(p.published_at),
                    'first_collected_at':iso(p.first_collected_at),
                    'last_collected_at':iso(p.last_collected_at),
                    'url':p.url, 'source_url':p.url,
                    'editorial_review_only':True,
                    'is_operational':p.is_operational, 'is_noise':p.is_noise}
            by_day[day][key(item)] = item
        return by_day, len(posts)
    finally:
        session.close()

def append_archive(day, items):
    path = f'archive/{day}.json'
    for attempt in range(5):
        fetched = github('GET', path)
        sha = fetched.get('sha') if fetched else None
        if fetched:
            archive = json.loads(base64.b64decode(fetched['content']).decode('utf-8'))
            if archive.get('date') != day or archive.get('schema_version') != 1:
                raise RuntimeError(f'Unexpected archive format: {path}')
        else: archive = {'schema_version':1, 'date':day}
        target = archive.setdefault('telegram_posts', [])
        if not isinstance(target, list): raise RuntimeError('Invalid telegram_posts array')
        seen = {key(x) for x in target if isinstance(x,dict) and x.get('source_post_id')}
        additions = [v for k,v in items.items() if k not in seen]
        if not additions: return 0
        target.extend(additions)
        archive['last_archived_at'] = datetime.now(timezone.utc).isoformat()
        payload = {'message':f'Append Telegram editorial records {day}',
                   'content':base64.b64encode((json.dumps(archive,ensure_ascii=False,indent=2)+'\n').encode()).decode()}
        if sha: payload['sha'] = sha
        try:
            github('PUT',path,payload)
            return len(additions)
        except RuntimeError as exc:
            if ('HTTP 409' not in str(exc) and 'HTTP 422' not in str(exc)) or attempt == 4: raise
    return 0

def review(days):
    remaining = MAX_AI
    for day in sorted(days,reverse=True):
        if remaining <= 0: break
        archive,_ = read_json(f'archive/{day}.json')
        if not archive: continue
        path = f'ai_reviews/{day}.json'
        old,sha = read_json(path)
        result = old if isinstance(old,dict) and isinstance(old.get('reviews'),dict) else {'schema_version':SCHEMA_VERSION,'date':day,'reviews':{}}
        if result.get('schema_version',1) < SCHEMA_VERSION:
            result['legacy_reviews'] = {**result.get('reviews',{}), **result.get('legacy_reviews',{})}
            result['schema_version'] = SCHEMA_VERSION
        pending = []
        for item in archive.get('telegram_posts',[]):
            if not isinstance(item,dict) or not item.get('source_post_id'): continue
            rid = 'telegram:' + str(item['source_post_id'])
            if result['reviews'].get(rid,{}).get('schema_version') == SCHEMA_VERSION: continue
            content = str(item.get('text') or '').strip()
            if content: pending.append({'id':rid,'source':'TELEGRAM','type':'EDITORIAL_RAW_TELEGRAM','text':content[:1600]})
        for start in range(0,min(len(pending),remaining),6):
            batch = pending[start:start+min(6,remaining)]
            additions = analyze_batch(batch)
            if len(additions) != len(batch): raise RuntimeError('Incomplete Telegram AI response')
            result['reviews'].update(additions)
            save_json(path,result,sha)
            _,sha = read_json(path)
            remaining -= len(additions)
            print(f'{day}: {len(additions)} Telegram reviews saved')
    print(f'Telegram AI reviews created: {MAX_AI-remaining}')

def main():
    if not os.getenv('EDITORIAL_GITHUB_TOKEN') or not os.getenv('OPENAI_API_KEY'):
        raise RuntimeError('EDITORIAL_GITHUB_TOKEN and OPENAI_API_KEY are required')
    by_day,total = collect()
    print(f'Telegram CollectedPost candidates: {total}')
    for day,items in sorted(by_day.items()):
        print(f'{day}: {append_archive(day,items)} Telegram posts archived')
    review(by_day.keys())

if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print(f'TELEGRAM EDITORIAL BRIDGE ERROR: {exc}',file=sys.stderr)
        sys.exit(1)
