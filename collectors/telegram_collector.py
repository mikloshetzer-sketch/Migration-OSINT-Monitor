"""
Migration OSINT Monitor

File:
collectors/telegram_collector.py

Version:
v5 - footer-cleaned post validation + Western Mediterranean discovery

Purpose:
Read-only Telegram OSINT collector for PUBLIC broadcast channels.

Main improvements over v2:
1. Public channels are no longer accepted only because their title/username
   contains words such as "asylum" or "migrant".
2. Every newly discovered public channel is sampled and content-scored.
3. Only channels with genuine migration-related recent content are searched.
4. False-positive title matches such as entertainment venues using "Asylum"
   are rejected before their posts enter the analytical pipeline.
5. Discovery is multilingual and includes Western Mediterranean / Ceuta /
   Melilla / Morocco-relevant terms.
6. Channel validation results are cached for the complete monitor process.

Safety:
- PUBLIC broadcast channels only
- no private chats
- no private groups
- no message sending
- no Telegram-side writes

Required environment variables:
- TELEGRAM_API_ID
- TELEGRAM_API_HASH
- TELEGRAM_SESSION

Optional environment variables:
- TELEGRAM_PUBLIC_CHANNELS
    Comma-separated public usernames that should always be checked.
    Explicit channels are still content-validated.

- TELEGRAM_RECENT_HOURS
    Normal run lookback. Default: 72.

- TELEGRAM_DISCOVERY_LIMIT
    Directory search limit per term. Default: 20.

- TELEGRAM_CHANNEL_SAMPLE_SIZE
    Number of recent channel posts used for source validation. Default: 20.

- TELEGRAM_MIN_CHANNEL_SCORE
    Minimum source-validation score. Default: 3.
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from telethon import functions, types
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.sync import TelegramClient


class TelegramCollector:
    """
    Content-validated public Telegram broadcast-channel collector.
    """

    MAX_SEARCH_TERMS = 8
    MAX_DISCOVERY_TERMS = 24
    DEFAULT_RECENT_HOURS = 72
    DEFAULT_DISCOVERY_LIMIT = 20
    DEFAULT_CHANNEL_SAMPLE_SIZE = 20
    DEFAULT_MIN_CHANNEL_SCORE = 3
    MAX_CHANNELS_PER_QUERY = 30
    MAX_VALIDATED_CHANNELS_PER_QUERY = 30
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

    # Directory discovery terms. These are intentionally broader than the
    # downstream migration content validator.
    DISCOVERY_SEEDS = (
        "migration",
        "migrant",
        "refugee",
        "immigration",
        "migracion",
        "migración",
        "migrantes",
        "refugiados",
        "migration maroc",
        "migration morocco",
        "ceuta",
        "melilla",
        "sebta",
        "marruecos",
        "maroc",
        "morocco",
        "الهجرة",
        "مهاجر",
        "مهاجرين",
        "سبتة",
        "المغرب",
    )

    # Strong location / route terms. A hit here materially increases the
    # probability that the channel is useful for the monitor.
    ROUTE_TERMS = (
        "ceuta",
        "sebta",
        "سبتة",
        "melilla",
        "morocco",
        "maroc",
        "marruecos",
        "المغرب",
        "fnideq",
        "castillejos",
        "tetouan",
        "tétouan",
        "tanger",
        "tangier",
        "strait of gibraltar",
        "estrecho de gibraltar",
        "western mediterranean",
        "mediterráneo occidental",
        "canary islands",
        "canarias",
        "lampedusa",
        "libya",
        "tunisia",
        "calais",
        "english channel",
        "la manche",
        "belarus",
        "poland border",
    )

    # Multilingual migration-context terms used for channel validation.
    MIGRATION_TERMS = (
        # English
        "migration",
        "migrant",
        "migrants",
        "refugee",
        "refugees",
        "asylum seeker",
        "asylum seekers",
        "immigration",
        "illegal immigration",
        "irregular migration",
        "border crossing",
        "cross the border",
        "migrant boat",
        "refugee boat",
        "smuggler",
        "smugglers",
        "human smuggling",
        "human trafficking",
        "deportation",
        "deported",
        "coast guard",

        # Spanish
        "migración",
        "migracion",
        "migrante",
        "migrantes",
        "refugiado",
        "refugiados",
        "solicitante de asilo",
        "solicitantes de asilo",
        "inmigración",
        "inmigracion",
        "inmigrante",
        "inmigrantes",
        "cruce fronterizo",
        "cruzar la frontera",
        "patera",
        "pateras",
        "cayuco",
        "cayucos",
        "tráfico de migrantes",
        "trafico de migrantes",
        "devolución",
        "devolucion",

        # French
        "migration",
        "migrant",
        "migrants",
        "réfugié",
        "réfugiés",
        "refugie",
        "refugies",
        "demandeur d'asile",
        "demandeurs d'asile",
        "immigration",
        "frontière",
        "frontiere",
        "passeur",
        "passeurs",

        # Italian
        "migrante",
        "migranti",
        "rifugiato",
        "rifugiati",
        "immigrazione",
        "sbarco",
        "sbarchi",
        "scafista",
        "scafisti",

        # Arabic
        "الهجرة",
        "مهاجر",
        "مهاجرين",
        "مهاجرون",
        "لاجئ",
        "لاجئين",
        "لجوء",
        "الحدود",
        "عبور الحدود",
        "قارب مهاجرين",
        "تهريب البشر",
        "تهريب المهاجرين",

        # Russian / common CIS
        "миграция",
        "мигрант",
        "мигранты",
        "беженец",
        "беженцы",
        "убежище",
        "граница",
        "нелегальная миграция",
    )

    # Terms that are much more operational than generic migration mentions.
    OPERATIONAL_MIGRATION_TERMS = (
        "crossing",
        "cross the border",
        "border crossing",
        "arrived",
        "arrival",
        "departure",
        "departing",
        "boat",
        "vessel",
        "intercepted",
        "rescued",
        "rescue",
        "smuggler",
        "smugglers",
        "smuggling",
        "meeting point",
        "gathering point",
        "departure point",
        "cruce",
        "cruzar",
        "llegada",
        "llegaron",
        "salida",
        "patera",
        "cayuco",
        "interceptados",
        "rescatados",
        "passeur",
        "passeurs",
        "traversée",
        "traversee",
        "sbarco",
        "sbarchi",
        "عبور",
        "قارب",
        "قوارب",
        "تهريب",
        "пересечение",
        "границы",
    )

    # Phrases indicating obvious title/name ambiguity and non-migration use.
    # These do not automatically blacklist a channel; they subtract from the
    # validation score unless genuine migration content is also present.
    NON_MIGRATION_HINTS = (
        "tickets",
        "ticket",
        "club",
        "dj",
        "concert",
        "festival",
        "music",
        "party",
        "album",
        "gaming",
        "game",
        "movie",
        "cinema",
        "anime",
        "crypto",
        "token",
        "trading",
        "casino",
        "barrel",
        "release",
        "tour dates",
    )

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
        "cruce fronterizo",
        "cruzar la frontera",
        "tráfico de migrantes",
        "trafico de migrantes",
        "عبور الحدود",
        "تهريب المهاجرين",
    )

    FOOTER_PATTERNS = (
        r"(?im)^\s*[🚀📲✅🔔👉👈🏻⬅️➡️]*\s*подписаться\s+на\s+канал:.*$",
        r"(?im)^\s*мигранты\.рф\s*\|\s*подписаться.*$",
        r"(?im)^\s*мигранты\s*[—-]\s*всё\s+как\s+есть.*$",
        r"(?im)^\s*обуна\s+бўлинг.*$",
        r"(?im)^\s*россиядаги\s+ўзбеклар\s+канали.*$",
        r"(?im)^\s*@[\w_]+\s*[⬅️➡️👈👉]*\s*$",
        r"(?im)^\s*поділіться\s+цією\s+інформацією.*$",
        r"(?im)^\s*записатися\s+на\s+консультацію:.*$",
        r"(?im)^\s*дізнатися\s+більше:.*$",
        r"(?im)^\s*facebook\.com/.*$",
        r"(?im)^\s*telegram\.me/.*$",
        r"(?im)^\s*t\.me/.*$",
    )

    WESTERN_MED_ROUTE_TERMS = (
        "ceuta",
        "sebta",
        "سبتة",
        "melilla",
        "fnideq",
        "الفنيدق",
        "tetouan",
        "tétouan",
        "تطوان",
        "tanger",
        "tangier",
        "طنجة",
        "morocco",
        "maroc",
        "marruecos",
        "المغرب",
        "estrecho de gibraltar",
        "strait of gibraltar",
        "mediterráneo occidental",
        "western mediterranean",
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

        self.channel_sample_size = self._env_int(
            "TELEGRAM_CHANNEL_SAMPLE_SIZE",
            self.DEFAULT_CHANNEL_SAMPLE_SIZE,
            minimum=5,
            maximum=50,
        )

        self.min_channel_score = self._env_int(
            "TELEGRAM_MIN_CHANNEL_SCORE",
            self.DEFAULT_MIN_CHANNEL_SCORE,
            minimum=1,
            maximum=20,
        )

        self.explicit_channels = (
            self._load_explicit_channels()
        )

        # One instance is reused by main.py across every query group, so these
        # caches significantly reduce repeated Telegram API work.
        self._channel_cache: Dict[
            str,
            Dict[str, Any]
        ] = {}

        self._discovery_term_cache: Dict[
            str,
            List[str]
        ] = {}

        self._validation_cache: Dict[
            str,
            Dict[str, Any]
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

        search_terms = (
            self._expand_query(
                query
            )
        )

        if not search_terms:
            print(
                "TELEGRAM COLLECTOR: no usable search terms."
            )
            return []

        discovery_terms = (
            self._build_discovery_terms(
                query=query,
                search_terms=search_terms,
            )
        )

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

            discovered = (
                self._collect_candidate_channels(
                    client=client,
                    discovery_terms=discovery_terms,
                )
            )

            print(
                "Telegram public channels discovered: "
                f"{len(discovered)}"
            )

            if not discovered:
                return []

            validated = (
                self._validate_candidate_channels(
                    client=client,
                    channels=discovered,
                )
            )

            accepted = [
                item
                for item in validated
                if item.get(
                    "accepted"
                )
            ]

            rejected = [
                item
                for item in validated
                if not item.get(
                    "accepted"
                )
            ]

            print(
                "Telegram channels accepted after content validation: "
                f"{len(accepted)}"
            )

            print(
                "Telegram channels rejected after content validation: "
                f"{len(rejected)}"
            )

            if accepted:
                print(
                    "Telegram accepted channel preview: "
                    f"{self._validation_preview(accepted)}"
                )

            if rejected:
                print(
                    "Telegram rejected channel preview: "
                    f"{self._validation_preview(rejected)}"
                )

            accepted_channels = [
                item[
                    "channel"
                ]
                for item in accepted[
                    :self.MAX_VALIDATED_CHANNELS_PER_QUERY
                ]
            ]

            if not accepted_channels:
                print(
                    "Telegram recent public-channel matches: 0"
                )
                return []

            posts = (
                self._search_channels(
                    client=client,
                    channels=accepted_channels,
                    search_terms=search_terms,
                    cutoff=cutoff,
                    max_results=max_results,
                )
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
        Historical collector hook for the later Telegram backfill.

        Channel validation uses current/recent channel content because it is a
        source-quality test. Message collection itself respects the requested
        historical interval.
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

        search_terms = (
            self._expand_query(
                query
            )
        )

        if not search_terms:
            return []

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

            discovered = (
                self._collect_candidate_channels(
                    client=client,
                    discovery_terms=discovery_terms,
                )
            )

            validated = (
                self._validate_candidate_channels(
                    client=client,
                    channels=discovered,
                )
            )

            accepted_channels = [
                item[
                    "channel"
                ]
                for item in validated
                if item.get(
                    "accepted"
                )
            ]

            return self._search_channels(
                client=client,
                channels=accepted_channels,
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

        # Explicit public channels are priority candidates, but they are not
        # blindly trusted: they still pass the content validator below.
        for username in self.explicit_channels:
            channel = (
                self._resolve_public_channel(
                    client=client,
                    username=username,
                )
            )

            if channel:
                channel[
                    "discovery_origin"
                ] = "EXPLICIT"

                channels_by_key[
                    channel[
                        "key"
                    ]
                ] = channel

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

                        channel[
                            "discovery_origin"
                        ] = (
                            f"DIRECTORY:{term}"
                        )

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

        channel = (
            self._channel_from_entity(
                entity
            )
        )

        if channel:
            self._channel_cache[
                cache_key
            ] = channel

            self._channel_cache[
                channel[
                    "key"
                ]
            ] = channel

        return channel

    def _channel_from_entity(
        self,
        entity,
    ) -> Optional[Dict[str, Any]]:
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

        # Auditability requirement:
        # only channels with a public t.me username are accepted.
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
            "discovery_origin":
                None,
        }

    # ======================================================
    # CONTENT-BASED SOURCE VALIDATION
    # ======================================================

    def _validate_candidate_channels(
        self,
        *,
        client: TelegramClient,
        channels: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        results = []

        for channel in channels:
            key = channel[
                "key"
            ]

            cached = (
                self._validation_cache.get(
                    key
                )
            )

            if cached is not None:
                results.append(
                    cached
                )
                continue

            validation = (
                self._validate_one_channel(
                    client=client,
                    channel=channel,
                )
            )

            self._validation_cache[
                key
            ] = validation

            results.append(
                validation
            )

        # Accepted channels with stronger evidence are searched first.
        results.sort(
            key=lambda item: (
                bool(
                    item.get(
                        "accepted"
                    )
                ),
                int(
                    item.get(
                        "score",
                        0,
                    )
                ),
                int(
                    item.get(
                        "migration_posts",
                        0,
                    )
                ),
            ),
            reverse=True,
        )

        return results

    def _validate_one_channel(
        self,
        *,
        client: TelegramClient,
        channel: Dict[str, Any],
    ) -> Dict[str, Any]:
        samples = []

        try:
            for message in client.iter_messages(
                channel[
                    "entity"
                ],
                limit=self.channel_sample_size,
            ):
                text = str(
                    getattr(
                        message,
                        "message",
                        "",
                    )
                    or ""
                ).strip()

                if text:
                    samples.append(
                        text
                    )

        except FloodWaitError as error:
            raise RuntimeError(
                "Telegram validation flood wait: "
                f"{error.seconds} seconds."
            ) from error

        except Exception as error:
            return {
                "channel":
                    channel,
                "accepted":
                    False,
                "score":
                    -10,
                "migration_posts":
                    0,
                "operational_posts":
                    0,
                "route_posts":
                    0,
                "sample_posts":
                    0,
                "reason":
                    (
                        "VALIDATION_ERROR:"
                        f"{type(error).__name__}"
                    ),
            }

        title_blob = (
            f"{channel.get('title', '')} "
            f"{channel.get('username', '')}"
        ).lower()

        score = 0
        migration_posts = 0
        operational_posts = 0
        route_posts = 0
        non_migration_hits = 0

        for text in samples:
            cleaned_text = self._clean_post_text(
                text
            )
            lowered = cleaned_text.lower()

            if not lowered:
                continue

            migration_hits = (
                self._count_term_hits(
                    lowered,
                    self.MIGRATION_TERMS,
                )
            )

            operational_hits = (
                self._count_term_hits(
                    lowered,
                    self.OPERATIONAL_MIGRATION_TERMS,
                )
            )

            route_hits = (
                self._count_term_hits(
                    lowered,
                    self.ROUTE_TERMS,
                )
            )

            western_med_hits = (
                self._count_term_hits(
                    lowered,
                    self.WESTERN_MED_ROUTE_TERMS,
                )
            )

            non_migration = (
                self._count_term_hits(
                    lowered,
                    self.NON_MIGRATION_HINTS,
                )
            )

            if migration_hits:
                migration_posts += 1

                # Basic migration-context evidence.
                score += min(
                    migration_hits,
                    3,
                )

            if operational_hits and migration_hits:
                operational_posts += 1

                # Operational migration content is particularly useful.
                score += 2

            if route_hits and migration_hits:
                route_posts += 1

                # Named route/location + migration is high-value.
                score += 2

            if western_med_hits and migration_hits:
                score += 3

            non_migration_hits += (
                non_migration
            )

        # Channel title/username helps only a little. Content remains decisive.
        title_migration_hits = (
            self._count_term_hits(
                title_blob,
                self.MIGRATION_TERMS,
            )
        )

        title_route_hits = (
            self._count_term_hits(
                title_blob,
                self.ROUTE_TERMS,
            )
        )

        title_noise_hits = (
            self._count_term_hits(
                title_blob,
                self.NON_MIGRATION_HINTS,
            )
        )

        if title_migration_hits:
            score += 1

        if title_route_hits:
            score += 1

        # If "asylum" is merely an entertainment/brand name, this pushes
        # the score down unless the post sample contains actual migration.
        if title_noise_hits:
            score -= min(
                title_noise_hits,
                3,
            )

        if (
            non_migration_hits > 0
            and migration_posts == 0
        ):
            score -= min(
                non_migration_hits,
                5,
            )

        sample_count = len(
            samples
        )

        # Minimum evidence rules:
        # - at least one actual migration-content post
        # - and either sufficient score OR repeated migration content
        accepted = bool(
            migration_posts >= 1
            and (
                score >= self.min_channel_score
                or migration_posts >= 2
            )
        )

        if not samples:
            reason = (
                "NO_TEXT_SAMPLE"
            )
        elif migration_posts == 0:
            reason = (
                "NO_MIGRATION_CONTENT"
            )
        elif accepted:
            reason = (
                "CONTENT_VALIDATED"
            )
        else:
            reason = (
                "WEAK_MIGRATION_EVIDENCE"
            )

        return {
            "channel":
                channel,
            "accepted":
                accepted,
            "score":
                score,
            "migration_posts":
                migration_posts,
            "operational_posts":
                operational_posts,
            "route_posts":
                route_posts,
            "sample_posts":
                sample_count,
            "reason":
                reason,
        }

    def _validation_preview(
        self,
        validations: List[Dict[str, Any]],
        limit: int = 8,
    ) -> List[str]:
        preview = []

        for item in validations[
            :limit
        ]:
            channel = item[
                "channel"
            ]

            username = (
                channel.get(
                    "username"
                )
                or channel.get(
                    "title"
                )
                or "unknown"
            )

            preview.append(
                (
                    f"@{username}"
                    f"(score={item.get('score')},"
                    f"mig={item.get('migration_posts')},"
                    f"op={item.get('operational_posts')},"
                    f"route={item.get('route_posts')},"
                    f"{item.get('reason')})"
                )
            )

        return preview

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
        """Scan every validated public channel before selecting recent results.

        Previous logic stopped as soon as the global result limit was reached
        and limited each channel to approximately one result. That favored
        early channels and could hide newer posts from later channels.

        This implementation scans every accepted channel, applies the existing
        migration/topic checks, deduplicates, and only then selects the newest
        results. API work remains bounded by TELEGRAM_SCAN_LIMIT.
        """
        if not channels:
            return []

        query_topic_terms = self._build_post_topic_terms(search_terms)
        scan_limit = self._env_int(
            "TELEGRAM_SCAN_LIMIT", 240, minimum=40, maximum=600
        )
        print(f"Telegram local post topic terms: {query_topic_terms}")
        print(
            f"Telegram scan configuration: channels={len(channels)}, "
            f"per_channel_limit={scan_limit}, result_limit={max_results}"
        )

        posts_by_id: Dict[str, Dict[str, Any]] = {}
        total_scanned = 0
        total_context = 0
        total_topic = 0
        channel_errors = 0
        truncated_channels = 0

        for channel in channels:
            scanned = 0
            context_matches = 0
            topic_matches = 0
            reached_cutoff = False
            try:
                iterator = client.iter_messages(
                    channel["entity"], limit=scan_limit, offset_date=end_at
                )
                for message in iterator:
                    message_date = (
                        self._ensure_utc(message.date)
                        if getattr(message, "date", None) else None
                    )
                    if message_date is not None and message_date < cutoff:
                        reached_cutoff = True
                        break
                    if end_at is not None and message_date is not None and message_date >= end_at:
                        continue

                    scanned += 1
                    normalized = self._normalize_message(
                        message=message,
                        channel=channel,
                        search_query="LOCAL_SCAN:" + ",".join(query_topic_terms[:8]),
                    )
                    if not normalized:
                        continue
                    cleaned_post_text = self._clean_post_text(normalized["text"])
                    text_lower = cleaned_post_text.lower()
                    if not text_lower or not self._count_term_hits(
                        text_lower, self.MIGRATION_TERMS
                    ):
                        continue
                    context_matches += 1
                    if query_topic_terms and not self._matches_any_topic_term(
                        text_lower, query_topic_terms
                    ):
                        continue
                    topic_matches += 1
                    normalized["text"] = cleaned_post_text
                    posts_by_id.setdefault(normalized["post_id"], normalized)

                if scanned >= scan_limit and not reached_cutoff:
                    truncated_channels += 1
                    print(
                        f"TELEGRAM SCAN LIMIT @{channel.get('username')}: "
                        f"scanned={scanned}; older posts may remain unscanned"
                    )
                print(
                    f"TELEGRAM CHANNEL SCAN @{channel.get('username')}: "
                    f"scanned={scanned} migration={context_matches} "
                    f"topic={topic_matches}"
                )
            except FloodWaitError as error:
                raise RuntimeError(
                    f"Telegram message-scan flood wait: {error.seconds} seconds."
                ) from error
            except Exception as error:
                channel_errors += 1
                print(
                    "TELEGRAM CHANNEL WARNING: "
                    f"@{channel.get('username')} | "
                    f"{type(error).__name__}: {error}"
                )
            finally:
                total_scanned += scanned
                total_context += context_matches
                total_topic += topic_matches

        posts = sorted(
            posts_by_id.values(),
            key=lambda item: item.get("published_at") or "",
            reverse=True,
        )
        # Give event-like Telegram reports a fair chance to reach the
        # existing strict operational/assertion filters in main.py.
        # This is a retrieval priority only, NOT an event classification.
        # Reserve slots for Ceuta/Melilla and for other migration routes.
        event_like = [p for p in posts if self._telegram_event_candidate(p.get("text", ""))]
        ceuta_event = [p for p in event_like if self._is_ceuta_melilla_post(p.get("text", ""))]
        other_event = [p for p in event_like if not self._is_ceuta_melilla_post(p.get("text", ""))]
        ceuta_context = [p for p in posts if self._is_ceuta_melilla_post(p.get("text", ""))]
        selected = []
        selected_ids = set()

        def add_from(items, quota):
            for item in items:
                if len(selected) >= max_results or quota <= 0:
                    break
                if item["post_id"] in selected_ids:
                    continue
                selected.append(item)
                selected_ids.add(item["post_id"])
                quota -= 1

        # Do not let one geographic area monopolize all result slots.
        ceuta_quota = max(1, max_results * 2 // 5)
        other_quota = max(1, max_results * 2 // 5)
        add_from(ceuta_event, ceuta_quota)
        add_from(other_event, other_quota)
        # Maintain primary-area visibility even if there are no event-like posts.
        add_from(ceuta_context, ceuta_quota)
        # Fill remaining slots with event-like posts, then contextual coverage.
        add_from(event_like, max_results)
        add_from(posts, max_results)
        selected.sort(
            key=lambda item: item.get("published_at") or "", reverse=True
        )
        print(
            "TELEGRAM GEOGRAPHY: "
            f"ceuta_melilla_candidates={len(ceuta_context)} "
            f"ceuta_melilla_selected={sum(self._is_ceuta_melilla_post(p.get('text', '')) for p in selected)} "
            f"other_migration_selected={sum(not self._is_ceuta_melilla_post(p.get('text', '')) for p in selected)}"
        )
        print(
            "TELEGRAM COVERAGE: "
            f"channels={len(channels)} scanned={total_scanned} "
            f"migration_context={total_context} topic_matches={total_topic} "
            f"unique_matches={len(posts)} event_candidates={len(event_like)} "
            f"event_candidates_selected={sum(self._telegram_event_candidate(p.get('text', '')) for p in selected)} "
            f"returned={len(selected)} "
            f"channel_errors={channel_errors} scan_limit_channels={truncated_channels}"
        )
        return selected

    @staticmethod
    def _telegram_event_candidate(text: str) -> bool:
        """Lightweight multilingual retrieval ranking, not event verification.

        Reject obvious statistics/biographies and require migration context
        plus an event verb. The main analytical filters remain authoritative.
        """
        t = str(text or "").casefold()
        if not t:
            return False
        if re.search(r"\b(?:in 19\d{2}|in 20[01]\d|since 19\d{2}|since 20[01]\d)\b", t):
            return False
        if re.search(r"\b(?:this year|last year|annual report|year to date|ytd|en lo que va de año|este año)\b", t) and not re.search(r"\b(?:today|yesterday|hoy|ayer|last night|anoche)\b", t):
            return False
        migration = re.search(
            r"\b(?:migrants?|refugees?|asylum seekers?|smugglers?|migration|"
            r"migrantes?|refugiados?|pateras?|cayucos?|inmigrantes?|"
            r"migranti|rifugiati|migranten|flüchtlinge|"
            r"مهاجرين|مهاجرون|مهاجر|لاجئين|لاجئ)\b",
            t, re.UNICODE
        )
        if not migration:
            return False
        action = re.search(
            r"\b(?:rescued?|rescue operation|intercepted?|arrested?|detained?|"
            r"deported?|capsized?|shipwreck(?:ed)?|drowned?|crossed?|"
            r"arrived?|landed?|departed?|seized?|stopped?|"
            r"rescatad[oa]s?|rescat(?:aron|ados?)|detenid[oa]s?|"
            r"interceptad[oa]s?|llegaron|llegad[oa]s?|"
            r"naufrag(?:io|aron)|ahogad[oa]s?|"
            r"soccorsi|salvati|arrestati|sbarcati|"
            r"gerettet|festgenommen|angekommen|"
            r"إنقاذ|أنقذت|اعتراض|اعتقال|غرق|وصلوا)\b",
            t, re.UNICODE
        )
        return bool(action)

    @staticmethod
    def _is_ceuta_melilla_post(text: str) -> bool:
        """Detect primary-area mentions in actual post text, not channel names."""
        normalized = str(text or "").casefold()
        return any(
            re.search(pattern, normalized, flags=re.UNICODE)
            for pattern in (
                r"(?<!\w)ceuta(?!\w)",
                r"(?<!\w)melilla(?!\w)",
                r"(?<!\w)sebta(?!\w)",
                r"(?<!\w)سبتة(?!\w)",
                r"(?<!\w)مليلية(?!\w)",
            )
        )

    def _build_post_topic_terms(
        self,
        search_terms: List[str],
    ) -> List[str]:
        """
        Remove generic migration words from the QueryEngine terms.

        What remains expresses the actual sub-topic of the query:
        border/crossing, sea/boat, departure/arrival, coordination, etc.
        """

        generic_migration_terms = {
            "migration",
            "migrant",
            "migrants",
            "refugee",
            "refugees",
            "asylum",
            "immigration",
            "migracion",
            "migración",
            "migrante",
            "migrantes",
            "refugiado",
            "refugiados",
            "inmigracion",
            "inmigración",
            "الهجرة",
            "مهاجر",
            "مهاجرين",
            "لاجئ",
            "لاجئين",
            "миграция",
            "мигрант",
            "мигранты",
            "беженец",
            "беженцы",
        }

        result: List[str] = []

        for term in search_terms:
            cleaned = re.sub(
                r"\s+",
                " ",
                str(
                    term
                    or ""
                ).lower(),
            ).strip()

            if (
                not cleaned
                or cleaned in generic_migration_terms
                or cleaned in self.STOPWORDS
            ):
                continue

            self._append_unique(
                result,
                cleaned,
            )

        return result[:12]

    def _matches_any_topic_term(
        self,
        text: str,
        topic_terms: List[str],
    ) -> bool:
        """
        Query-topic matching with small multilingual concept expansions.
        """

        expansions = {
            "border": (
                "border",
                "frontier",
                "frontera",
                "frontière",
                "frontiere",
                "confine",
                "الحدود",
                "граница",
                "границы",
            ),
            "crossing": (
                "crossing",
                "crossed",
                "cross the border",
                "cruce",
                "cruzar",
                "traversée",
                "traversee",
                "عبور",
                "пересечение",
            ),
            "route": (
                "route",
                "ruta",
                "itinéraire",
                "itineraire",
                "طريق",
                "маршрут",
            ),
            "checkpoint": (
                "checkpoint",
                "border post",
                "puesto fronterizo",
                "poste frontière",
                "poste frontiere",
            ),
            "patrol": (
                "patrol",
                "border guard",
                "guardia civil",
                "guardia fronteriza",
                "garde-frontière",
                "garde frontiere",
                "حرس الحدود",
            ),
            "boat": (
                "boat",
                "boats",
                "patera",
                "pateras",
                "cayuco",
                "cayucos",
                "barca",
                "bateau",
                "bateaux",
                "قارب",
                "قوارب",
            ),
            "vessel": (
                "vessel",
                "ship",
                "embarcación",
                "embarcacion",
                "navire",
            ),
            "sea": (
                "sea",
                "mediterranean",
                "mediterráneo",
                "mediterraneo",
                "mer",
                "البحر",
            ),
            "coast guard": (
                "coast guard",
                "guardia costiera",
                "guardia civil",
                "salvamento marítimo",
                "salvamento maritimo",
                "garde-côtes",
                "garde cotes",
            ),
            "rescue": (
                "rescue",
                "rescued",
                "rescatado",
                "rescatados",
                "sauvetage",
                "secouru",
                "إنقاذ",
            ),
            "intercepted": (
                "intercepted",
                "intercept",
                "interceptado",
                "interceptados",
                "intercepté",
                "interceptes",
                "اعتراض",
            ),
            "departure": (
                "departure",
                "departed",
                "leaving",
                "salida",
                "salieron",
                "départ",
                "depart",
                "partenza",
                "مغادرة",
            ),
            "departing": (
                "departing",
                "leaving",
                "saliendo",
                "partant",
                "مغادرة",
            ),
            "leaving": (
                "leaving",
                "departure",
                "salida",
                "départ",
                "depart",
                "مغادرة",
            ),
            "arrived": (
                "arrived",
                "arrival",
                "llegó",
                "llego",
                "llegaron",
                "arrivée",
                "arrivee",
                "sbarco",
                "وصل",
                "وصول",
            ),
            "arrival": (
                "arrival",
                "arrived",
                "llegada",
                "llegaron",
                "arrivée",
                "arrivee",
                "sbarco",
                "وصول",
            ),
            "coordination": (
                "coordination",
                "coordinate",
                "organized",
                "organised",
                "organizar",
                "grupo",
                "telegram group",
                "whatsapp group",
                "meeting point",
                "gathering point",
                "تنسيق",
            ),
        }

        normalized = str(
            text
            or ""
        ).lower()

        for topic in topic_terms:
            candidates = expansions.get(
                topic,
                (topic,),
            )

            for candidate in candidates:
                if candidate in normalized:
                    return True

        return False

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
    # QUERY CONVERSION / DISCOVERY
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
        Build a limited but multilingual directory-search set.

        Generic migration queries automatically gain Western Mediterranean
        discovery terms. This is source discovery only; actual messages still
        pass content validation and the normal analytical pipeline.
        """

        query_lower = (
            str(
                query
                or ""
            ).lower()
        )

        result: List[str] = []

        # Core multilingual migration discovery.
        preferred = (
            "migration",
            "migrant",
            "migrantes",
            "migración",
            "refugee",
            "الهجرة",
        )

        for term in preferred:
            self._append_unique(
                result,
                term,
            )

        # Route-specific discovery relevant to the Western Mediterranean
        # monitor, including Ceuta/Melilla and Moroccan terminology.
        route_discovery = (
            "ceuta",
            "ceuta migrantes",
            "ceuta inmigracion",
            "sebta",
            "sebta migration",
            "سبتة",
            "سبتة مهاجرين",
            "melilla",
            "melilla migrantes",
            "melilla inmigracion",
            "fnideq",
            "fnideq migration",
            "الفنيدق",
            "tetouan",
            "tétouan",
            "tetouan migration",
            "تطوان",
            "tanger",
            "tangier",
            "tanger migration",
            "طنجة",
            "morocco migration",
            "morocco migrants",
            "maroc migration",
            "maroc migrants",
            "marruecos migrantes",
            "marruecos inmigracion",
            "المغرب الهجرة",
            "المغرب مهاجرين",
        )

        for term in route_discovery:
            self._append_unique(
                result,
                term,
            )

        # Query-specific terms such as "border", "boat", or named places are
        # appended only while the cap permits.
        for term in search_terms:
            cleaned = (
                term.lower()
                .strip()
            )

            if (
                not cleaned
                or cleaned in self.STOPWORDS
            ):
                continue

            # Generic one-word operational terms alone are weak channel names,
            # so they are not prioritized for directory discovery.
            if cleaned in {
                "border",
                "crossing",
                "route",
                "checkpoint",
                "patrol",
                "boat",
                "vessel",
                "sea",
                "rescue",
                "intercepted",
                "departure",
                "departing",
                "leaving",
                "arrived",
                "arrival",
            }:
                continue

            self._append_unique(
                result,
                cleaned,
            )

        # If the current query itself names a route/location term, make sure
        # it is present near the front of the list.
        for route_term in self.ROUTE_TERMS:
            if route_term in query_lower:
                if route_term in result:
                    result.remove(
                        route_term
                    )

                result.insert(
                    0,
                    route_term,
                )

        return result[
            :self.MAX_DISCOVERY_TERMS
        ]

    # ======================================================
    # HELPERS
    # ======================================================

    def _clean_post_text(
        self,
        text: str,
    ) -> str:
        value = str(
            text
            or ""
        )

        for pattern in self.FOOTER_PATTERNS:
            value = re.sub(
                pattern,
                " ",
                value,
            )

        value = re.sub(
            r"\n{3,}",
            "\n\n",
            value,
        )
        value = re.sub(
            r"[ \t]{2,}",
            " ",
            value,
        )

        return value.strip()

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

    def _load_explicit_channels(self) -> List[str]:
        """Load registered Telegram public channels and explicit overrides.

        The source registry's category assignments are not changed.
        """
        raw = str(os.getenv("TELEGRAM_PUBLIC_CHANNELS", "") or "")
        registry_channels = []
        registry_path = (
            Path(__file__).resolve().parent.parent
            / "config" / "source_registry.json"
        )
        try:
            with registry_path.open("r", encoding="utf-8") as handle:
                registry = json.load(handle)
            entries = registry.get("TELEGRAM", {})
            if isinstance(entries, dict):
                registry_channels = list(entries.keys())
        except (OSError, ValueError, TypeError) as error:
            print(f"TELEGRAM REGISTRY WARNING: {type(error).__name__}: {error}")

        result = []
        for item in registry_channels + raw.split(","):
            cleaned = str(item or "").strip().lstrip("@").strip("/")
            if (re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", cleaned)
                    and cleaned.lower() not in {x.lower() for x in result}):
                result.append(cleaned)
        print(f"Telegram registered public channels: {len(result)}")
        return result

    @staticmethod
    def _count_term_hits(
        text: str,
        terms,
    ) -> int:
        """
        Count distinct configured terms present in normalized text.
        Distinct-term counting avoids one repeated keyword dominating score.
        """

        normalized = (
            str(
                text
                or ""
            ).lower()
        )

        hits = 0

        for term in terms:
            cleaned = str(
                term
                or ""
            ).lower().strip()

            if (
                cleaned
                and cleaned in normalized
            ):
                hits += 1

        return hits

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
