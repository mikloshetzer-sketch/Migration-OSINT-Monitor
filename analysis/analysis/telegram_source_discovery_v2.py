"""
Migration OSINT Monitor

File:
analysis/telegram_source_discovery_v2.py

Purpose:
Independent Telegram Source Discovery & Coverage Engine V2.

This remains completely separate from the production Telegram collector.

Safety / isolation:
- no database writes;
- no private chats/groups;
- no joins/subscriptions;
- no modification of the production source list;
- no paid Telegram Stars searches;
- writes only telegram-source-discovery-v2.json to repository root.

V2 improvements:
1. Keeps the V1 global public-channel discovery mechanism.
2. Uses existing production filters only as read-only evidence.
3. Adds a dedicated PRECURSOR / PREPARATORY ACTION detector.
4. Scores sources from several independent quality dimensions instead of
   treating a small number of "operational" matches as sufficient.
5. Penalizes inaccessible/placeholder content and suspiciously weak sources.
6. Produces transparent score components and per-channel reasons.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CheckSearchPostsFloodRequest,
    SearchPostsRequest,
)
from telethon.tl.types import InputPeerEmpty

# Read-only use of production filters.
try:
    from analysis.noise_filter import NoiseFilter
except Exception:
    NoiseFilter = None

try:
    from analysis.operational_event_filter import OperationalEventFilter
except Exception:
    OperationalEventFilter = None

try:
    from analysis.early_warning_review_detector import EarlyWarningReviewDetector
except Exception:
    EarlyWarningReviewDetector = None


OUTPUT_PATH = REPO_ROOT / "telegram-source-discovery-v2.json"

DEFAULT_MAX_QUERIES = 8
DEFAULT_RESULTS_PER_QUERY = 25
DEFAULT_SAMPLE_POSTS_PER_CHANNEL = 4


DISCOVERY_QUERIES: List[Dict[str, str]] = [
    {
        "id": "en_border_crossing",
        "language": "en",
        "family": "MOVEMENT",
        "query": "migrants border crossing",
    },
    {
        "id": "en_interception",
        "language": "en",
        "family": "INTERCEPTION",
        "query": "migrants intercepted",
    },
    {
        "id": "en_precursor_border",
        "language": "en",
        "family": "PRECURSOR",
        "query": "migrants border barrier deployment",
    },
    {
        "id": "es_border_crossing",
        "language": "es",
        "family": "MOVEMENT",
        "query": "migrantes frontera cruce",
    },
    {
        "id": "ru_enforcement",
        "language": "ru",
        "family": "ENFORCEMENT",
        "query": "мигранты задержаны",
    },
    {
        "id": "ru_border_precursor",
        "language": "ru",
        "family": "PRECURSOR",
        "query": "мигранты граница усиление",
    },
    {
        "id": "ar_border",
        "language": "ar",
        "family": "MOVEMENT",
        "query": "مهاجرين الحدود",
    },
    {
        "id": "ar_crossing",
        "language": "ar",
        "family": "MOVEMENT",
        "query": "عبور المهاجرين",
    },
    {
        "id": "fr_crossing",
        "language": "fr",
        "family": "MOVEMENT",
        "query": "migrants frontière passage",
    },
    {
        "id": "it_arrival",
        "language": "it",
        "family": "MOVEMENT",
        "query": "migranti arrivi costa",
    },
]


MIGRATION_PATTERNS = (
    r"\bmigrants?\b",
    r"\bimmigrants?\b",
    r"\brefugees?\b",
    r"\basylum\b",
    r"\bmigrantes?\b",
    r"\brefugiados?\b",
    r"\bmigranti\b",
    r"\br[ée]fugi[ée]s?\b",
    r"\bмигрант\w*\b",
    r"\bбежен\w*\b",
    r"\bмуҳожир\w*\b",
    r"(?:مهاجر|مهاجرين|لاجئ|لاجئين)",
)

GEOGRAPHIC_PATTERNS = (
    # Generic geographic structures.
    r"\bborder\b",
    r"\bcoast\b",
    r"\bport\b",
    r"\bcheckpoint\b",
    r"\bfrontier\b",
    r"\bfrontera\b",
    r"\bcosta\b",
    r"\bpuerto\b",
    r"\bfronti[èe]re\b",
    r"\bграниц\w*\b",
    r"\bКПП\b",
    r"(?:الحدود|المعبر|الساحل|الميناء)",
    # Recurrent route / country geography, not Ceuta-specific scoring.
    r"\bSpain\b|\bMorocco\b|\bItaly\b|\bGreece\b|\bFrance\b|\bUK\b|\bBritain\b",
    r"\bBelarus\b|\bLatvia\b|\bLithuania\b|\bPoland\b|\bRussia\b|\bTurkey\b",
    r"\bCanary Islands\b|\bAegean\b|\bMediterranean\b|\bAtlantic\b|\bChannel\b",
    r"\bEspaña\b|\bMarruecos\b|\bItalia\b|\bGrecia\b",
    r"\bРоссия\b|\bБеларус\w*\b|\bЛатви\w*\b|\bЛитв\w*\b|\bПольш\w*\b",
    r"(?:إسبانيا|المغرب|إيطاليا|اليونان|روسيا|بيلاروسيا|لاتفيا|ليتوانيا|بولندا)",
)

INACCESSIBLE_PATTERNS = (
    r"this channel can.?t be displayed",
    r"violated local laws",
    r"content unavailable",
)

PRECURSOR_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "BORDER_HARDENING": (
        r"\b(?:build|building|construct|construction|erect)\w*\b.{0,120}\b(?:barrier|fence|wall)\b",
        r"\b(?:barrier|fence|wall)\b.{0,120}\b(?:border|crossing|migrants?)\b",
        r"\b(?:tighten|reinforce|strengthen|harden)\w*\b.{0,100}\bborder\b",
        r"\b(?:закрыт\w*|усилен\w*|укреп\w*|стро\w*)\b.{0,100}\b(?:границ\w*|забор\w*|огражден\w*)\b",
        r"(?:تشديد|تعزيز|بناء).{0,100}(?:الحدود|السياج|الحاجز)",
    ),
    "FORCE_DEPLOYMENT": (
        r"\b(?:deploy|deployment|reinforcements?)\b.{0,120}\b(?:border|troops?|police|guard|military)\b",
        r"\b(?:troops?|military|police|border guard)\b.{0,120}\b(?:deploy|deployment|reinforce)\w*\b",
        r"\b(?:развернут\w*|направил\w*|переброс\w*|усил\w*)\b.{0,120}\b(?:полици\w*|военн\w*|погранич\w*)\b",
        r"(?:نشر|تعزيز).{0,120}(?:الجيش|الشرطة|حرس الحدود)",
    ),
    "CROSSING_STATUS_CHANGE": (
        r"\b(?:border crossing|checkpoint)\b.{0,120}\b(?:closed|reopened|restricted|suspended)\b",
        r"\b(?:closed|reopened|restricted|suspended)\b.{0,120}\b(?:border crossing|checkpoint)\b",
        r"\b(?:КПП|пункт\s+пропуска)\b.{0,120}\b(?:закрыт\w*|открыт\w*|возобнов\w*|огранич\w*)\b",
        r"(?:المعبر|نقطة العبور).{0,120}(?:إغلاق|إعادة فتح|تقييد)",
    ),
    "GATHERING_CONCENTRATION": (
        r"\b(?:migrants?|people)\b.{0,120}\b(?:gathering|concentrating|assembling|massing)\b",
        r"\b(?:gathering|concentration|assembly)\b.{0,120}\b(?:migrants?|border)\b",
        r"\b(?:мигрант\w*)\b.{0,120}\b(?:собира\w*|скоплен\w*|концентрац\w*)\b",
        r"(?:مهاجرين|مهاجرون).{0,120}(?:تجمع|احتشاد)",
    ),
    "ROUTE_INFRASTRUCTURE": (
        r"\b(?:tunnel|route|path|corridor)\b.{0,140}\b(?:migrants?|smugglers?|border)\b",
        r"\b(?:smuggling network|smugglers?)\b.{0,140}\b(?:route|crossing|border|tunnel)\b",
        r"\b(?:туннел\w*|маршрут\w*|коридор\w*)\b.{0,140}\b(?:мигрант\w*|контрабанд\w*|границ\w*)\b",
        r"(?:نفق|طريق|مسار).{0,140}(?:المهاجرين|المهربين|الحدود)",
    ),
    "POLICY_PREPARATION": (
        r"\b(?:authorities|government|ministry)\b.{0,140}\b(?:plan|plans|prepare|preparing|proposal)\b.{0,140}\b(?:border|migration|deportation|return)\b",
        r"\b(?:планир\w*|готов\w*|предлож\w*)\b.{0,140}\b(?:границ\w*|миграц\w*|депортац\w*)\b",
        r"(?:تخطط|خطة|اقتراح).{0,140}(?:الحدود|الهجرة|الترحيل)",
    ),
}


def env_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    raw = str(os.getenv(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer; got {raw!r}") from exc

    value = max(minimum, value)
    if maximum is not None:
        value = min(value, maximum)
    return value


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def compact_text(text: str, limit: int = 900) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def matches_any(text: str, patterns: Tuple[str, ...]) -> List[str]:
    hits = []
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
        if match:
            hits.append(match.group(0))
    return hits


def detect_precursors(text: str) -> Dict[str, Any]:
    categories: List[str] = []
    phrases: List[str] = []

    for category, patterns in PRECURSOR_PATTERNS.items():
        local_hits = matches_any(text, patterns)
        if local_hits:
            categories.append(category)
            phrases.extend(local_hits)

    migration_context = bool(matches_any(text, MIGRATION_PATTERNS))
    geographic_context = bool(matches_any(text, GEOGRAPHIC_PATTERNS))

    # A precursor signal must be attached to human migration and to a
    # location/border/route context. This prevents generic security policy
    # or infrastructure stories from becoming migration precursors.
    detected = bool(
        categories
        and migration_context
        and geographic_context
    )

    return {
        "detected": detected,
        "categories": categories if detected else [],
        "matched_phrases": phrases[:10] if detected else [],
    }


class FilterBundle:
    def __init__(self) -> None:
        self.noise_filter = NoiseFilter() if NoiseFilter else None
        self.operational_filter = (
            OperationalEventFilter()
            if OperationalEventFilter
            else None
        )
        self.early_warning_detector = (
            EarlyWarningReviewDetector()
            if EarlyWarningReviewDetector
            else None
        )

    def availability(self) -> Dict[str, bool]:
        return {
            "NoiseFilter": self.noise_filter is not None,
            "OperationalEventFilter":
                self.operational_filter is not None,
            "EarlyWarningReviewDetector":
                self.early_warning_detector is not None,
        }

    def analyze(self, text: str) -> Dict[str, Any]:
        result = {
            "noise": False,
            "operational": False,
            "operational_categories": [],
            "early_warning": False,
            "early_warning_signal": None,
            "precursor": False,
            "precursor_categories": [],
            "migration_relevance": False,
            "geographic_specificity": False,
            "inaccessible_placeholder": False,
            "analysis_error": None,
        }

        try:
            result["migration_relevance"] = bool(
                matches_any(text, MIGRATION_PATTERNS)
            )
            result["geographic_specificity"] = bool(
                matches_any(text, GEOGRAPHIC_PATTERNS)
            )
            result["inaccessible_placeholder"] = bool(
                matches_any(text, INACCESSIBLE_PATTERNS)
            )

            precursor_result = detect_precursors(text)
            result["precursor"] = precursor_result["detected"]
            result["precursor_categories"] = precursor_result["categories"]

            if self.noise_filter is not None:
                noise_result = self.noise_filter.analyze(text)
                result["noise"] = bool(
                    noise_result.get("is_noise")
                )

            if not result["noise"] and self.operational_filter is not None:
                op_result = self.operational_filter.analyze(text)
                result["operational"] = bool(
                    op_result.get("is_operational")
                )
                result["operational_categories"] = list(
                    op_result.get("operational_categories", []) or []
                )

            if (
                not result["noise"]
                and not result["operational"]
                and self.early_warning_detector is not None
            ):
                ew_result = self.early_warning_detector.detect(text)
                result["early_warning"] = bool(
                    ew_result.get("detected")
                )
                result["early_warning_signal"] = ew_result.get(
                    "primary_signal"
                )

        except Exception as exc:
            result["analysis_error"] = f"{type(exc).__name__}: {exc}"

        return result


def score_source(channel: Dict[str, Any]) -> Tuple[int, str, Dict[str, int], List[str]]:
    """
    Multi-dimensional V2 source score.

    A channel cannot become HIGH_VALUE simply because one permissive filter
    classified one or two posts as operational.
    """

    query_count = len(channel["query_ids"])
    family_count = len(channel["query_families"])
    posts = channel["posts_matched"]

    migration_posts = channel["migration_relevant_posts"]
    geographic_posts = channel["geographic_posts"]
    useful_posts = channel["useful_posts"]
    operational_posts = channel["operational_posts"]
    early_posts = channel["early_warning_posts"]
    precursor_posts = channel["precursor_posts"]
    noise_posts = channel["noise_posts"]
    inaccessible_posts = channel["inaccessible_posts"]

    components: Dict[str, int] = {}

    # 1. Breadth: independent queries / families.
    components["query_breadth"] = min(query_count * 2, 6)
    components["family_breadth"] = min(family_count * 2, 4)

    # 2. Migration relevance depth.
    components["migration_relevance"] = min(migration_posts, 5)

    # 3. Geographic specificity.
    components["geographic_specificity"] = min(geographic_posts, 4)

    # 4. Useful analytical output.
    components["operational_value"] = min(operational_posts * 2, 6)
    components["early_warning_value"] = min(early_posts * 2, 4)
    components["precursor_value"] = min(precursor_posts * 3, 6)

    # 5. Repeated useful reporting is stronger than one isolated hit.
    if useful_posts >= 3:
        components["repeat_usefulness"] = 4
    elif useful_posts == 2:
        components["repeat_usefulness"] = 2
    elif useful_posts == 1:
        components["repeat_usefulness"] = 1
    else:
        components["repeat_usefulness"] = 0

    # 6. Penalties.
    components["noise_penalty"] = -min(noise_posts * 2, 6)
    components["inaccessible_penalty"] = -min(inaccessible_posts * 4, 12)

    # Low-value result farms / one-hit sources should not outrank repeated,
    # geographically specific migration reporting.
    if posts == 1 and useful_posts <= 1:
        components["single_hit_penalty"] = -2
    else:
        components["single_hit_penalty"] = 0

    score = sum(components.values())
    score = max(0, score)

    reasons: List[str] = []

    if query_count >= 2:
        reasons.append("DISCOVERED_BY_MULTIPLE_QUERIES")
    if family_count >= 2:
        reasons.append("MULTI_FAMILY_COVERAGE")
    if operational_posts:
        reasons.append("OPERATIONAL_REPORTING")
    if early_posts:
        reasons.append("EARLY_WARNING_REPORTING")
    if precursor_posts:
        reasons.append("PRECURSOR_REPORTING")
    if useful_posts >= 2:
        reasons.append("REPEATED_USEFUL_REPORTING")
    if geographic_posts >= 2:
        reasons.append("GEOGRAPHICALLY_SPECIFIC")
    if inaccessible_posts:
        reasons.append("INACCESSIBLE_CONTENT_PENALTY")
    if noise_posts:
        reasons.append("NOISE_PENALTY")

    # HIGH_VALUE requires more than raw points: repeated useful reporting
    # plus source depth / breadth must also be present.
    high_value_gate = (
        score >= 18
        and useful_posts >= 2
        and migration_posts >= 2
        and (
            query_count >= 2
            or precursor_posts >= 1
            or operational_posts >= 2
        )
        and inaccessible_posts == 0
    )

    watch_gate = (
        score >= 11
        and useful_posts >= 1
        and migration_posts >= 1
        and inaccessible_posts < max(posts, 1)
    )

    candidate_gate = (
        score >= 5
        and migration_posts >= 1
    )

    if high_value_gate:
        classification = "HIGH_VALUE"
    elif watch_gate:
        classification = "WATCH"
    elif candidate_gate:
        classification = "CANDIDATE"
    else:
        classification = "REJECT"

    return score, classification, components, reasons


def peer_channel_id(message: Any) -> Optional[int]:
    peer = safe_attr(message, "peer_id")
    if peer is None:
        return None
    channel_id = safe_attr(peer, "channel_id")
    if channel_id is None:
        return None
    try:
        return int(channel_id)
    except (TypeError, ValueError):
        return None


def build_chat_lookup(chats: List[Any]) -> Dict[int, Any]:
    result: Dict[int, Any] = {}
    for chat in chats or []:
        chat_id = safe_attr(chat, "id")
        if chat_id is None:
            continue
        try:
            result[int(chat_id)] = chat
        except (TypeError, ValueError):
            continue
    return result


async def quota_status(client: TelegramClient, query: str) -> Dict[str, Any]:
    result = await client(CheckSearchPostsFloodRequest(query=query))
    return {
        "query_is_free": bool(safe_attr(result, "query_is_free", False)),
        "total_daily": safe_attr(result, "total_daily"),
        "remains": safe_attr(result, "remains"),
        "wait_till": safe_attr(result, "wait_till"),
        "stars_amount": safe_attr(result, "stars_amount"),
    }


def search_allowed_without_payment(status: Dict[str, Any]) -> bool:
    if status.get("query_is_free"):
        return True

    remains = status.get("remains")
    if remains is None:
        return False

    try:
        return int(remains) > 0
    except (TypeError, ValueError):
        return False


async def search_public_posts(
    client: TelegramClient,
    query: str,
    limit: int,
) -> Any:
    return await client(
        SearchPostsRequest(
            hashtag=None,
            query=query,
            offset_rate=0,
            offset_peer=InputPeerEmpty(),
            offset_id=0,
            limit=limit,
            allow_paid_stars=None,
        )
    )


async def run_discovery() -> Dict[str, Any]:
    api_id_raw = str(os.getenv("TELEGRAM_API_ID", "")).strip()
    api_hash = str(os.getenv("TELEGRAM_API_HASH", "")).strip()
    session_string = str(os.getenv("TELEGRAM_SESSION", "")).strip()

    if not api_id_raw or not api_hash or not session_string:
        raise RuntimeError(
            "Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_SESSION."
        )

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_API_ID must be an integer.") from exc

    max_queries = env_int(
        "TELEGRAM_DISCOVERY_V2_MAX_QUERIES",
        DEFAULT_MAX_QUERIES,
        minimum=1,
        maximum=len(DISCOVERY_QUERIES),
    )
    results_per_query = env_int(
        "TELEGRAM_DISCOVERY_V2_RESULTS_PER_QUERY",
        DEFAULT_RESULTS_PER_QUERY,
        minimum=1,
        maximum=100,
    )
    sample_limit = env_int(
        "TELEGRAM_DISCOVERY_V2_SAMPLE_POSTS_PER_CHANNEL",
        DEFAULT_SAMPLE_POSTS_PER_CHANNEL,
        minimum=1,
        maximum=10,
    )

    query_plan = DISCOVERY_QUERIES[:max_queries]
    filters = FilterBundle()
    started_at = utcnow_iso()

    channels: Dict[int, Dict[str, Any]] = {}
    seen_posts: Set[Tuple[int, int]] = set()
    query_audit: List[Dict[str, Any]] = []

    summary = {
        "queries_planned": len(query_plan),
        "queries_completed": 0,
        "queries_skipped_no_free_quota": 0,
        "queries_failed": 0,
        "raw_messages_returned": 0,
        "unique_public_channel_posts": 0,
        "unique_channels": 0,
        "paid_search_used": False,
    }

    client = TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
    )

    await client.connect()

    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized.")

        for query_def in query_plan:
            query_text = query_def["query"]
            query_record = {
                **query_def,
                "quota_before": None,
                "status": None,
                "messages_returned": 0,
                "public_channel_posts": 0,
                "error": None,
            }

            try:
                quota = await quota_status(client, query_text)
                query_record["quota_before"] = quota

                if not search_allowed_without_payment(quota):
                    query_record["status"] = "SKIPPED_NO_FREE_QUOTA"
                    summary["queries_skipped_no_free_quota"] += 1
                    query_audit.append(query_record)
                    break

                response = await search_public_posts(
                    client=client,
                    query=query_text,
                    limit=results_per_query,
                )

                messages = list(safe_attr(response, "messages", []) or [])
                chats = list(safe_attr(response, "chats", []) or [])
                chat_lookup = build_chat_lookup(chats)

                summary["raw_messages_returned"] += len(messages)
                query_record["messages_returned"] = len(messages)

                local_count = 0

                for message in messages:
                    channel_id = peer_channel_id(message)
                    if channel_id is None:
                        continue

                    chat = chat_lookup.get(channel_id)
                    if chat is None:
                        continue

                    if not (
                        bool(safe_attr(chat, "broadcast", False))
                        or bool(safe_attr(chat, "megagroup", False))
                    ):
                        continue

                    message_id = safe_attr(message, "id")
                    if message_id is None:
                        continue

                    post_key = (channel_id, int(message_id))
                    if post_key in seen_posts:
                        continue

                    text = str(safe_attr(message, "message", "") or "").strip()
                    if not text:
                        continue

                    seen_posts.add(post_key)
                    local_count += 1

                    analysis = filters.analyze(text)

                    row = channels.get(channel_id)
                    if row is None:
                        username = safe_attr(chat, "username")
                        row = {
                            "channel_id": channel_id,
                            "username": username,
                            "title": safe_attr(chat, "title"),
                            "url": (
                                f"https://t.me/{username}"
                                if username
                                else None
                            ),
                            "broadcast": bool(
                                safe_attr(chat, "broadcast", False)
                            ),
                            "megagroup": bool(
                                safe_attr(chat, "megagroup", False)
                            ),
                            "verified": bool(
                                safe_attr(chat, "verified", False)
                            ),
                            "query_ids": set(),
                            "query_families": set(),
                            "languages": set(),
                            "posts_matched": 0,
                            "migration_relevant_posts": 0,
                            "geographic_posts": 0,
                            "operational_posts": 0,
                            "early_warning_posts": 0,
                            "precursor_posts": 0,
                            "useful_posts": 0,
                            "noise_posts": 0,
                            "inaccessible_posts": 0,
                            "sample_posts": [],
                        }
                        channels[channel_id] = row

                    row["query_ids"].add(query_def["id"])
                    row["query_families"].add(query_def["family"])
                    row["languages"].add(query_def["language"])
                    row["posts_matched"] += 1

                    if analysis["migration_relevance"]:
                        row["migration_relevant_posts"] += 1
                    if analysis["geographic_specificity"]:
                        row["geographic_posts"] += 1
                    if analysis["operational"]:
                        row["operational_posts"] += 1
                    if analysis["early_warning"]:
                        row["early_warning_posts"] += 1
                    if analysis["precursor"]:
                        row["precursor_posts"] += 1
                    if analysis["noise"]:
                        row["noise_posts"] += 1
                    if analysis["inaccessible_placeholder"]:
                        row["inaccessible_posts"] += 1

                    if (
                        analysis["operational"]
                        or analysis["early_warning"]
                        or analysis["precursor"]
                    ):
                        row["useful_posts"] += 1

                    if len(row["sample_posts"]) < sample_limit:
                        message_date = safe_attr(message, "date")
                        username = row.get("username")
                        post_url = (
                            f"https://t.me/{username}/{message_id}"
                            if username
                            else None
                        )

                        row["sample_posts"].append(
                            {
                                "message_id": message_id,
                                "published_at": (
                                    message_date.isoformat()
                                    if message_date
                                    else None
                                ),
                                "query_id": query_def["id"],
                                "query_family": query_def["family"],
                                "text": compact_text(text),
                                "url": post_url,
                                "analysis": analysis,
                            }
                        )

                query_record["public_channel_posts"] = local_count
                query_record["status"] = "COMPLETED"
                summary["queries_completed"] += 1
                query_audit.append(query_record)

            except Exception as exc:
                query_record["status"] = "FAILED"
                query_record["error"] = f"{type(exc).__name__}: {exc}"
                summary["queries_failed"] += 1
                query_audit.append(query_record)

        final_channels: List[Dict[str, Any]] = []

        for row in channels.values():
            score, classification, components, reasons = score_source(row)

            row["source_score"] = score
            row["classification"] = classification
            row["score_components"] = components
            row["classification_reasons"] = reasons

            row["query_ids"] = sorted(row["query_ids"])
            row["query_families"] = sorted(row["query_families"])
            row["languages"] = sorted(row["languages"])

            final_channels.append(row)

        final_channels.sort(
            key=lambda item: (
                item["source_score"],
                item["precursor_posts"],
                item["operational_posts"],
                item["early_warning_posts"],
                item["useful_posts"],
            ),
            reverse=True,
        )

        summary["unique_public_channel_posts"] = len(seen_posts)
        summary["unique_channels"] = len(final_channels)

        for label in ("HIGH_VALUE", "WATCH", "CANDIDATE", "REJECT"):
            summary[label.lower() + "_channels"] = sum(
                1
                for item in final_channels
                if item["classification"] == label
            )

        summary["channels_with_operational_posts"] = sum(
            1 for item in final_channels if item["operational_posts"] > 0
        )
        summary["channels_with_early_warning_posts"] = sum(
            1 for item in final_channels if item["early_warning_posts"] > 0
        )
        summary["channels_with_precursor_posts"] = sum(
            1 for item in final_channels if item["precursor_posts"] > 0
        )

        return {
            "schema_version": "2.0",
            "run_type": "TELEGRAM_SOURCE_DISCOVERY_V2_DIAGNOSTIC",
            "generated_at": utcnow_iso(),
            "started_at": started_at,
            "safety": {
                "database_writes": False,
                "private_chats_accessed": False,
                "channel_membership_changes": False,
                "production_collector_modified": False,
                "paid_search_allowed": False,
                "paid_search_used": False,
            },
            "configuration": {
                "max_queries": max_queries,
                "results_per_query": results_per_query,
                "sample_posts_per_channel": sample_limit,
                "query_plan": query_plan,
                "filter_availability": filters.availability(),
            },
            "summary": summary,
            "query_audit": query_audit,
            "channels": final_channels,
        }

    finally:
        await client.disconnect()


def main() -> int:
    print("===================================")
    print(" TELEGRAM SOURCE DISCOVERY V2")
    print("===================================")
    print("Production collector: UNCHANGED")
    print("Database writes: DISABLED")
    print("Private chats/groups: NOT ACCESSED")
    print("Paid Telegram Stars: DISABLED")

    payload = asyncio.run(run_discovery())

    OUTPUT_PATH.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = payload["summary"]

    print("-----------------------------------")
    print("Discovery V2 complete.")
    print("Queries completed:", summary["queries_completed"])
    print("Unique public posts:", summary["unique_public_channel_posts"])
    print("Unique channels:", summary["unique_channels"])
    print("High value:", summary.get("high_value_channels", 0))
    print("Watch:", summary.get("watch_channels", 0))
    print("Candidate:", summary.get("candidate_channels", 0))
    print("Reject:", summary.get("reject_channels", 0))
    print(
        "Channels with precursors:",
        summary.get("channels_with_precursor_posts", 0),
    )
    print("JSON:", OUTPUT_PATH.name)

    if payload["channels"]:
        print("-----------------------------------")
        print("Top source candidates:")

        for item in payload["channels"][:15]:
            name = (
                f"@{item['username']}"
                if item.get("username")
                else item.get("title")
                or str(item["channel_id"])
            )

            print(
                f"{name} | score={item['source_score']} | "
                f"{item['classification']} | posts={item['posts_matched']} | "
                f"op={item['operational_posts']} | "
                f"early={item['early_warning_posts']} | "
                f"precursor={item['precursor_posts']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
