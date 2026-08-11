"""
Migration OSINT Monitor

File:
collectors/telegram_collector.py

Description:
Read-only Telegram public-channel collector using an authorized Telethon
StringSession.

Normal mode:
- reuses the monitor's existing query groups
- performs Telegram global message search
- keeps only PUBLIC broadcast channels with usernames
- normalizes Telegram messages into the same post dictionary used by
  X / Reddit / Mastodon
- never writes to Telegram and never reads private chats/groups

Historical helper:
- search_between() supports bounded date-range retrieval
- used by analysis/telegram_backfill.py

Required environment variables:
- TELEGRAM_API_ID
- TELEGRAM_API_HASH
- TELEGRAM_SESSION
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.sync import TelegramClient


class TelegramCollector:
    """
    Collects public Telegram channel posts through an authorized user session.
    """

    MAX_SEARCH_TERMS = 8
    SEARCH_OVERSAMPLE_FACTOR = 5

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
    }

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
    )

    def __init__(
        self,
        *,
        api_id: Optional[str] = None,
        api_hash: Optional[str] = None,
        session_string: Optional[str] = None,
    ):
        self.api_id_raw = (
            str(
                api_id
                if api_id is not None
                else os.getenv(
                    "TELEGRAM_API_ID",
                    "",
                )
            )
            .strip()
        )

        self.api_hash = (
            str(
                api_hash
                if api_hash is not None
                else os.getenv(
                    "TELEGRAM_API_HASH",
                    "",
                )
            )
            .strip()
        )

        self.session_string = (
            str(
                session_string
                if session_string is not None
                else os.getenv(
                    "TELEGRAM_SESSION",
                    "",
                )
            )
            .strip()
        )

    def is_configured(
        self,
    ) -> bool:
        return bool(
            self.api_id_raw.isdigit()
            and self.api_hash
            and self.session_string
        )

    def search_recent(
        self,
        query: str,
        max_results: int = 10,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search recent public Telegram broadcast-channel posts.

        max_pages is accepted for collector compatibility. Telegram global
        search uses message iteration rather than X-style page tokens.
        """

        del max_pages

        return self._search(
            query=query,
            max_results=max_results,
            start_at=None,
            end_at=None,
        )

    def search_between(
        self,
        *,
        query: str,
        start_at: datetime,
        end_at: datetime,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Search one bounded UTC interval [start_at, end_at).
        """

        start_utc = self._ensure_utc(
            start_at
        )
        end_utc = self._ensure_utc(
            end_at
        )

        if end_utc <= start_utc:
            return []

        return self._search(
            query=query,
            max_results=max_results,
            start_at=start_utc,
            end_at=end_utc,
        )

    def _search(
        self,
        *,
        query: str,
        max_results: int,
        start_at: Optional[datetime],
        end_at: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []

        if not query or not str(query).strip():
            return []

        max_results = max(
            1,
            min(
                int(
                    max_results
                ),
                500,
            ),
        )

        search_terms = (
            self._expand_query(
                query
            )
        )

        if not search_terms:
            return []

        per_term_target = max(
            2,
            (
                max_results
                + len(search_terms)
                - 1
            )
            // len(search_terms),
        )

        posts: List[
            Dict[str, Any]
        ] = []

        seen_keys = set()

        client = TelegramClient(
            StringSession(
                self.session_string
            ),
            int(
                self.api_id_raw
            ),
            self.api_hash,
        )

        try:
            client.connect()

            if not client.is_user_authorized():
                raise RuntimeError(
                    "TELEGRAM_SESSION is not authorized."
                )

            for search_term in search_terms:
                if (
                    len(posts)
                    >= max_results
                ):
                    break

                remaining = (
                    max_results
                    - len(posts)
                )

                term_limit = min(
                    max(
                        per_term_target,
                        remaining,
                    )
                    * self.SEARCH_OVERSAMPLE_FACTOR,
                    200,
                )

                try:
                    iterator = client.iter_messages(
                        None,
                        search=search_term,
                        limit=term_limit,
                        offset_date=end_at,
                    )

                    accepted_for_term = 0

                    for message in iterator:
                        message_date = (
                            self._ensure_utc(
                                message.date
                            )
                            if message.date
                            else None
                        )

                        if (
                            start_at is not None
                            and message_date is not None
                            and message_date
                            < start_at
                        ):
                            break

                        if (
                            end_at is not None
                            and message_date is not None
                            and message_date
                            >= end_at
                        ):
                            continue

                        normalized = (
                            self._normalize_message(
                                message=message,
                                search_query=search_term,
                            )
                        )

                        if not normalized:
                            continue

                        post_key = (
                            normalized[
                                "post_id"
                            ]
                        )

                        if post_key in seen_keys:
                            continue

                        seen_keys.add(
                            post_key
                        )

                        posts.append(
                            normalized
                        )

                        accepted_for_term += 1

                        if (
                            len(posts)
                            >= max_results
                            or accepted_for_term
                            >= per_term_target
                        ):
                            break

                except FloodWaitError as error:
                    raise RuntimeError(
                        "Telegram flood wait: "
                        f"{error.seconds} seconds."
                    ) from error

        finally:
            client.disconnect()

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
        search_query: str,
    ) -> Optional[Dict[str, Any]]:
        text = (
            str(
                getattr(
                    message,
                    "message",
                    "",
                )
                or ""
            )
            .strip()
        )

        if not text:
            return None

        chat = getattr(
            message,
            "chat",
            None,
        )

        # Public broadcast channels only.
        if chat is None:
            return None

        if not bool(
            getattr(
                chat,
                "broadcast",
                False,
            )
        ):
            return None

        username = (
            str(
                getattr(
                    chat,
                    "username",
                    "",
                )
                or ""
            )
            .strip()
        )

        if not username:
            return None

        channel_id = str(
            getattr(
                chat,
                "id",
                "",
            )
            or ""
        )

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

        source_post_id = (
            f"{channel_id}:{message_id}"
            if channel_id
            else f"{username}:{message_id}"
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

        title = (
            str(
                getattr(
                    chat,
                    "title",
                    "",
                )
                or username
            )
            .strip()
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
                    chat,
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

    def _expand_query(
        self,
        query: str,
    ) -> List[str]:
        """
        Convert an X-style Boolean query into Telegram-friendly searches.

        Telegram server-side search does not interpret X operators such as
        "-is:retweet". We therefore extract quoted phrases and meaningful
        lexical terms, prioritizing operational multi-word phrases.
        """

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
            if (
                token in self.STOPWORDS
                or token in {
                    "lang",
                    "retweet",
                    "is",
                }
            ):
                continue

            self._append_unique(
                terms,
                token,
            )

        return terms[
            :self.MAX_SEARCH_TERMS
        ]

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
