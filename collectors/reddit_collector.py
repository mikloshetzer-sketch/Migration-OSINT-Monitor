"""
Migration OSINT Monitor

File:
reddit_collector.py

Description:
Reddit RSS collector for recent migration-related posts.

The collector uses Reddit's publicly available RSS search/feed
output and does not require Reddit OAuth credentials.

Normalized output is intentionally aligned with XCollector so
that Reddit posts can enter the same Migration OSINT analytical
pipeline:

- Noise Filter
- Influence Signal Detector
- Operational Event Filter
- Signal Classification
- Location Extraction
- Time Extraction
- Region Resolution
- Correlation
- Event Groups
- Database Storage
"""

import hashlib
import re

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from urllib.parse import quote_plus

import feedparser


class RedditCollector:
    """
    Collects recent Reddit posts through public RSS feeds.

    No Reddit CLIENT_ID or CLIENT_SECRET is required.

    The collector exposes a search_recent() method compatible
    with the interface currently used by XCollector.
    """

    BASE_URL = "https://www.reddit.com"

    SEARCH_ENDPOINT = "/search.rss"

    REQUEST_TIMEOUT = 30

    USER_AGENT = (
        "MigrationOSINTMonitor/1.0 "
        "(OSINT research RSS collector)"
    )

    def __init__(self):
        """
        Initializes the Reddit RSS collector.
        """

        feedparser.USER_AGENT = (
            self.USER_AGENT
        )

    # ======================================================
    # CONFIGURATION
    # ======================================================

    def is_configured(self) -> bool:
        """
        Reddit RSS does not require API credentials.

        Returns:
            Always True.
        """

        return True

    # ======================================================
    # PUBLIC SEARCH
    # ======================================================

    def search_recent(
        self,
        query: str,
        max_results: int = 100,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Searches recent Reddit posts through Reddit RSS search.

        Args:
            query:
                Search query.

            max_results:
                Maximum number of normalized Reddit posts
                returned.

            max_pages:
                Accepted for compatibility with XCollector.

                Reddit RSS currently does not use the same
                pagination model as the X API, therefore this
                value is not used in the first implementation.

        Returns:
            List of normalized post dictionaries.
        """

        if not query or not query.strip():
            raise ValueError(
                "Reddit search query cannot be empty."
            )

        if max_results < 1:
            max_results = 1

        if max_results > 100:
            max_results = 100

        rss_url = self._build_search_url(
            query=query,
        )

        feed = self._parse_feed(
            rss_url
        )

        entries = (
            getattr(
                feed,
                "entries",
                [],
            )
            or []
        )

        posts: List[
            Dict[str, Any]
        ] = []

        seen_post_ids = set()

        for entry in entries:

            normalized_post = (
                self._normalize_entry(
                    entry
                )
            )

            if not normalized_post:
                continue

            post_id = (
                normalized_post.get(
                    "post_id"
                )
            )

            if (
                post_id
                and post_id
                in seen_post_ids
            ):
                continue

            if post_id:
                seen_post_ids.add(
                    post_id
                )

            posts.append(
                normalized_post
            )

            if len(posts) >= max_results:
                break

        return posts

    # ======================================================
    # SUBREDDIT FEED
    # ======================================================

    def fetch_subreddit(
        self,
        subreddit: str,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves recent posts from a specific subreddit RSS.

        This is not required by the current main.py, but is
        included because later we may want targeted migration
        subreddit monitoring in addition to global search.

        Example:

            collector.fetch_subreddit(
                "immigration",
                max_results=25,
            )
        """

        if not subreddit:
            raise ValueError(
                "Subreddit cannot be empty."
            )

        subreddit = (
            subreddit
            .strip()
            .replace(
                "r/",
                "",
            )
            .strip("/")
        )

        if max_results < 1:
            max_results = 1

        if max_results > 100:
            max_results = 100

        rss_url = (
            f"{self.BASE_URL}"
            f"/r/{subreddit}/new/.rss"
        )

        feed = self._parse_feed(
            rss_url
        )

        entries = (
            getattr(
                feed,
                "entries",
                [],
            )
            or []
        )

        posts: List[
            Dict[str, Any]
        ] = []

        seen_post_ids = set()

        for entry in entries:

            normalized_post = (
                self._normalize_entry(
                    entry,
                    subreddit_hint=subreddit,
                )
            )

            if not normalized_post:
                continue

            post_id = (
                normalized_post.get(
                    "post_id"
                )
            )

            if (
                post_id
                and post_id
                in seen_post_ids
            ):
                continue

            if post_id:
                seen_post_ids.add(
                    post_id
                )

            posts.append(
                normalized_post
            )

            if len(posts) >= max_results:
                break

        return posts

    # ======================================================
    # SEARCH URL
    # ======================================================

    def _build_search_url(
        self,
        query: str,
    ) -> str:
        """
        Builds a Reddit RSS search URL.

        sort=new:
            newest posts first

        t=week:
            keeps the feed focused on recent material
        """

        encoded_query = quote_plus(
            query.strip()
        )

        return (
            f"{self.BASE_URL}"
            f"{self.SEARCH_ENDPOINT}"
            f"?q={encoded_query}"
            f"&sort=new"
            f"&t=week"
        )

    # ======================================================
    # RSS PARSING
    # ======================================================

    def _parse_feed(
        self,
        url: str,
    ):
        """
        Loads an RSS feed using feedparser.
        """

        feedparser.USER_AGENT = (
            self.USER_AGENT
        )

        feed = feedparser.parse(
            url,
            request_headers={
                "User-Agent":
                    self.USER_AGENT,

                "Accept":
                    (
                        "application/rss+xml,"
                        "application/atom+xml,"
                        "application/xml,"
                        "text/xml"
                    ),
            },
        )

        return feed

    # ======================================================
    # NORMALIZATION
    # ======================================================

    def _normalize_entry(
        self,
        entry,
        subreddit_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Converts one Reddit RSS item into the same basic
        internal format used by XCollector.
        """

        title = (
            getattr(
                entry,
                "title",
                "",
            )
            or ""
        )

        link = (
            getattr(
                entry,
                "link",
                "",
            )
            or ""
        )

        summary = (
            getattr(
                entry,
                "summary",
                "",
            )
            or getattr(
                entry,
                "description",
                "",
            )
            or ""
        )

        body = (
            self._strip_html(
                summary
            )
        )

        title = (
            self._clean_text(
                title
            )
        )

        body = (
            self._clean_text(
                body
            )
        )

        text = (
            self._combine_title_and_body(
                title=title,
                body=body,
            )
        )

        if not text:
            return None

        reddit_id = (
            self._extract_reddit_id(
                entry=entry,
                link=link,
            )
        )

        author = (
            self._extract_author(
                entry
            )
        )

        published_at = (
            self._extract_published_at(
                entry
            )
        )

        subreddit = (
            self._extract_subreddit(
                entry=entry,
                link=link,
                subreddit_hint=subreddit_hint,
            )
        )

        post_id = (
            reddit_id
            or self._generate_post_id(
                link=link,
                title=title,
                published_at=published_at,
            )
        )

        return {
            # ----------------------------------------------
            # CORE FIELDS
            # ----------------------------------------------

            "source":
                "REDDIT",

            "post_id":
                post_id,

            "author_id":
                author,

            "author":
                author,

            "author_name":
                author,

            "author_location":
                None,

            "author_verified":
                None,

            "text":
                text,

            "language":
                None,

            "published_at":
                published_at,

            "conversation_id":
                post_id,

            "public_metrics":
                {},

            "url":
                link or None,

            # ----------------------------------------------
            # REDDIT-SPECIFIC OPTIONAL METADATA
            # ----------------------------------------------

            "subreddit":
                subreddit,

            "title":
                title,
        }

    # ======================================================
    # TEXT
    # ======================================================

    def _combine_title_and_body(
        self,
        *,
        title: str,
        body: str,
    ) -> str:
        """
        Combines Reddit title and body while avoiding
        unnecessary duplication.
        """

        title = (
            title.strip()
            if title
            else ""
        )

        body = (
            body.strip()
            if body
            else ""
        )

        if not title:
            return body

        if not body:
            return title

        if (
            title.lower()
            in body.lower()
        ):
            return body

        return (
            f"{title}\n{body}"
        )

    def _strip_html(
        self,
        text: str,
    ) -> str:
        """
        Removes HTML produced by Reddit RSS summaries.
        """

        if not text:
            return ""

        text = re.sub(
            r"<br\s*/?>",
            "\n",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"</p\s*>",
            "\n",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"<[^>]+>",
            " ",
            text,
        )

        replacements = {
            "&amp;": "&",
            "&lt;": "<",
            "&gt;": ">",
            "&quot;": '"',
            "&#39;": "'",
            "&apos;": "'",
            "&nbsp;": " ",
        }

        for old, new in replacements.items():

            text = text.replace(
                old,
                new,
            )

        return text

    def _clean_text(
        self,
        text: str,
    ) -> str:
        """
        Normalizes whitespace while preserving paragraphs.
        """

        if not text:
            return ""

        text = text.replace(
            "\r",
            "\n",
        )

        text = re.sub(
            r"[ \t]+",
            " ",
            text,
        )

        text = re.sub(
            r"\n\s*\n+",
            "\n",
            text,
        )

        return text.strip()

    # ======================================================
    # AUTHOR
    # ======================================================

    def _extract_author(
        self,
        entry,
    ) -> Optional[str]:
        """
        Extracts Reddit author name from RSS metadata.
        """

        author = (
            getattr(
                entry,
                "author",
                None,
            )
        )

        if author:

            author = str(
                author
            ).strip()

            author = re.sub(
                r"^/u/",
                "",
                author,
                flags=re.IGNORECASE,
            )

            author = re.sub(
                r"^u/",
                "",
                author,
                flags=re.IGNORECASE,
            )

            if author:
                return author

        author_detail = (
            getattr(
                entry,
                "author_detail",
                None,
            )
        )

        if author_detail:

            try:

                name = (
                    author_detail.get(
                        "name"
                    )
                )

            except AttributeError:

                name = None

            if name:

                return str(
                    name
                ).strip()

        return None

    # ======================================================
    # SUBREDDIT
    # ======================================================

    def _extract_subreddit(
        self,
        *,
        entry,
        link: str,
        subreddit_hint: Optional[str],
    ) -> Optional[str]:
        """
        Attempts to identify the subreddit.
        """

        if subreddit_hint:

            return subreddit_hint

        if link:

            match = re.search(
                r"reddit\.com/r/([^/]+)/",
                link,
                flags=re.IGNORECASE,
            )

            if match:

                return match.group(
                    1
                )

        tags = (
            getattr(
                entry,
                "tags",
                [],
            )
            or []
        )

        for tag in tags:

            try:

                term = tag.get(
                    "term"
                )

            except AttributeError:

                term = None

            if not term:
                continue

            term = str(
                term
            )

            match = re.search(
                r"(?:^|/)r/([^/\s]+)",
                term,
                flags=re.IGNORECASE,
            )

            if match:

                return match.group(
                    1
                )

        return None

    # ======================================================
    # POST ID
    # ======================================================

    def _extract_reddit_id(
        self,
        *,
        entry,
        link: str,
    ) -> Optional[str]:
        """
        Extracts a stable Reddit submission ID when possible.
        """

        entry_id = (
            getattr(
                entry,
                "id",
                None,
            )
        )

        if entry_id:

            entry_id = str(
                entry_id
            )

            match = re.search(
                r"(?:t3_)?([a-z0-9]{5,12})$",
                entry_id,
                flags=re.IGNORECASE,
            )

            if match:

                return (
                    "reddit_"
                    + match.group(
                        1
                    )
                )

        if link:

            match = re.search(
                r"/comments/([a-z0-9]+)/",
                link,
                flags=re.IGNORECASE,
            )

            if match:

                return (
                    "reddit_"
                    + match.group(
                        1
                    )
                )

        return None

    def _generate_post_id(
        self,
        *,
        link: str,
        title: str,
        published_at: Optional[str],
    ) -> str:
        """
        Generates deterministic fallback ID.

        Python's built-in hash() is intentionally not used
        because it is not guaranteed to remain stable across
        different process runs.
        """

        seed = (
            f"{link}|"
            f"{title}|"
            f"{published_at}"
        )

        digest = (
            hashlib.sha256(
                seed.encode(
                    "utf-8"
                )
            )
            .hexdigest()[:20]
        )

        return (
            f"reddit_{digest}"
        )

    # ======================================================
    # PUBLICATION TIME
    # ======================================================

    def _extract_published_at(
        self,
        entry,
    ) -> Optional[str]:
        """
        Converts RSS publication metadata into an ISO-8601
        UTC timestamp compatible with the rest of the system.
        """

        published_parsed = (
            getattr(
                entry,
                "published_parsed",
                None,
            )
        )

        if published_parsed:

            try:

                dt = datetime(
                    *published_parsed[:6],
                    tzinfo=timezone.utc,
                )

                return (
                    dt.isoformat()
                    .replace(
                        "+00:00",
                        "Z",
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        updated_parsed = (
            getattr(
                entry,
                "updated_parsed",
                None,
            )
        )

        if updated_parsed:

            try:

                dt = datetime(
                    *updated_parsed[:6],
                    tzinfo=timezone.utc,
                )

                return (
                    dt.isoformat()
                    .replace(
                        "+00:00",
                        "Z",
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        published = (
            getattr(
                entry,
                "published",
                None,
            )
            or getattr(
                entry,
                "updated",
                None,
            )
        )

        if published:

            return str(
                published
            )

        return None


# ==========================================================
# MANUAL TEST
# ==========================================================

if __name__ == "__main__":

    collector = (
        RedditCollector()
    )

    test_query = (
        "migrant border crossing"
    )

    print(
        "==================================="
    )

    print(
        "Reddit Collector Test"
    )

    print(
        "==================================="
    )

    print(
        "Query:",
        test_query,
    )

    print(
        "-----------------------------------"
    )

    posts = (
        collector.search_recent(
            query=test_query,
            max_results=10,
            max_pages=1,
        )
    )

    print(
        "Posts collected:",
        len(posts),
    )

    for index, post in enumerate(
        posts,
        start=1,
    ):

        print()

        print(
            "-----------------------------------"
        )

        print(
            f"POST {index}"
        )

        print(
            "-----------------------------------"
        )

        print(
            "Source:",
            post.get(
                "source"
            ),
        )

        print(
            "Post ID:",
            post.get(
                "post_id"
            ),
        )

        print(
            "Subreddit:",
            post.get(
                "subreddit"
            ),
        )

        print(
            "Author:",
            post.get(
                "author"
            ),
        )

        print(
            "Published:",
            post.get(
                "published_at"
            ),
        )

        print(
            "Title:",
            post.get(
                "title"
            ),
        )

        print(
            "Text:",
            post.get(
                "text"
            ),
        )

        print(
            "URL:",
            post.get(
                "url"
            ),
        )
