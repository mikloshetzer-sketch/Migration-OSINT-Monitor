"""
Migration OSINT Monitor

File:
mastodon_collector.py

Description:
Mastodon RSS/Atom collector for recent migration-related posts.

This collector uses public Mastodon hashtag RSS feeds and does not
require OAuth credentials.

The collector is designed for the Migration OSINT Monitor and returns
normalized post dictionaries compatible with the same analysis
pipeline used for X and Reddit posts.

Key design:

1. Accept one migration-related logical query.
2. Convert the query into Mastodon-friendly hashtag candidates.
3. Read those hashtag feeds from several configurable Mastodon
   instances.
4. Merge and deduplicate the results.
5. Return normalized Mastodon posts.

Important:
Mastodon is federated. One instance does not represent the whole
network. Using several public instances improves coverage, while the
downstream analytical pipeline remains responsible for relevance,
noise filtering and event/influence classification.
"""

import hashlib
import html
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import feedparser
from dateutil import parser as date_parser


class MastodonCollector:
    """
    Collects recent Mastodon posts using public hashtag RSS feeds.
    """

    USER_AGENT = (
        "MigrationOSINTMonitor/1.0 "
        "(public Mastodon RSS OSINT research collector)"
    )

    # Public instances used when MASTODON_INSTANCES is not configured.
    # This is deliberately small. Coverage can be expanded later without
    # changing collector logic.
    DEFAULT_INSTANCES = [
        "mastodon.social",
        "mstdn.social",
    ]

    # Maximum number of hashtags generated from one logical query.
    MAX_HASHTAGS = 18

    # Maximum entries accepted from one individual hashtag/instance feed.
    PER_FEED_RESULT_LIMIT = 10

    # Live early-warning window. Public hashtag feeds can contain old posts.
    DEFAULT_MAX_POST_AGE_HOURS = 72

    # Terms that strongly indicate human migration and also work reasonably
    # well as Mastodon hashtags.
    MIGRATION_HASHTAGS = [
        "migration",
        "migrant",
        "migrants",
        "refugee",
        "refugees",
        "asylum",
        "immigration",
        "immigrant",
        "immigrants",
    ]

    # Operational-topic terms that may occur in the monitor's logical queries.
    TOPIC_HASHTAGS = [
        "border",
        "crossing",
        "route",
        "checkpoint",
        "patrol",
        "boat",
        "vessel",
        "sea",
        "rescue",
        "smuggling",
        "smuggler",
        "trafficking",
        "transport",
        "arrival",
        "departures",
        "deportation",
        "deportations",
    ]

    # A small multilingual layer for global monitoring.
    MULTILINGUAL_HASHTAGS = [
        "migración",
        "migracion",
        "migrantes",
        "refugiados",
        "réfugiés",
        "migranti",
        "immigrazione",
        "asilo",
    ]

    def __init__(
        self,
        instances: Optional[List[str]] = None,
    ):
        """
        Initializes the public RSS collector.

        Instances may be supplied directly or through the optional
        MASTODON_INSTANCES environment variable as a comma-separated list.
        No secret is required.
        """

        feedparser.USER_AGENT = self.USER_AGENT

        configured_instances = (
            instances
            or self._instances_from_environment()
            or self.DEFAULT_INSTANCES
        )

        self.instances = self._normalize_instances(
            configured_instances
        )

        if not self.instances:
            self.instances = list(
                self.DEFAULT_INSTANCES
            )

        self.max_post_age_hours = (
            self._max_post_age_from_environment()
        )

    # ======================================================
    # CONFIGURATION
    # ======================================================

    def is_configured(self) -> bool:
        """
        Public Mastodon RSS feeds do not require OAuth credentials.
        """
        return bool(
            self.instances
        )

    def _max_post_age_from_environment(
        self,
    ) -> int:
        """
        Optional env:
            MASTODON_MAX_POST_AGE_HOURS

        Default:
            72
        """
        raw = os.getenv(
            "MASTODON_MAX_POST_AGE_HOURS",
            "",
        ).strip()

        if not raw:
            return self.DEFAULT_MAX_POST_AGE_HOURS

        try:
            value = int(raw)
        except (TypeError, ValueError):
            return self.DEFAULT_MAX_POST_AGE_HOURS

        return max(
            1,
            min(
                value,
                24 * 30,
            ),
        )

    def _instances_from_environment(
        self,
    ) -> List[str]:
        """
        Reads optional comma-separated MASTODON_INSTANCES.

        Example:
            MASTODON_INSTANCES=mastodon.social,mstdn.social
        """

        raw = os.getenv(
            "MASTODON_INSTANCES",
            "",
        ).strip()

        if not raw:
            return []

        return [
            item.strip()
            for item in raw.split(",")
            if item.strip()
        ]

    def _normalize_instances(
        self,
        instances: List[str],
    ) -> List[str]:
        """
        Normalizes instance hostnames and removes duplicates.
        """

        normalized: List[str] = []

        for instance in instances:

            value = str(
                instance
            ).strip()

            if not value:
                continue

            value = re.sub(
                r"^https?://",
                "",
                value,
                flags=re.IGNORECASE,
            )

            value = value.strip(
                "/"
            )

            if not value:
                continue

            if value not in normalized:
                normalized.append(
                    value
                )

        return normalized

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
        Searches recent Mastodon posts through public hashtag RSS feeds.

        The method keeps the same signature as XCollector and RedditCollector
        so main.py can treat all collectors consistently.

        Args:
            query:
                Migration-related logical search query.

            max_results:
                Maximum number of unique normalized Mastodon posts returned.

            max_pages:
                Accepted for interface compatibility. RSS feeds do not use
                X-style pagination.

        Returns:
            List of normalized Mastodon post dictionaries.
        """

        if not query or not query.strip():
            raise ValueError(
                "Mastodon search query cannot be empty."
            )

        max_results = max(
            1,
            min(
                int(max_results),
                100,
            ),
        )

        hashtags = self._expand_query_to_hashtags(
            query
        )

        if not hashtags:
            return []

        feed_buckets: Dict[
            Tuple[str, str],
            List[Dict[str, Any]],
        ] = {}

        for instance in self.instances:

            for hashtag in hashtags:

                rss_url = self._build_hashtag_url(
                    instance=instance,
                    hashtag=hashtag,
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

                    normalized_post = (
                        self._normalize_entry(
                            entry=entry,
                            instance=instance,
                            hashtag=hashtag,
                            search_query=query,
                        )
                    )

                    if not normalized_post:
                        continue

                    if not self._is_recent_post(
                        normalized_post
                    ):
                        continue

                    post_id = (
                        normalized_post.get(
                            "post_id"
                        )
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
                        >= self.PER_FEED_RESULT_LIMIT
                    ):
                        break

                feed_buckets[
                    (
                        instance,
                        hashtag,
                    )
                ] = bucket

        # --------------------------------------------------
        # ROUND-ROBIN MERGE
        # --------------------------------------------------
        #
        # A productive hashtag on one server must not consume
        # the whole result budget.
        # --------------------------------------------------

        merged_posts: List[
            Dict[str, Any]
        ] = []

        seen_ids = set()

        max_bucket_size = max(
            (
                len(bucket)
                for bucket
                in feed_buckets.values()
            ),
            default=0,
        )

        ordered_keys = [
            (
                instance,
                hashtag,
            )
            for hashtag in hashtags
            for instance in self.instances
        ]

        for position in range(
            max_bucket_size
        ):

            for key in ordered_keys:

                bucket = feed_buckets.get(
                    key,
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
    # FRESHNESS
    # ======================================================

    def _is_recent_post(
        self,
        post: Dict[str, Any],
    ) -> bool:
        """
        Rejects timestamped Mastodon posts older than the configured
        live-monitoring window.

        Missing/unparseable timestamps are retained conservatively.
        """

        published_at = post.get(
            "published_at"
        )

        if not published_at:
            return True

        try:
            published = date_parser.parse(
                str(published_at)
            )
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            return True

        if published.tzinfo is None:
            published = published.replace(
                tzinfo=timezone.utc
            )
        else:
            published = published.astimezone(
                timezone.utc
            )

        now = datetime.now(
            timezone.utc
        )

        if published > (
            now
            + timedelta(
                minutes=10
            )
        ):
            return True

        cutoff = (
            now
            - timedelta(
                hours=self.max_post_age_hours
            )
        )

        return published >= cutoff

    # ======================================================
    # QUERY -> HASHTAGS
    # ======================================================

    def _expand_query_to_hashtags(
        self,
        query: str,
    ) -> List[str]:
        """
        Converts an X-style logical query into a compact Mastodon hashtag set.

        Mastodon RSS does not provide Reddit-style free-text search feeds,
        so topic coverage is achieved by monitoring relevant hashtags.
        """

        cleaned = self._clean_query(
            query
        )

        if not cleaned:
            return []

        terms = self._extract_terms(
            cleaned
        )

        results: List[str] = []

        # Prefer exact terms appearing in the logical query.
        for term in terms:

            candidate = self._term_to_hashtag(
                term
            )

            if not candidate:
                continue

            if (
                candidate.lower()
                in self._known_hashtag_set()
            ):
                self._append_unique(
                    results,
                    candidate,
                )

            if len(results) >= self.MAX_HASHTAGS:
                return results

        # Ensure basic migration coverage.
        for hashtag in self.MIGRATION_HASHTAGS:

            self._append_unique(
                results,
                hashtag,
            )

            if len(results) >= self.MAX_HASHTAGS:
                return results

        # If the logical query contains a second operational concept,
        # include matching topic hashtags.
        lower_query = cleaned.lower()

        for hashtag in self.TOPIC_HASHTAGS:

            if (
                re.search(
                    rf"\b{re.escape(hashtag)}\b",
                    lower_query,
                    flags=re.IGNORECASE,
                )
            ):
                self._append_unique(
                    results,
                    hashtag,
                )

            if len(results) >= self.MAX_HASHTAGS:
                return results

        # Small multilingual fallback only for broad migration queries.
        if self._looks_like_general_migration_query(
            lower_query
        ):

            for hashtag in self.MULTILINGUAL_HASHTAGS:

                self._append_unique(
                    results,
                    hashtag,
                )

                if len(results) >= self.MAX_HASHTAGS:
                    break

        return results[
            :self.MAX_HASHTAGS
        ]

    def _known_hashtag_set(
        self,
    ) -> set:
        """
        Returns all currently recognized hashtag candidates.
        """

        return {
            item.lower()
            for item in (
                self.MIGRATION_HASHTAGS
                + self.TOPIC_HASHTAGS
                + self.MULTILINGUAL_HASHTAGS
            )
        }

    def _clean_query(
        self,
        query: str,
    ) -> str:
        """
        Removes X-specific operators from a logical search string.
        """

        value = str(
            query
        )

        value = re.sub(
            r"\blang:[a-zA-Z-]+\b",
            " ",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"-is:[a-zA-Z_]+",
            " ",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"-has:[a-zA-Z_]+",
            " ",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"\b(?:from|to):[A-Za-z0-9_]+\b",
            " ",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

    def _extract_terms(
        self,
        query: str,
    ) -> List[str]:
        """
        Extracts simple words/phrases from OR-style logical queries.
        """

        value = re.sub(
            r"[()]",
            " ",
            query,
        )

        parts = re.split(
            r"\s+(?:OR|AND|NOT)\s+",
            value,
            flags=re.IGNORECASE,
        )

        results: List[str] = []

        for part in parts:

            part = (
                part.strip()
                .strip('"')
                .strip("'")
                .strip()
            )

            if not part:
                continue

            # Multi-word terms are collapsed later by _term_to_hashtag.
            if part not in results:
                results.append(
                    part
                )

        return results

    def _term_to_hashtag(
        self,
        term: str,
    ) -> Optional[str]:
        """
        Converts a simple term into a hashtag-safe token.
        """

        if not term:
            return None

        value = html.unescape(
            str(term)
        )

        value = re.sub(
            r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ_]+",
            "",
            value,
        )

        value = value.strip(
            "_"
        )

        if not value:
            return None

        if value.isdigit():
            return None

        return value.lower()

    def _append_unique(
        self,
        results: List[str],
        value: str,
    ) -> None:
        """
        Adds a normalized hashtag only once.
        """

        normalized = self._term_to_hashtag(
            value
        )

        if not normalized:
            return

        if normalized not in results:
            results.append(
                normalized
            )

    def _looks_like_general_migration_query(
        self,
        query: str,
    ) -> bool:
        """
        Detects broad migration-monitoring queries.
        """

        hits = sum(
            1
            for term
            in self.MIGRATION_HASHTAGS
            if re.search(
                rf"\b{re.escape(term)}\b",
                query,
                flags=re.IGNORECASE,
            )
        )

        return hits >= 2

    # ======================================================
    # FEED URL / PARSING
    # ======================================================

    def _build_hashtag_url(
        self,
        *,
        instance: str,
        hashtag: str,
    ) -> str:
        """
        Builds a Mastodon hashtag RSS URL.

        Standard Mastodon web hashtag timelines expose RSS by adding
        .rss to /tags/<hashtag>.
        """

        safe_hashtag = quote(
            hashtag.strip().lstrip("#"),
            safe="",
        )

        return (
            f"https://{instance}"
            f"/tags/{safe_hashtag}.rss"
        )

    def _parse_feed(
        self,
        url: str,
    ):
        """
        Parses one Mastodon RSS/Atom feed.
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
    # ENTRY NORMALIZATION
    # ======================================================

    def _normalize_entry(
        self,
        *,
        entry,
        instance: str,
        hashtag: str,
        search_query: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Converts one Mastodon feed entry into the monitor's normalized
        post dictionary format.
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
            or getattr(
                entry,
                "content",
                "",
            )
            or ""
        )

        if isinstance(
            summary,
            list,
        ):
            summary = " ".join(
                str(
                    item.get(
                        "value",
                        "",
                    )
                    if isinstance(
                        item,
                        dict,
                    )
                    else item
                )
                for item in summary
            )

        title = self._clean_text(
            self._strip_html(
                str(title)
            )
        )

        body = self._clean_text(
            self._strip_html(
                str(summary)
            )
        )

        text = self._combine_title_and_body(
            title=title,
            body=body,
        )

        if not text:
            return None

        author = self._extract_author(
            entry
        )

        published_at = (
            self._extract_published_at(
                entry
            )
        )

        post_id = (
            self._extract_status_id(
                entry=entry,
                link=link,
            )
            or self._generate_post_id(
                link=link,
                text=text,
                published_at=published_at,
            )
        )

        language = self._extract_language(
            entry
        )

        return {
            "source":
                "MASTODON",

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
                language,

            "published_at":
                published_at,

            "conversation_id":
                post_id,

            "public_metrics":
                {},

            "url":
                link or None,

            "mastodon_instance":
                instance,

            "mastodon_hashtag":
                hashtag,

            "mastodon_search_query":
                search_query,
        }

    # ======================================================
    # TEXT
    # ======================================================

    def _strip_html(
        self,
        text: str,
    ) -> str:
        """
        Removes HTML from Mastodon feed content.
        """

        if not text:
            return ""

        value = html.unescape(
            text
        )

        value = re.sub(
            r"<br\s*/?>",
            "\n",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"</p\s*>",
            "\n",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"<[^>]+>",
            " ",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

    def _clean_text(
        self,
        text: str,
    ) -> str:
        """
        Cleans common feed formatting fragments.
        """

        if not text:
            return ""

        value = html.unescape(
            text
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

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

        if (
            body.lower()
            in title.lower()
        ):
            return title

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
        Extracts a Mastodon account label from feed metadata.
        """

        author = (
            getattr(
                entry,
                "author",
                None,
            )
        )

        if author:
            value = str(
                author
            ).strip()

            if value:
                return value

        author_detail = (
            getattr(
                entry,
                "author_detail",
                None,
            )
        )

        if author_detail:

            try:
                value = (
                    author_detail.get(
                        "name"
                    )
                    or author_detail.get(
                        "email"
                    )
                )
            except AttributeError:
                value = None

            if value:
                return str(
                    value
                ).strip()

        return None

    # ======================================================
    # POST ID
    # ======================================================

    def _extract_status_id(
        self,
        *,
        entry,
        link: str,
    ) -> Optional[str]:
        """
        Extracts a deterministic Mastodon status identifier when possible.
        """

        entry_id = (
            getattr(
                entry,
                "id",
                None,
            )
        )

        if entry_id:
            raw = str(
                entry_id
            ).strip()

            match = re.search(
                r"(?:/@[^/]+/|/users/[^/]+/statuses/)([0-9]+)",
                raw,
                flags=re.IGNORECASE,
            )

            if match:
                return (
                    "mastodon_"
                    + match.group(
                        1
                    )
                )

        if link:

            match = re.search(
                r"(?:/@[^/]+/|/users/[^/]+/statuses/)([0-9]+)",
                link,
                flags=re.IGNORECASE,
            )

            if match:
                return (
                    "mastodon_"
                    + match.group(
                        1
                    )
                )

        return None

    def _generate_post_id(
        self,
        *,
        link: str,
        text: str,
        published_at: Optional[str],
    ) -> str:
        """
        Generates deterministic fallback ID.
        """

        seed = (
            f"{link}|"
            f"{text}|"
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
            f"mastodon_{digest}"
        )

    # ======================================================
    # LANGUAGE
    # ======================================================

    def _extract_language(
        self,
        entry,
    ) -> Optional[str]:
        """
        Extracts language metadata when the feed provides it.
        """

        for field in (
            "language",
            "lang",
        ):

            value = getattr(
                entry,
                field,
                None,
            )

            if value:
                return str(
                    value
                ).strip()

        return None

    # ======================================================
    # PUBLICATION TIME
    # ======================================================

    def _extract_published_at(
        self,
        entry,
    ) -> Optional[str]:
        """
        Converts feed publication time to UTC ISO-8601.
        """

        for parsed_field in (
            "published_parsed",
            "updated_parsed",
        ):

            parsed = getattr(
                entry,
                parsed_field,
                None,
            )

            if not parsed:
                continue

            try:
                dt = datetime(
                    *parsed[:6],
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
        MastodonCollector()
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
            "(boat OR vessel OR sea OR rescue)"
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
        "Mastodon Collector Test"
    )

    print(
        "==================================="
    )

    print(
        "Instances:",
        collector.instances,
    )

    for query in test_queries:

        print()

        print(
            "Query:"
        )

        print(
            query
        )

        hashtags = (
            collector._expand_query_to_hashtags(
                query
            )
        )

        print(
            "Hashtags:"
        )

        for item in hashtags:

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
                "Instance:",
                post.get(
                    "mastodon_instance"
                ),
            )

            print(
                "Hashtag:",
                post.get(
                    "mastodon_hashtag"
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
