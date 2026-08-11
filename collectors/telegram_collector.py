"""
Migration OSINT Monitor

File:
collectors/telegram_collector.py

Purpose:
Read-only Telegram OSINT collector for PUBLIC broadcast channels.

Why this version exists:
The first implementation relied on Telegram global message search. In practice,
that can return no results when the relevant public channels are not already
part of the account's normal dialog/search context.

This collector therefore uses a two-stage strategy:

1. DISCOVERY
   Search Telegram's public directory for public broadcast channels whose
   names/usernames match migration-related search terms.

2. COLLECTION
   Search recent messages INSIDE those discovered public broadcast channels.

The collector:
- uses the existing authorized TELEGRAM_SESSION
- reads PUBLIC broadcast channels only
- never accesses private chats or private groups
- never sends messages
- returns normalized post dictionaries compatible with the existing
  X / Reddit / Mastodon analysis pipeline

Environment variables:
- TELEGRAM_API_ID
- TELEGRAM_API_HASH
- TELEGRAM_SESSION

Optional:
- TELEGRAM_PUBLIC_CHANNELS
    Comma-separated public usernames to always include, for example:
    channel_a,channel_b,channel_c

- TELEGRAM_RECENT_HOURS
    Normal-run lookback window. Default: 72 hours.

- TELEGRAM_DISCOVERY_LIMIT
    Maximum public-directory results checked per discovery term.
    Default: 20.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from telethon import functions, types
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.sync import TelegramClient


class TelegramCollector:
    """
    Public Telegram broadcast-channel collector.
    """

    MAX_SEARCH_TERMS = 8
    MAX_DISCOVERY_TERMS = 6
    DEFAULT_RECENT_HOURS = 72
    DEFAULT_DISCOVERY_LIMIT = 20
    MAX_CHANNELS_PER_QUERY = 30
    MAX_MESSAGES_PER_CHANNEL_TERM = 12

    STOPWORDS = {
        "and",
        "or",
        "not",
        "the",
        "a",
        "an",
        "to",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "with",
        "without",
        "into",
        "onto",
        "near",
        "at",
        "in",
        "on",
        "of",
        "for",
        "by",
        "via",
        "lang",
        "retweet",
    }

    # These terms are useful for discovering likely migration-focused
    # public channels. Query-specific terms are still added dynamically.
    DISCOVERY_SEEDS = (
        "migration",
        "migrant",
        "refugee",
        "border",
        "asylum",
        "immigration",
    )

    # Multi-word terms are especially valuable once we are inside a
    # discovered channel and searching its posts.
    HIGH_VALUE_PHRASES = (
        "border crossing",
        "mass crossing",
        "crossing planned",
        "planned crossing",
        "crossing organized",
        "crossing organised",
        "migrant boat",
        "refugee boat",
        "smuggling route",
        "migrant route",
        "border closure",
        "border closed",
        "border open",
        "coast guard",
        "departure point",
        "meeting point",
        "gathering point",
        "crossing point",
    )

    def __init__(
        self,
        *,
        api_id: Optional[str] = None,
        api_hash: Optional[str] = None,
        session_string: Optional[str] = None,
    ):
        self.api_id_raw = str(
            api_id
            if api_id is not None
            else os.getenv(
                "TELEGRAM_API_ID",
                "",
            )
        ).strip()

        self.api_hash = str(
            api_hash
            if api_hash is not None
            else os.getenv(
                "TELEGRAM_API_HASH",
                "",
            )
        ).strip()

        self.session_string = str(
            session_string
            if session_string is not None
            else os.getenv(
                "TELEGRAM_SESSION",
                "",
            )
        ).strip()

        self.recent_hours = self._env_int(
            "TELEGRAM_RECENT_HOURS",
            self.DEFAULT_RECENT_HOURS,
            minimum=1,
            maximum=24 * 30,
        )

        self.discovery_limit = self._env_int(
            "TELEGRAM_DISCOVERY_LIMIT",
            self.DEFAULT_DISCOVERY_LIMIT,
            minimum=5,
            maximum=100,
        )

        self.explicit_channels = (
            self._load_explicit_channels()
        )

        # Per-process cache. main.py creates one TelegramCollector and
        # reuses it across all QueryEngine queries.
        self._channel_cache: Dict[
            str,
            Dict[str, Any]
        ] = {}

        self._discovery_term_cache: Dict[
            str,
            List[str]
        ] = {}

    # ======================================================
    # CONFIGURATION
    # ======================================================

    def is_configured(
        self,
    ) -> bool:
        return bool(
            self.api_id_raw.isdigit()
            and self.api_hash
            and self.session_string
        )

    # ======================================================
    # NORMAL RUN
    # ======================================================

    def search_recent(
        self,
        query: str,
        max_results: int = 10,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Discover relevant public channels and search recent posts within them.
        """

        del max_pages

        if not self.is_configured():
            print(
                "TELEGRAM COLLECTOR: not configured."
            )
            return []

        if not query or not str(query).strip():
            return []

        max_results = max(
            1,
            min(
                int(max_results),
                100,
            ),
        )

        search_terms = self._expand_query(
            query
        )

        discovery_terms = (
            self._build_discovery_terms(
                query=query,
                search_terms=search_terms,
            )
        )

        if not search_terms:
            print(
                "TELEGRAM COLLECTOR: no usable search terms."
            )
            return []

        cutoff = (
            datetime.now(
                timezone.utc
            )
            - timedelta(
                hours=self.recent_hours
            )
        )

        client = self._build_client()

        try:
            client.connect()

            if not client.is_user_authorized():
                raise RuntimeError(
                    "TELEGRAM_SESSION is not authorized."
                )

            channels = self._collect_candidate_channels(
                client=client,
                discovery_terms=discovery_terms,
            )

            if not channels:
                print(
                    "TELEGRAM COLLECTOR: "
                    "0 public broadcast channels discovered."
                )
                return []

            print(
                "Telegram public channels discovered: "
                f"{len(channels)}"
            )

            preview = [
                (
                    item.get("username")
                    or item.get("title")
                    or item.get("id")
                )
                for item in channels[:8]
            ]

            print(
                "Telegram channel preview: "
                f"{preview}"
            )

            posts = self._search_channels(
                client=client,
                channels=channels,
                search_terms=search_terms,
                cutoff=cutoff,
                max_results=max_results,
            )

            print(
                "Telegram recent public-channel matches: "
                f"{len(posts)}"
            )

            return posts

        finally:
            client.disconnect()

    # ======================================================
    # HISTORICAL / BACKFILL SUPPORT
    # ======================================================

    def search_between(
        self,
        *,
        query: str,
        start_at: datetime,
        end_at: datetime,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Same public-channel discovery logic, but with a bounded UTC interval.

        This is intentionally kept here so the later Telegram backfill can use
        the exact same source-discovery and normalization logic as normal runs.
        """

        if not self.is_configured():
            return []

        start_utc = self._ensure_utc(
            start_at
        )
        end_utc = self._ensure_utc(
            end_at
        )

        if end_utc <= start_utc:
            return []

        search_terms = self._expand_query(
            query
        )

        discovery_terms = (
            self._build_discovery_terms(
                query=query,
                search_terms=search_terms,
            )
        )

        client = self._build_client()

        try:
            client.connect()

            if not client.is_user_authorized():
                raise RuntimeError(
                    "TELEGRAM_SESSION is not authorized."
                )

            channels = self._collect_candidate_channels(
                client=client,
                discovery_terms=discovery_terms,
            )

            return self._search_channels(
                client=client,
                channels=channels,
                search_terms=search_terms,
                cutoff=start_utc,
                end_at=end_utc,
                max_results=max_results,
            )

        finally:
            client.disconnect()

    # ======================================================
    # PUBLIC CHANNEL DISCOVERY
    # ======================================================

    def _collect_candidate_channels(
        self,
        *,
        client: TelegramClient,
        discovery_terms: List[str],
    ) -> List[Dict[str, Any]]:
        channels_by_key: Dict[
            str,
            Dict[str, Any]
        ] = {}

        # 1. Explicit public channels configured by us.
        for username in self.explicit_channels:
            channel = self._resolve_public_channel(
                client=client,
                username=username,
            )

            if channel:
                channels_by_key[
                    channel["key"]
                ] = channel

        # 2. Telegram public directory discovery.
        for term in discovery_terms:
            discovered_keys = (
                self._discovery_term_cache.get(
                    term
                )
            )

            if discovered_keys is None:
                discovered_keys = []

                try:
                    result = client(
                        functions.contacts.SearchRequest(
                            q=term,
                            limit=self.discovery_limit,
                        )
                    )

                    for chat in (
                        getattr(
                            result,
                            "chats",
                            [],
                        )
                        or []
                    ):
                        channel = (
                            self._channel_from_entity(
                                chat
                            )
                        )

                        if not channel:
                            continue

                        key = channel[
                            "key"
                        ]

                        self._channel_cache[
                            key
                        ] = channel

                        if key not in discovered_keys:
                            discovered_keys.append(
                                key
                            )

                except FloodWaitError as error:
                    raise RuntimeError(
                        "Telegram public-directory flood wait: "
                        f"{error.seconds} seconds."
                    ) from error

                self._discovery_term_cache[
                    term
                ] = discovered_keys

            for key in discovered_keys:
                channel = (
                    self._channel_cache.get(
                        key
                    )
                )

                if channel:
                    channels_by_key[
                        key
                    ] = channel

                if (
                    len(channels_by_key)
                    >= self.MAX_CHANNELS_PER_QUERY
                ):
                    break

            if (
                len(channels_by_key)
                >= self.MAX_CHANNELS_PER_QUERY
            ):
                break

        values = list(
            channels_by_key.values()
        )

        values.sort(
            key=lambda item: (
                str(
                    item.get(
                        "username",
                        ""
                    )
                ).lower(),
                str(
                    item.get(
                        "title",
                        ""
                    )
                ).lower(),
            )
        )

        return values[
            :self.MAX_CHANNELS_PER_QUERY
        ]

    def _resolve_public_channel(
        self,
        *,
        client: TelegramClient,
        username: str,
    ) -> Optional[Dict[str, Any]]:
        cleaned = (
            str(
                username
                or ""
            )
            .strip()
            .lstrip("@")
        )

        if not cleaned:
            return None

        cache_key = (
            "username:"
            + cleaned.lower()
        )

        if cache_key in self._channel_cache:
            return self._channel_cache[
                cache_key
            ]

        try:
            entity = client.get_entity(
                cleaned
            )
        except Exception:
            return None

        channel = self._channel_from_entity(
            entity
        )

        if channel:
            self._channel_cache[
                cache_key
            ] = channel

            self._channel_cache[
                channel["key"]
            ] = channel

        return channel

    def _channel_from_entity(
        self,
        entity,
    ) -> Optional[Dict[str, Any]]:
        """
        Accept PUBLIC broadcast channels only.
        """

        if not isinstance(
            entity,
            types.Channel,
        ):
            return None

        if not bool(
            getattr(
                entity,
                "broadcast",
                False,
            )
        ):
            return None

        username = str(
            getattr(
                entity,
                "username",
                "",
            )
            or ""
        ).strip()

        # No username = not a public channel URL we can audit.
        if not username:
            return None

        channel_id = str(
            getattr(
                entity,
                "id",
                "",
            )
            or ""
        )

        title = str(
            getattr(
                entity,
                "title",
                "",
            )
            or username
        ).strip()

        key = (
            f"{channel_id}:"
            f"{username.lower()}"
        )

        return {
            "key":
                key,
            "id":
                channel_id,
            "username":
                username,
            "title":
                title,
            "entity":
                entity,
        }

    # ======================================================
    # MESSAGE COLLECTION
    # ======================================================

    def _search_channels(
        self,
        *,
        client: TelegramClient,
        channels: List[Dict[str, Any]],
        search_terms: List[str],
        cutoff: datetime,
        max_results: int,
        end_at: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        posts: List[
            Dict[str, Any]
        ] = []

        seen_ids = set()

        # Fair-share budget prevents one very active channel from consuming
        # every available result.
        per_channel_budget = max(
            1,
            (
                max_results
                + max(
                    len(channels),
                    1,
                )
                - 1
            )
            // max(
                len(channels),
                1,
            ),
        )

        for channel in channels:
            if len(posts) >= max_results:
                break

            accepted_from_channel = 0

            entity = channel[
                "entity"
            ]

            for term in search_terms:
                if len(posts) >= max_results:
                    break

                if (
                    accepted_from_channel
                    >= per_channel_budget
                ):
                    break

                try:
                    iterator = client.iter_messages(
                        entity,
                        search=term,
                        limit=self.MAX_MESSAGES_PER_CHANNEL_TERM,
                        offset_date=end_at,
                    )

                    for message in iterator:
                        message_date = (
                            self._ensure_utc(
                                message.date
                            )
                            if getattr(
                                message,
                                "date",
                                None,
                            )
                            else None
                        )

                        if (
                            message_date is not None
                            and message_date < cutoff
                        ):
                            # Telegram returns newest first within a channel.
                            break

                        if (
                            end_at is not None
                            and message_date is not None
                            and message_date >= end_at
                        ):
                            continue

                        normalized = (
                            self._normalize_message(
                                message=message,
                                channel=channel,
                                search_query=term,
                            )
                        )

                        if not normalized:
                            continue

                        post_id = normalized[
                            "post_id"
                        ]

                        if post_id in seen_ids:
                            continue

                        seen_ids.add(
                            post_id
                        )

                        posts.append(
                            normalized
                        )

                        accepted_from_channel += 1

                        if (
                            len(posts)
                            >= max_results
                            or accepted_from_channel
                            >= per_channel_budget
                        ):
                            break

                except FloodWaitError as error:
                    raise RuntimeError(
                        "Telegram message-search flood wait: "
                        f"{error.seconds} seconds."
                    ) from error

                except Exception as error:
                    # One inaccessible/deleted/restricted public channel
                    # must not break the complete monitor run.
                    print(
                        "TELEGRAM CHANNEL WARNING: "
                        f"@{channel.get('username')} | "
                        f"{type(error).__name__}: {error}"
                    )

        posts.sort(
            key=lambda item: (
                item.get(
                    "published_at"
                )
                or ""
            ),
            reverse=True,
        )

        return posts[
            :max_results
        ]

    def _normalize_message(
        self,
        *,
        message,
        channel: Dict[str, Any],
        search_query: str,
    ) -> Optional[Dict[str, Any]]:
        text = str(
            getattr(
                message,
                "message",
                "",
            )
            or ""
        ).strip()

        if not text:
            return None

        message_id = str(
            getattr(
                message,
                "id",
                "",
            )
            or ""
        )

        if not message_id:
            return None

        username = str(
            channel.get(
                "username"
            )
            or ""
        ).strip()

        channel_id = str(
            channel.get(
                "id"
            )
            or ""
        ).strip()

        title = str(
            channel.get(
                "title"
            )
            or username
        ).strip()

        source_post_id = (
            f"{channel_id}:"
            f"{message_id}"
        )

        published_at = None

        if getattr(
            message,
            "date",
            None,
        ):
            published_at = (
                self._ensure_utc(
                    message.date
                )
                .isoformat(
                    timespec="seconds"
                )
                .replace(
                    "+00:00",
                    "Z",
                )
            )

        url = (
            f"https://t.me/"
            f"{username}/"
            f"{message_id}"
        )

        return {
            "source":
                "TELEGRAM",
            "post_id":
                source_post_id,
            "author_id":
                channel_id
                or username,
            "author":
                username,
            "author_name":
                title,
            "author_location":
                None,
            "author_verified":
                getattr(
                    channel.get(
                        "entity"
                    ),
                    "verified",
                    None,
                ),
            "text":
                text,
            "language":
                None,
            "published_at":
                published_at,
            "conversation_id":
                source_post_id,
            "public_metrics":
                {
                    "views":
                        getattr(
                            message,
                            "views",
                            None,
                        ),
                    "forwards":
                        getattr(
                            message,
                            "forwards",
                            None,
                        ),
                },
            "url":
                url,
            "telegram_channel_id":
                channel_id
                or None,
            "telegram_channel":
                username,
            "telegram_channel_title":
                title,
            "telegram_search_query":
                search_query,
        }

    # ======================================================
    # QUERY CONVERSION
    # ======================================================

    def _expand_query(
        self,
        query: str,
    ) -> List[str]:
        value = str(
            query
            or ""
        )

        value = re.sub(
            r"(?<!\S)-?[a-z_]+:[^\s()]+",
            " ",
            value,
            flags=re.IGNORECASE,
        )

        quoted = [
            item.strip()
            for item in re.findall(
                r'"([^"]+)"',
                value,
            )
            if item.strip()
        ]

        plain = re.sub(
            r'"[^"]+"',
            " ",
            value,
        )

        tokens = [
            token.lower()
            for token in re.findall(
                r"[\wÀ-ÿ\u0600-\u06ff'-]{3,}",
                plain,
                flags=re.UNICODE,
            )
        ]

        terms: List[str] = []

        lower_value = (
            value.lower()
        )

        for phrase in self.HIGH_VALUE_PHRASES:
            if phrase in lower_value:
                self._append_unique(
                    terms,
                    phrase,
                )

        for phrase in quoted:
            self._append_unique(
                terms,
                phrase,
            )

        for token in tokens:
            if token in self.STOPWORDS:
                continue

            self._append_unique(
                terms,
                token,
            )

        return terms[
            :self.MAX_SEARCH_TERMS
        ]

    def _build_discovery_terms(
        self,
        *,
        query: str,
        search_terms: List[str],
    ) -> List[str]:
        """
        Build channel-directory search terms.

        We prefer core migration concepts and named locations from the current
        query. We intentionally do NOT search every operational verb because
        that would discover huge numbers of irrelevant Telegram channels.
        """

        query_lower = str(
            query
            or ""
        ).lower()

        result: List[str] = []

        for seed in self.DISCOVERY_SEEDS:
            if (
                seed in query_lower
                or seed in search_terms
            ):
                self._append_unique(
                    result,
                    seed,
                )

        # Add useful query-specific non-generic terms such as "ceuta",
        # "melilla", "morocco", "channel", etc.
        generic_terms = set(
            self.DISCOVERY_SEEDS
        ) | {
            "border",
            "crossing",
            "route",
            "checkpoint",
            "patrol",
            "boat",
            "vessel",
            "sea",
            "coast",
            "guard",
            "rescue",
            "intercepted",
            "departure",
            "departing",
            "leaving",
            "arrived",
            "arrival",
            "migrants",
            "refugees",
        }

        for term in search_terms:
            cleaned = term.lower().strip()

            if (
                not cleaned
                or cleaned in generic_terms
                or " " in cleaned
            ):
                continue

            self._append_unique(
                result,
                cleaned,
            )

        # Guarantee at least the two strongest generic discovery seeds.
        if not result:
            result = [
                "migration",
                "migrant",
            ]

        return result[
            :self.MAX_DISCOVERY_TERMS
        ]

    # ======================================================
    # HELPERS
    # ======================================================

    def _build_client(
        self,
    ) -> TelegramClient:
        return TelegramClient(
            StringSession(
                self.session_string
            ),
            int(
                self.api_id_raw
            ),
            self.api_hash,
        )

    def _load_explicit_channels(
        self,
    ) -> List[str]:
        raw = str(
            os.getenv(
                "TELEGRAM_PUBLIC_CHANNELS",
                "",
            )
            or ""
        )

        result = []

        for item in raw.split(","):
            cleaned = (
                item.strip()
                .lstrip("@")
            )

            if (
                cleaned
                and cleaned not in result
            ):
                result.append(
                    cleaned
                )

        return result

    @staticmethod
    def _append_unique(
        values: List[str],
        value: str,
    ) -> None:
        cleaned = re.sub(
            r"\s+",
            " ",
            str(
                value
                or ""
            ),
        ).strip()

        if (
            cleaned
            and cleaned not in values
        ):
            values.append(
                cleaned
            )

    @staticmethod
    def _ensure_utc(
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

    @staticmethod
    def _env_int(
        name: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        raw = str(
            os.getenv(
                name,
                str(default),
            )
            or str(default)
        ).strip()

        try:
            value = int(
                raw
            )
        except ValueError:
            value = default

        return max(
            minimum,
            min(
                value,
                maximum,
            ),
        )
