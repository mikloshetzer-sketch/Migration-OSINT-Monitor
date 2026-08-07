"""
Migration OSINT Monitor

File:
repository.py

Description:
Database repository functions for storing and retrieving collected posts.
"""

from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database.models import Post


class PostRepository:
    """
    Handles database operations for collected posts.
    """

    def save_post(
        self,
        session: Session,
        post: Post,
    ) -> bool:
        """
        Saves a post to the database.

        Returns:
            True if the post was saved successfully.
            False if the post already exists.
        """
        try:
            session.add(post)
            session.commit()
            session.refresh(post)
            return True

        except IntegrityError:
            session.rollback()
            return False

    def get_by_source_and_post_id(
        self,
        session: Session,
        source: str,
        post_id: str,
    ) -> Optional[Post]:
        """
        Returns a post by source and original post ID.
        """
        return (
            session.query(Post)
            .filter(
                Post.source == source,
                Post.post_id == post_id,
            )
            .first()
        )
