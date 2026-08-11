"""
Migration OSINT Monitor

File:
tools/x_full_archive_test.py

Purpose:
A SAFE, read-only X full-archive capability test.

This script:
- uses the existing X_BEARER_TOKEN environment secret,
- calls ONLY GET /2/tweets/search/all,
- queries one small historical time window,
- requests at most 10 posts,
- does NOT write to SQLite,
- does NOT modify dashboard-data.json,
- does NOT run Reddit or Mastodon,
- prints enough information to confirm whether full-archive access works.

Default test window:
2026-06-15 08:00:00 UTC -> 2026-06-15 09:00:00 UTC
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

import requests


API_URL = "https://api.x.com/2/tweets/search/all"

DEFAULT_QUERY = (
    "(migration OR migrant OR migrants OR refugee OR refugees OR asylum)"
    " -is:retweet"
)

DEFAULT_START_TIME = "2026-06-15T08:00:00Z"
DEFAULT_END_TIME = "2026-06-15T09:00:00Z"
DEFAULT_MAX_RESULTS = 10


def env_value(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {
            "_raw_text": response.text[:4000],
        }

    if isinstance(payload, dict):
        return payload

    return {
        "_payload": payload,
    }


def print_api_error(
    response: requests.Response,
    payload: Dict[str, Any],
) -> None:
    print("")
    print("========================================")
    print("X FULL-ARCHIVE TEST FAILED")
    print("========================================")
    print(f"HTTP status: {response.status_code}")

    title = payload.get("title")
    detail = payload.get("detail")
    error_type = payload.get("type")

    if title:
        print(f"Title: {title}")

    if detail:
        print(f"Detail: {detail}")

    if error_type:
        print(f"Type: {error_type}")

    errors = payload.get("errors")

    if errors:
        print("Errors:")
        print(
            json.dumps(
                errors,
                indent=2,
                ensure_ascii=False,
            )
        )

    if "_raw_text" in payload:
        print("Raw response:")
        print(payload["_raw_text"])

    print("")
    print("Interpretation:")
    print(
        "- 401 usually means an authentication/token problem."
    )
    print(
        "- 403 usually means the endpoint is not available "
        "for this project/account or the request is forbidden."
    )
    print(
        "- 429 means rate/usage limits were reached."
    )
    print(
        "- Other 4xx responses should be read from the API "
        "error message above."
    )


def main() -> int:
    bearer_token = os.getenv(
        "X_BEARER_TOKEN",
        "",
    ).strip()

    if not bearer_token:
        print(
            "ERROR: X_BEARER_TOKEN environment variable is missing."
        )
        return 2

    query = env_value(
        "X_FULL_ARCHIVE_TEST_QUERY",
        DEFAULT_QUERY,
    )

    start_time = env_value(
        "X_FULL_ARCHIVE_TEST_START_TIME",
        DEFAULT_START_TIME,
    )

    end_time = env_value(
        "X_FULL_ARCHIVE_TEST_END_TIME",
        DEFAULT_END_TIME,
    )

    raw_max_results = env_value(
        "X_FULL_ARCHIVE_TEST_MAX_RESULTS",
        str(DEFAULT_MAX_RESULTS),
    )

    try:
        max_results = int(
            raw_max_results
        )
    except ValueError:
        print(
            "ERROR: X_FULL_ARCHIVE_TEST_MAX_RESULTS must be an integer."
        )
        return 2

    # X full-archive Search Posts All currently requires max_results 10..500.
    max_results = max(
        10,
        min(
            max_results,
            10,  # keep the capability test deliberately capped at 10
        ),
    )

    params = {
        "query": query,
        "start_time": start_time,
        "end_time": end_time,
        "max_results": max_results,
        "sort_order": "recency",
        "tweet.fields": (
            "id,text,author_id,created_at,lang,"
            "conversation_id,public_metrics"
        ),
        "expansions": "author_id",
        "user.fields": "id,name,username,verified",
    }

    headers = {
        "Authorization": (
            f"Bearer {bearer_token}"
        ),
        "User-Agent": (
            "Migration-OSINT-Monitor/"
            "X-Full-Archive-Capability-Test"
        ),
    }

    print(
        "========================================"
    )
    print(
        "X FULL-ARCHIVE CAPABILITY TEST"
    )
    print(
        "========================================"
    )
    print(
        f"Endpoint: {API_URL}"
    )
    print(
        f"Start:    {start_time}"
    )
    print(
        f"End:      {end_time}"
    )
    print(
        f"Max posts requested: {max_results}"
    )
    print(
        f"Query: {query}"
    )
    print(
        "Database writes: DISABLED"
    )
    print(
        "Reddit/Mastodon: DISABLED"
    )
    print("")

    try:
        response = requests.get(
            API_URL,
            headers=headers,
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        print(
            "NETWORK ERROR:"
        )
        print(
            str(exc)
        )
        return 3

    payload = safe_json(
        response
    )

    if response.status_code != 200:
        print_api_error(
            response,
            payload,
        )
        return 1

    data = payload.get(
        "data",
        [],
    )

    meta = payload.get(
        "meta",
        {},
    )

    includes = payload.get(
        "includes",
        {},
    )

    users = {
        str(user.get("id")): user
        for user in includes.get(
            "users",
            [],
        )
        if isinstance(
            user,
            dict,
        )
    }

    print(
        "========================================"
    )
    print(
        "SUCCESS: FULL-ARCHIVE ENDPOINT WORKS"
    )
    print(
        "========================================"
    )
    print(
        f"HTTP status: {response.status_code}"
    )
    print(
        f"Result count: {meta.get('result_count', len(data))}"
    )
    print(
        f"Newest ID: {meta.get('newest_id', '-')}"
    )
    print(
        f"Oldest ID: {meta.get('oldest_id', '-')}"
    )
    print(
        f"Pagination token present: "
        f"{bool(meta.get('next_token'))}"
    )
    print("")

    if not data:
        print(
            "The endpoint is accessible, but this exact one-hour "
            "query returned no posts."
        )
        print(
            "That is still a SUCCESSFUL capability test."
        )
        return 0

    print(
        "POST PREVIEW"
    )
    print(
        "----------------------------------------"
    )

    for index, post in enumerate(
        data,
        start=1,
    ):
        author_id = str(
            post.get(
                "author_id",
                "",
            )
        )

        user = users.get(
            author_id,
            {},
        )

        username = user.get(
            "username",
            "-",
        )

        created_at = post.get(
            "created_at",
            "-",
        )

        post_id = post.get(
            "id",
            "-",
        )

        lang = post.get(
            "lang",
            "-",
        )

        post_text = str(
            post.get(
                "text",
                "",
            )
        ).replace(
            "\n",
            " ",
        )

        if len(post_text) > 240:
            post_text = (
                post_text[:237]
                + "..."
            )

        print(
            f"{index}. {created_at} | @{username} | "
            f"lang={lang} | id={post_id}"
        )
        print(
            f"   {post_text}"
        )

    print("")
    print(
        "NEXT STEP:"
    )
    print(
        "If this workflow succeeds, the account can use "
        "GET /2/tweets/search/all and we can build the "
        "X-only historical backfill safely."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
