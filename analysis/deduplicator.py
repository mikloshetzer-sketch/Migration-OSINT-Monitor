"""
Migration OSINT Monitor

File:
deduplicator.py

Description:
Provides duplicate detection helpers for collected social media posts.
"""

from typing import Optional

from sqlalchemy.orm import Session

from database.models import Post


class Deduplicator:
    """
    Checks whether a post already exists in the history database.
    """

    def is_duplicate(
        self,
        session: Session,
        source: str,
        post_id: str,
    ) -> bool:
        """
        Returns True if the same source + post_id combination
        already exists in the database.
        """

        existing_post: Optional[Post] = (
            session.query(Post)
            .filter(
                Post.source == source,
                Post.post_id == post_id,
            )
            .first()
        )

        return existing_post is not None
