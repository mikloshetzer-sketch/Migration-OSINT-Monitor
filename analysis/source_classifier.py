
"""
Migration OSINT Monitor
Source Intelligence - Publisher Classification

Classifies the publisher of an already collected post.

No network requests.
No database writes.
No modifications to existing event classification.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse


PRIVATE_PERSON = "PRIVATE_PERSON"
GOVERNMENT = "GOVERNMENT"
ORGANIZATION = "ORGANIZATION"
MEDIA = "MEDIA"
UNKNOWN = "UNKNOWN"

VALID_CATEGORIES = {
    PRIVATE_PERSON,
    GOVERNMENT,
    ORGANIZATION,
    MEDIA,
    UNKNOWN,
}


def normalize_author(value: Any) -> str:
    """Normalize a publisher name for registry matching."""
    if value is None:
        return ""

    value = str(value).strip().casefold()
    value = re.sub(r"\s+", " ", value)

    return value.lstrip("@")


def normalize_platform(value: Any) -> str:
    """Normalize the source platform name."""
    platform = str(value or "").strip().upper()

    aliases = {
        "TWITTER": "X",
        "X/TWITTER": "X",
        "TG": "TELEGRAM",
    }

    return aliases.get(platform, platform)


def normalize_category(value: Any) -> str:
    """Accept only supported publisher categories."""
    category = str(value or "").strip().upper()

    return category if category in VALID_CATEGORIES else UNKNOWN


def get_post_author(post: Mapping[str, Any]) -> str:
    """Read the existing author field without modifying it."""
    return str(post.get("author") or "").strip()


def get_post_platform(post: Mapping[str, Any]) -> str:
    """Read the existing source field."""
    return normalize_platform(post.get("source"))


def get_post_url(post: Mapping[str, Any]) -> str:
    """Read the existing post URL."""
    return str(
        post.get("url")
        or post.get("source_url")
        or ""
    ).strip()


def get_post_id(post: Mapping[str, Any]) -> str:
    """Read the original platform post identifier."""
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
    """
    Registry structure:

    {
        "TELEGRAM": {
            "example_channel": {
                "category": "MEDIA",
                "name": "Example Channel"
            }
        }
    }

    Registry matches are platform-specific.
    """

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
            category = normalize_category(
                record.get("category")
            )
            display_name = str(
                record.get("name") or author
            )

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
    """
    Classify the publisher of an existing collected post.

    IMPORTANT:
    - A platform is not a publisher category.
    - A personal-looking username is not proof of identity.
    - A .gov domain in a shared link does not prove that the
      publisher is a government account.
    - Unknown publishers remain UNKNOWN.
    """

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
    """Classify multiple existing posts."""
    return [
        classify_source(post, registry=registry)
        for post in posts
    ]


def summarize_categories(
    classifications: list[Mapping[str, Any]],
) -> Dict[str, int]:
    """Count posts by publisher category."""

    summary = {
        PRIVATE_PERSON: 0,
        GOVERNMENT: 0,
        ORGANIZATION: 0,
        MEDIA: 0,
        UNKNOWN: 0,
    }

    for item in classifications:
        category = normalize_category(
            item.get("publisher_category")
        )

        summary[category] += 1

    return summary
