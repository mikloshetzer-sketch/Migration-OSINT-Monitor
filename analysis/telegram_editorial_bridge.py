"""Archive collected Telegram posts for editorial review only.

No AI calls here: the shared enrich_editorial_ai_hu module handles all sources.
Source Intelligence and operational classifications remain untouched.
"""
import base64
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

from database.database import get_session
from database.models import CollectedPost
from analysis.enrich_editorial_ai_hu import github

TZ = ZoneInfo('Europe/Budapest')
MAX_POSTS = max(1, min(1000, int(os.getenv('TELEGRAM_EDITORIAL_MAX_POSTS', '150'))))


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def key(item):
    return 'TELEGRAM:' + str(item['source_post_id'])


def collect():
    session = get_session()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
        posts = (session.query(CollectedPost)
                 .filter(CollectedPost.source == 'TELEGRAM')
                 .filter(CollectedPost.last_collected_at >= cutoff)
                 .order_by(CollectedPost.last_collected_at.desc())
                 .limit(MAX_POSTS).all())
        by_day = defaultdict(dict)
        for p in posts:
            if not p.source_post_id or not (p.text or '').strip():
                continue
            stamp = p.first_collected_at or p.published_at or p.last_collected_at
            if stamp is None:
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            day = stamp.astimezone(TZ).date().isoformat()
            item = {'source': 'TELEGRAM', 'source_post_id': str(p.source_post_id),
                    'post_id': str(p.source_post_id), 'author': p.author,
                    'text': p.text, 'language': p.language,
                    'published_at': iso(p.published_at),
                    'first_collected_at': iso(p.first_collected_at),
                    'last_collected_at': iso(p.last_collected_at),
                    'url': p.url, 'source_url': p.url,
                    'editorial_review_only': True,
                    'is_operational': p.is_operational, 'is_noise': p.is_noise}
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
        else:
            archive = {'schema_version': 1, 'date': day}
        target = archive.setdefault('telegram_posts', [])
        if not isinstance(target, list):
            raise RuntimeError('Invalid telegram_posts array')
        seen = {key(x) for x in target if isinstance(x, dict) and x.get('source_post_id')}
        additions = [item for k, item in items.items() if k not in seen]
        if not additions:
            return 0
        target.extend(additions)
        archive['last_archived_at'] = datetime.now(timezone.utc).isoformat()
        payload = {'message': f'Append Telegram editorial records {day}',
                   'content': base64.b64encode((json.dumps(archive, ensure_ascii=False, indent=2) + '\n').encode('utf-8')).decode('ascii')}
        if sha:
            payload['sha'] = sha
        try:
            github('PUT', path, payload)
            return len(additions)
        except RuntimeError as exc:
            if ('HTTP 409' not in str(exc) and 'HTTP 422' not in str(exc)) or attempt == 4:
                raise
            time.sleep(2 ** attempt)
    return 0


def main():
    if not os.getenv('EDITORIAL_GITHUB_TOKEN'):
        raise RuntimeError('EDITORIAL_GITHUB_TOKEN is required')
    by_day, total = collect()
    print(f'Telegram CollectedPost candidates: {total}')
    added = 0
    for day, items in sorted(by_day.items()):
        count = append_archive(day, items)
        added += count
        print(f'{day}: {count} Telegram posts archived')
    print(f'Telegram editorial archive complete: {added} added. AI handled by unified module.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'TELEGRAM EDITORIAL BRIDGE ERROR: {exc}', file=sys.stderr)
        sys.exit(1)

