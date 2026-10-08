
"""
Migration OSINT Monitor
Source Intelligence - Publisher Classification

Read-only classification of previously collected posts.
No network requests, database writes or event classification changes.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional


MEDIA = "MEDIA"
GOVERNMENT = "GOVERNMENT"
NGO = "NGO"
POLITICAL = "POLITICAL"
EXPERT = "EXPERT"
COMMENTATOR = "COMMENTATOR"
COMMUNITY = "COMMUNITY"
INDIVIDUAL = "INDIVIDUAL"
UNKNOWN = "UNKNOWN"

VALID_CATEGORIES = {
    MEDIA,
    GOVERNMENT,
    NGO,
    POLITICAL,
    EXPERT,
    COMMENTATOR,
    COMMUNITY,
    INDIVIDUAL,
    UNKNOWN,
}

# Compatibility with older registry categories.
LEGACY_CATEGORIES = {
    "PRIVATE_PERSON": INDIVIDUAL,
    "ORGANIZATION": COMMUNITY,
}


def normalize_author(value: Any) -> str:
    if value is None:
        return ""

    value = str(value).strip().casefold()
    value = re.sub(r"\s+", " ", value)
    return value.lstrip("@")


def normalize_platform(value: Any) -> str:
    platform = str(value or "").strip().upper()

    aliases = {
        "TWITTER": "X",
        "X/TWITTER": "X",
        "TG": "TELEGRAM",
    }

    return aliases.get(platform, platform)


def normalize_category(value: Any) -> str:
    category = str(value or "").strip().upper()

    if category in VALID_CATEGORIES:
        return category

    return LEGACY_CATEGORIES.get(category, UNKNOWN)


def get_post_author(post: Mapping[str, Any]) -> str:
    return str(post.get("author") or "").strip()


def get_post_platform(post: Mapping[str, Any]) -> str:
    return normalize_platform(post.get("source"))


def get_post_url(post: Mapping[str, Any]) -> str:
    return str(
        post.get("url")
        or post.get("source_url")
        or ""
    ).strip()


def get_post_id(post: Mapping[str, Any]) -> str:
    return str(
        post.get("source_post_id")
        or post.get("post_id")
        or ""
    ).strip()


def _lookup_registry(
    registry: Mapping[str, Any],
    platform: str,
    author: str,
) -> Optional[Dict[str, Any]]:

    normalized_author = normalize_author(author)

    if not normalized_author:
        return None

    platform_registry = registry.get(platform, {})

    if not isinstance(platform_registry, Mapping):
        return None

    for registered_author, record in platform_registry.items():
        if normalize_author(registered_author) != normalized_author:
            continue

        if isinstance(record, str):
            category = normalize_category(record)
            display_name = author

        elif isinstance(record, Mapping):
            category = normalize_category(record.get("category"))
            display_name = str(record.get("name") or author)

        else:
            continue

        if category == UNKNOWN:
            return None

        return {
            "category": category,
            "publisher_name": display_name,
            "classification_method": "VERIFIED_REGISTRY",
            "classification_confidence": 1.0,
        }

    return None


def classify_source(
    post: Mapping[str, Any],
    registry: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:

    platform = get_post_platform(post)
    author = get_post_author(post)

    result = {
        "source": platform,
        "source_post_id": get_post_id(post),
        "author": author,
        "url": get_post_url(post),
        "publisher_category": UNKNOWN,
        "publisher_name": author or None,
        "classification_method": "INSUFFICIENT_EVIDENCE",
        "classification_confidence": 0.0,
    }

    if not author or not platform:
        return result

    if registry:
        match = _lookup_registry(
            registry=registry,
            platform=platform,
            author=author,
        )

        if match:
            result.update({
                "publisher_category": match["category"],
                "publisher_name": match["publisher_name"],
                "classification_method": match[
                    "classification_method"
                ],
                "classification_confidence": match[
                    "classification_confidence"
                ],
            })

    return result


def classify_posts(
    posts: list[Mapping[str, Any]],
    registry: Optional[Mapping[str, Any]] = None,
) -> list[Dict[str, Any]]:

    return [
        classify_source(post, registry=registry)
        for post in posts
    ]


def summarize_categories(
    classifications: list[Mapping[str, Any]],
) -> Dict[str, int]:

    summary = {
        category: 0
        for category in (
            MEDIA,
            GOVERNMENT,
            NGO,
            POLITICAL,
            EXPERT,
            COMMENTATOR,
            COMMUNITY,
            INDIVIDUAL,
            UNKNOWN,
        )
    }

    for item in classifications:
        category = normalize_category(
            item.get("publisher_category")
        )
        summary[category] += 1

    return summary

