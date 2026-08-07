"""
Migration OSINT Monitor

File:
x_collector.py

Description:
X API collector for recent and historical migration-related posts.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import requests

from config import X_BEARER_TOKEN


class XCollector:
    """
    Handles communication with the X API v2.
    """

    BASE_URL = "https://api.x.com/2"

    RECENT_SEARCH_ENDPOINT = "/tweets/search/recent"
    FULL_ARCHIVE_ENDPOINT = "/tweets/search/all"

    REQUEST_TIMEOUT = 30

    def __init__(self):
        if not X_BEARER_TOKEN:
            raise ValueError(
                "X_BEARER_TOKEN is not configured. "
                "Add it to the environment or GitHub Actions secrets."
            )

        self.headers = {
            "Authorization": f"Bearer {X_BEARER_TOKEN}",
            "User-Agent": "MigrationOSINTMonitor/1.0",
        }

    def is_configured(self) -> bool:
        """
        Returns True if an X Bearer Token is configured.
        """
        return bool(X_BEARER_TOKEN)

    def search_recent(
        self,
        query: str,
        max_results: int = 100,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Searches public X posts from the recent-search window.

        The X recent search endpoint currently covers the last 7 days.

        Args:
            query:
                X API search query.

            max_results:
                Number of posts requested per API page.

            max_pages:
                Maximum number of pages to retrieve.
                None means continue until there is no next page.

        Returns:
            List of normalized post dictionaries.
        """

        return self._search(
            endpoint=self.RECENT_SEARCH_ENDPOINT,
            query=query,
            max_results=max_results,
            max_pages=max_pages,
        )

    def search_archive(
        self,
        query: str,
        start_time: datetime,
        end_time: datetime,
        max_results: int = 100,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Searches the X full archive.

        This endpoint requires an X API access level that supports
        full-archive search.

        Args:
            query:
                X API search query.

            start_time:
                Beginning of the search period.

            end_time:
                End of the search period.

            max_results:
                Number of posts requested per API page.

            max_pages:
                Maximum number of pages to retrieve.
                None means continue until there is no next page.

        Returns:
            List of normalized post dictionaries.
        """

        if start_time >= end_time:
            raise ValueError("start_time must be earlier than end_time.")

        return self._search(
            endpoint=self.FULL_ARCHIVE_ENDPOINT,
            query=query,
            start_time=start_time,
            end_time=end_time,
            max_results=max_results,
            max_pages=max_pages,
        )

    def _search(
        self,
        endpoint: str,
        query: str,
        max_results: int,
        max_pages: Optional[int],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Internal search method with pagination support.
        """

        if not query or not query.strip():
            raise ValueError("Search query cannot be empty.")

        if max_results < 10:
            max_results = 10

        if max_results > 100:
            max_results = 100

        url = f"{self.BASE_URL}{endpoint}"

        params: Dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "tweet.fields": (
                "id,text,author_id,created_at,lang,"
                "conversation_id,public_metrics"
            ),
            "expansions": "author_id",
            "user.fields": "id,name,username,location,verified",
        }

        if start_time is not None:
            params["start_time"] = self._to_x_timestamp(start_time)

        if end_time is not None:
            params["end_time"] = self._to_x_timestamp(end_time)

        all_posts: List[Dict[str, Any]] = []

        next_token: Optional[str] = None
        page_number = 0

        while True:
            request_params = params.copy()

            if next_token:
                request_params["next_token"] = next_token

            response = requests.get(
                url,
                headers=self.headers,
                params=request_params,
                timeout=self.REQUEST_TIMEOUT,
            )

            self._raise_for_api_error(response)

            payload = response.json()

            users = self._build_user_lookup(payload)

            posts = payload.get("data", [])

            for post in posts:
                normalized_post = self._normalize_post(
                    post=post,
                    users=users,
                )

                all_posts.append(normalized_post)

            page_number += 1

            meta = payload.get("meta", {})
            next_token = meta.get("next_token")

            if not next_token:
                break

            if max_pages is not None and page_number >= max_pages:
                break

        return all_posts

    def _normalize_post(
        self,
        post: Dict[str, Any],
        users: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Converts an X API post into the internal collector format.
        """

        author_id = post.get("author_id")

        author_data = users.get(
            author_id,
            {},
        )

        username = author_data.get("username")

        post_id = post.get("id")

        if username and post_id:
            url = f"https://x.com/{username}/status/{post_id}"
        else:
            url = None

        return {
            "source": "X",
            "post_id": post_id,
            "author_id": author_id,
            "author": username,
            "author_name": author_data.get("name"),
            "author_location": author_data.get("location"),
            "author_verified": author_data.get("verified"),
            "text": post.get("text", ""),
            "language": post.get("lang"),
            "published_at": post.get("created_at"),
            "conversation_id": post.get("conversation_id"),
            "public_metrics": post.get("public_metrics", {}),
            "url": url,
        }

    def _build_user_lookup(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Builds an author lookup table from the API includes section.
        """

        includes = payload.get("includes", {})
        users = includes.get("users", [])

        return {
            user["id"]: user
            for user in users
            if user.get("id")
        }

    def _to_x_timestamp(
        self,
        value: datetime,
    ) -> str:
        """
        Converts a datetime to RFC3339 UTC format required by X.
        """

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)

        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _raise_for_api_error(
        self,
        response: requests.Response,
    ) -> None:
        """
        Converts common X API errors into readable exceptions.
        """

        if response.ok:
            return

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        detail = (
            payload.get("detail")
            or payload.get("title")
            or response.text
        )

        if response.status_code == 401:
            raise RuntimeError(
                "X API authentication failed. "
                "Check X_BEARER_TOKEN."
            )

        if response.status_code == 403:
            raise RuntimeError(
                "X API returned HTTP 403. "
                "The current API project may not have permission "
                "to use this endpoint."
            )

        if response.status_code == 429:
            raise RuntimeError(
                "X API rate limit reached. "
                "Wait before running another request."
            )

        raise RuntimeError(
            f"X API request failed "
            f"(HTTP {response.status_code}): {detail}"
        )
