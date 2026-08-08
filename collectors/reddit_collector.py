"""
Migration OSINT Monitor

File:
reddit_collector.py

Description:
Reddit RSS collector for recent migration-related posts.

This collector uses Reddit's public RSS search and does not
require OAuth credentials.

The collector is designed for the Migration OSINT Monitor and
returns normalized post dictionaries compatible with the same
analysis pipeline used for X posts.

Key design:

1. Accept one migration-related query.
2. Convert complex boolean-style queries into simpler Reddit
   RSS search phrases.
3. Run several smaller searches.
4. Merge and deduplicate the results.
5. Return normalized Reddit posts.

This approach is used because Reddit RSS search is less reliable
with deeply nested boolean expressions than the X API.
"""

import hashlib
import html
import re
from collections import defaultdict

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from urllib.parse import quote_plus

import feedparser


class RedditCollector:
    """
    Collects recent Reddit posts using public Reddit RSS feeds.
    """

    BASE_URL = "https://www.reddit.com"

    SEARCH_ENDPOINT = "/search.rss"

    USER_AGENT = (
        "MigrationOSINTMonitor/1.1 "
        "(public RSS OSINT research collector)"
    )

    # Maximum number of simple RSS queries generated from one
    # logical query.
    MAX_EXPANDED_QUERIES = 24

    # Maximum number of items accepted from one individual
    # Reddit RSS result set before moving to the next query.
    PER_QUERY_RESULT_LIMIT = 8

    DEFAULT_RECENCY = "week"

    # Migration-context seed terms are used only to keep the
    # Reddit searches human-migration focused. They do not
    # replace the downstream analytical filters.
    MIGRATION_SEED_TERMS = [
        "migrant",
        "migrants",
        "refugee",
        "refugees",
        "asylum",
        "immigrant",
        "immigrants",
    ]

    # Small multilingual expansion for global monitoring.
    # These are intentionally generic and not tied to Ceuta,
    # Morocco or any other specific route/location.
    MULTILINGUAL_MIGRATION_TERMS = [
        "migrante",
        "migrantes",
        "refugiado",
        "refugiados",
        "réfugié",
        "réfugiés",
        "migrante italiano",
        "migranti",
    ]

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(self):
        """
        Initializes the RSS collector.
        """

        feedparser.USER_AGENT = (
            self.USER_AGENT
        )

    # ======================================================
    # CONFIGURATION
    # ======================================================

    def is_configured(self) -> bool:
        """
        Public Reddit RSS search does not require credentials.
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
        Searches recent Reddit posts.

        Complex boolean queries are expanded into multiple
        simpler RSS searches. Results are gathered in a
        balanced way so that one successful sub-query cannot
        consume the entire result budget.

        Args:
            query:
                Migration-related logical search query.

            max_results:
                Maximum number of unique normalized Reddit posts
                returned.

            max_pages:
                Accepted for compatibility with XCollector.
                Reddit RSS does not use the same pagination model.

        Returns:
            List of normalized post dictionaries.
        """

        if not query or not query.strip():
            raise ValueError(
                "Reddit search query cannot be empty."
            )

        max_results = max(
            1,
            min(
                int(max_results),
                100,
            ),
        )

        expanded_queries = self._expand_query(
            query
        )

        if not expanded_queries:
            return []

        # First collect a small slice from each individual
        # query. This prevents the first productive RSS feed
        # from filling the full result budget.
        query_buckets: Dict[
            str,
            List[Dict[str, Any]]
        ] = {}

        for simple_query in expanded_queries:

            rss_url = self._build_search_url(
                simple_query
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

            bucket: List[
                Dict[str, Any]
            ] = []

            local_seen = set()

            for entry in entries:

                normalized_post = self._normalize_entry(
                    entry=entry,
                    search_query=simple_query,
                )

                if not normalized_post:
                    continue

                post_id = normalized_post.get(
                    "post_id"
                )

                if not post_id:
                    continue

                if post_id in local_seen:
                    continue

                local_seen.add(
                    post_id
                )

                bucket.append(
                    normalized_post
                )

                if (
                    len(bucket)
                    >= self.PER_QUERY_RESULT_LIMIT
                ):
                    break

            query_buckets[
                simple_query
            ] = bucket

        # --------------------------------------------------
        # ROUND-ROBIN MERGE
        # --------------------------------------------------
        #
        # Take one item from each productive query in turn.
        # This provides better topical spread than appending
        # all results from the first successful query.
        # --------------------------------------------------

        merged_posts: List[
            Dict[str, Any]
        ] = []

        seen_ids = set()

        max_bucket_size = max(
            (
                len(bucket)
                for bucket
                in query_buckets.values()
            ),
            default=0,
        )

        for position in range(
            max_bucket_size
        ):

            for simple_query in expanded_queries:

                bucket = query_buckets.get(
                    simple_query,
                    [],
                )

                if position >= len(bucket):
                    continue

                post = bucket[
                    position
                ]

                post_id = post.get(
                    "post_id"
                )

                if not post_id:
                    continue

                if post_id in seen_ids:
                    continue

                seen_ids.add(
                    post_id
                )

                merged_posts.append(
                    post
                )

                if (
                    len(merged_posts)
                    >= max_results
                ):
                    return merged_posts

        return merged_posts

    # ======================================================
    # QUERY EXPANSION
    # ======================================================

    def _expand_query(
        self,
        query: str,
    ) -> List[str]:
        """
        Converts a complex migration query into balanced,
        Reddit-friendly simple search phrases.

        Design goals:

        - avoid deeply nested boolean expressions,
        - keep searches tied to human migration,
        - cover several terms from every concept group,
        - avoid location-specific hard-coding,
        - provide a small multilingual fallback layer.
        """

        cleaned_query = self._clean_query(
            query
        )

        if not cleaned_query:
            return []

        groups = self._extract_parenthesized_groups(
            cleaned_query
        )

        results: List[str] = []

        # --------------------------------------------------
        # TWO OR MORE BOOLEAN GROUPS
        # --------------------------------------------------

        if len(groups) >= 2:

            first_group = self._split_or_terms(
                groups[0]
            )

            second_group = self._split_or_terms(
                groups[1]
            )

            first_terms = self._prioritize_migration_terms(
                first_group
            )

            second_terms = self._prioritize_topic_terms(
                second_group
            )

            # Phase 1:
            # ensure each secondary topic gets coverage with
            # several migration-context words.
            for second_term in second_terms:

                for first_term in first_terms[:4]:

                    self._append_unique_query(
                        results,
                        f"{first_term} {second_term}",
                    )

                    if (
                        len(results)
                        >= self.MAX_EXPANDED_QUERIES
                    ):
                        return results

            # Phase 2:
            # reverse ordering produces useful natural-language
            # variants because Reddit search ranking can differ
            # between "migrant border" and "border migrant".
            for second_term in second_terms[:6]:

                for first_term in first_terms[:2]:

                    self._append_unique_query(
                        results,
                        f"{second_term} {first_term}",
                    )

                    if (
                        len(results)
                        >= self.MAX_EXPANDED_QUERIES
                    ):
                        return results

            return results

        # --------------------------------------------------
        # ONE BOOLEAN GROUP
        # --------------------------------------------------

        if len(groups) == 1:

            group_terms = self._split_or_terms(
                groups[0]
            )

            prioritized = self._prioritize_migration_terms(
                group_terms
            )

            for term in prioritized:

                self._append_unique_query(
                    results,
                    term,
                )

            # Add a small multilingual layer only for broad
            # migration queries.
            if self._looks_like_general_migration_query(
                prioritized
            ):

                for term in self.MULTILINGUAL_MIGRATION_TERMS:

                    self._append_unique_query(
                        results,
                        term,
                    )

                    if (
                        len(results)
                        >= self.MAX_EXPANDED_QUERIES
                    ):
                        break

            return results[
                :self.MAX_EXPANDED_QUERIES
            ]

        # --------------------------------------------------
        # NO PARENTHESIZED GROUPS
        # --------------------------------------------------

        or_terms = self._split_or_terms(
            cleaned_query
        )

        if len(or_terms) > 1:

            for term in self._prioritize_migration_terms(
                or_terms
            ):

                self._append_unique_query(
                    results,
                    term,
                )

            return results[
                :self.MAX_EXPANDED_QUERIES
            ]

        return [
            cleaned_query
        ]

    def _append_unique_query(
        self,
        results: List[str],
        value: str,
    ) -> None:
        """
        Adds a normalized search phrase only once.
        """

        value = re.sub(
            r"\s+",
            " ",
            value or "",
        ).strip()

        if not value:
            return

        if value not in results:
            results.append(
                value
            )

    def _prioritize_migration_terms(
        self,
        terms: List[str],
    ) -> List[str]:
        """
        Orders migration words so the most useful human
        migration terms are searched before generic language.
        """

        normalized = []

        for term in terms:

            cleaned = re.sub(
                r"\s+",
                " ",
                term or "",
            ).strip()

            if (
                cleaned
                and cleaned
                not in normalized
            ):
                normalized.append(
                    cleaned
                )

        priority = {
            value: index
            for index, value
            in enumerate(
                self.MIGRATION_SEED_TERMS
            )
        }

        return sorted(
            normalized,
            key=lambda value: (
                priority.get(
                    value.lower(),
                    999,
                ),
                len(value),
                value.lower(),
            ),
        )

    def _prioritize_topic_terms(
        self,
        terms: List[str],
    ) -> List[str]:
        """
        Keeps topic coverage broad instead of repeatedly using
        only the first few OR terms.
        """

        normalized = []

        for term in terms:

            cleaned = re.sub(
                r"\s+",
                " ",
                term or "",
            ).strip()

            if (
                cleaned
                and cleaned
                not in normalized
            ):
                normalized.append(
                    cleaned
                )

        # Prefer concrete operational terms before generic ones.
        preferred = [
            "crossing",
            "border",
            "route",
            "checkpoint",
            "patrol",
            "boat",
            "vessel",
            "sea",
            "coast guard",
            "rescue",
            "intercepted",
            "smuggler",
            "smuggling",
            "trafficking",
            "transport",
            "driver",
            "departure",
            "departing",
            "leaving",
            "arrived",
            "arrival",
        ]

        ranking = {
            value: index
            for index, value
            in enumerate(
                preferred
            )
        }

        return sorted(
            normalized,
            key=lambda value: (
                ranking.get(
                    value.lower(),
                    999,
                ),
                len(value),
                value.lower(),
            ),
        )

    def _looks_like_general_migration_query(
        self,
        terms: List[str],
    ) -> bool:
        """
        Returns True when a one-group query is broadly about
        migration rather than a narrow technical topic.
        """

        migration_terms = {
            value.lower()
            for value
            in self.MIGRATION_SEED_TERMS
        }

        hits = sum(
            1
            for term in terms
            if term.lower()
            in migration_terms
        )

        return hits >= 2

    # ======================================================
    # QUERY CLEANING
    # ======================================================

    def _clean_query(
        self,
        query: str,
    ) -> str:
        """
        Removes operators that are useful on X but not useful
        for Reddit RSS search.
        """

        query = str(
            query
        )

        # X language operator
        query = re.sub(
            r"\blang:[a-zA-Z-]+\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )

        # X negative operators
        query = re.sub(
            r"-is:[a-zA-Z_]+",
            " ",
            query,
            flags=re.IGNORECASE,
        )

        query = re.sub(
            r"-has:[a-zA-Z_]+",
            " ",
            query,
            flags=re.IGNORECASE,
        )

        # X from/to operators
        query = re.sub(
            r"\b(?:from|to):[A-Za-z0-9_]+\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )

        # Remove doubled spaces.
        query = re.sub(
            r"\s+",
            " ",
            query,
        )

        return query.strip()

    # ======================================================
    # BOOLEAN GROUP PARSING
    # ======================================================

    def _extract_parenthesized_groups(
        self,
        query: str,
    ) -> List[str]:
        """
        Extracts simple parenthesized boolean groups.
        """

        return [
            match.strip()
            for match in re.findall(
                r"\(([^()]+)\)",
                query,
            )
            if match.strip()
        ]

    def _split_or_terms(
        self,
        text: str,
    ) -> List[str]:
        """
        Splits a boolean OR group into normalized phrases.
        """

        raw_terms = re.split(
            r"\s+OR\s+",
            text,
            flags=re.IGNORECASE,
        )

        results = []

        for term in raw_terms:

            term = (
                term.strip()
                .strip('"')
                .strip("'")
                .strip()
            )

            term = re.sub(
                r"[()]",
                " ",
                term,
            )

            term = re.sub(
                r"\s+",
                " ",
                term,
            ).strip()

            if not term:
                continue

            if term.upper() in {
                "AND",
                "OR",
                "NOT",
            }:
                continue

            if term not in results:

                results.append(
                    term
                )

        return results

    # ======================================================
    # SEARCH URL
    # ======================================================

    def _build_search_url(
        self,
        query: str,
    ) -> str:
        """
        Builds a recent Reddit RSS search URL.
        """

        encoded_query = (
            quote_plus(
                query.strip()
            )
        )

        return (
            f"{self.BASE_URL}"
            f"{self.SEARCH_ENDPOINT}"
            f"?q={encoded_query}"
            f"&sort=new"
            f"&t={self.DEFAULT_RECENCY}"
        )

    # ======================================================
    # FEED PARSING
    # ======================================================

    def _parse_feed(
        self,
        url: str,
    ):
        """
        Parses one Reddit RSS feed.
        """

        feedparser.USER_AGENT = (
            self.USER_AGENT
        )

        return feedparser.parse(
            url,
            request_headers={
                "User-Agent":
                    self.USER_AGENT,

                "Accept":
                    (
                        "application/atom+xml,"
                        "application/rss+xml,"
                        "application/xml,"
                        "text/xml"
                    ),
            },
        )

    # ======================================================
    # SUBREDDIT MONITORING
    # ======================================================

    def fetch_subreddit(
        self,
        subreddit: str,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves the newest posts from one subreddit.

        This method is kept for later targeted subreddit
        monitoring.
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

        max_results = max(
            1,
            min(
                int(max_results),
                100,
            ),
        )

        url = (
            f"{self.BASE_URL}"
            f"/r/{subreddit}/new/.rss"
        )

        feed = (
            self._parse_feed(
                url
            )
        )

        entries = (
            getattr(
                feed,
                "entries",
                [],
            )
            or []
        )

        posts = []

        seen_ids = set()

        for entry in entries:

            normalized_post = (
                self._normalize_entry(
                    entry=entry,
                    subreddit_hint=subreddit,
                    search_query=None,
                )
            )

            if not normalized_post:
                continue

            post_id = (
                normalized_post.get(
                    "post_id"
                )
            )

            if not post_id:
                continue

            if post_id in seen_ids:
                continue

            seen_ids.add(
                post_id
            )

            posts.append(
                normalized_post
            )

            if len(posts) >= max_results:
                break

        return posts

    # ======================================================
    # ENTRY NORMALIZATION
    # ======================================================

    def _normalize_entry(
        self,
        *,
        entry,
        search_query: Optional[str],
        subreddit_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Converts one Reddit RSS entry into the normalized
        Migration OSINT post format.
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

        title = (
            self._clean_text(
                self._strip_html(
                    title
                )
            )
        )

        body = (
            self._clean_text(
                self._strip_html(
                    summary
                )
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

        reddit_id = (
            self._extract_reddit_id(
                entry=entry,
                link=link,
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

            "subreddit":
                subreddit,

            "title":
                title,

            "reddit_search_query":
                search_query,
        }

    # ======================================================
    # TEXT NORMALIZATION
    # ======================================================

    def _strip_html(
        self,
        text: str,
    ) -> str:
        """
        Removes HTML from Reddit RSS content.
        """

        if not text:
            return ""

        text = html.unescape(
            text
        )

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

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    def _clean_text(
        self,
        text: str,
    ) -> str:
        """
        Cleans common Reddit RSS formatting fragments.
        """

        if not text:
            return ""

        text = html.unescape(
            text
        )

        # Remove standard Reddit RSS footer fragments.
        text = re.sub(
            r"\s*submitted by\s*/?u/[^\s]+"
            r"\s*to\s*/?r/[^\s]+.*$",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s*\[link\]\s*",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s*\[comments\]\s*",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    def _combine_title_and_body(
        self,
        *,
        title: str,
        body: str,
    ) -> str:
        """
        Combines title and body while avoiding duplication.
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

    # ======================================================
    # AUTHOR
    # ======================================================

    def _extract_author(
        self,
        entry,
    ) -> Optional[str]:
        """
        Extracts Reddit username.
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
                r"^/?u/",
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

                author = (
                    author_detail.get(
                        "name"
                    )
                )

            except AttributeError:

                author = None

            if author:

                return str(
                    author
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
        Extracts subreddit name.
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

                term = (
                    tag.get(
                        "term"
                    )
                )

            except AttributeError:

                term = None

            if not term:
                continue

            match = re.search(
                r"(?:^|/)r/([^/\s]+)",
                str(term),
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
        Extracts Reddit submission ID.
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
                r"(?:t3_)?([a-z0-9]{5,15})$",
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
        Converts RSS publication time to UTC ISO-8601.
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

        raw_date = (
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

        if raw_date:

            return str(
                raw_date
            )

        return None


# ==========================================================
# MANUAL TEST
# ==========================================================

if __name__ == "__main__":

    collector = (
        RedditCollector()
    )

    test_queries = [
        (
            "(migration OR migrant OR migrants OR "
            "refugee OR refugees OR asylum)"
        ),
        (
            "(migrant OR migrants OR refugee OR refugees) "
            "(border OR crossing OR route OR checkpoint OR patrol)"
        ),
        (
            "(migrant OR migrants OR refugee OR refugees) "
            "(boat OR vessel OR sea OR coast guard OR rescue)"
        ),
        (
            "(migrant OR migrants OR migration) "
            "(smuggler OR smuggling OR trafficking OR transport)"
        ),
    ]

    print(
        "==================================="
    )

    print(
        "Reddit Collector Test"
    )

    print(
        "==================================="
    )

    for query in test_queries:

        print()

        print(
            "Query:"
        )

        print(
            query
        )

        expanded = (
            collector._expand_query(
                query
            )
        )

        print(
            "Expanded queries:"
        )

        for item in expanded:

            print(
                " -",
                item,
            )

        posts = (
            collector.search_recent(
                query=query,
                max_results=20,
                max_pages=1,
            )
        )

        print(
            "Posts collected:",
            len(posts),
        )

        for post in posts[:5]:

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
                "Subreddit:",
                post.get(
                    "subreddit"
                ),
            )

            print(
                "Search query:",
                post.get(
                    "reddit_search_query"
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
