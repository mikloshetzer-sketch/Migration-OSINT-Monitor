"""
Migration OSINT Monitor

File:
event_group_engine.py

Description:
Event Group Engine.

Creates and maintains persistent real-world event groups from
correlated operational source events.

Responsibilities:
- create a new EventGroup for a new operational event
- attach source posts to an EventGroup
- find the EventGroup of a correlated source
- bootstrap an EventGroup when an older correlated database event
  does not yet belong to a group
- update source count
- update source types
- update first_seen / last_seen
- update confidence and representative text

The existing Post model remains unchanged.
"""

import json

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from database.models import (
    Post,
    EventGroup,
    EventGroupSource,
)

from database.event_group_repository import (
    EventGroupRepository,
)


class EventGroupEngine:
    """
    Persistent event-group management layer.
    """

    def __init__(self):
        self.repository = EventGroupRepository()

    def process(
        self,
        session,
        event: Dict[str, Any],
        correlation_result: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Dict[str, Any]:
        """
        Processes one operational event.

        Behaviour:

        NEW EVENT
            -> creates a new EventGroup
            -> links the source to the group

        CORRELATED EVENT
            -> finds the EventGroup belonging to
               the matched source
            -> attaches the new source
            -> updates the EventGroup

        If the matched historical source predates the
        EventGroup system and has no group yet, the engine
        automatically creates a group for that matched event
        before attaching the new source.

        Returns:
            {
                "event_group_id": int | None,
                "group_action": str,
                "source_linked": bool,
                "source_count": int,
                "correlation_score": float | None
            }
        """

        if correlation_result:
            return self._process_correlated_event(
                session=session,
                event=event,
                correlation_result=correlation_result,
            )

        return self._process_new_event(
            session=session,
            event=event,
        )

    def _process_new_event(
        self,
        *,
        session,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Creates a new EventGroup for an event
        that did not correlate with an existing event.
        """

        existing_group = (
            self._find_group_by_source_event(
                session=session,
                event=event,
            )
        )

        if existing_group:
            return {
                "event_group_id": existing_group.id,
                "group_action": "EXISTING_GROUP",
                "source_linked": False,
                "source_count": (
                    existing_group.source_count
                    or 0
                ),
                "correlation_score": None,
            }

        group = self._create_group(
            session=session,
            event=event,
        )

        source_linked = (
            self._attach_source(
                session=session,
                group=group,
                event=event,
                correlation_score=None,
            )
        )

        self._refresh_group_statistics(
            session=session,
            group=group,
        )

        return {
            "event_group_id": group.id,
            "group_action": "NEW_GROUP",
            "source_linked": source_linked,
            "source_count": (
                group.source_count
                or 0
            ),
            "correlation_score": None,
        }

    def _process_correlated_event(
        self,
        *,
        session,
        event: Dict[str, Any],
        correlation_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Adds an event to the EventGroup of its
        correlated source.
        """

        matched_event = (
            correlation_result.get(
                "event"
            )
            or {}
        )

        correlation_score = (
            correlation_result.get(
                "correlation_score"
            )
        )

        group = self._find_group_by_source_event(
            session=session,
            event=matched_event,
        )

        group_action = "UPDATED_GROUP"

        if group is None:
            group = self._create_group(
                session=session,
                event=matched_event,
            )

            self._attach_source(
                session=session,
                group=group,
                event=matched_event,
                correlation_score=None,
            )

            group_action = (
                "BOOTSTRAPPED_GROUP"
            )

        already_linked = (
            self._source_already_linked(
                session=session,
                group_id=group.id,
                event=event,
            )
        )

        if already_linked:
            self._refresh_group_statistics(
                session=session,
                group=group,
            )

            return {
                "event_group_id": group.id,
                "group_action": (
                    "EXISTING_SOURCE"
                ),
                "source_linked": False,
                "source_count": (
                    group.source_count
                    or 0
                ),
                "correlation_score": (
                    correlation_score
                ),
            }

        source_linked = self._attach_source(
            session=session,
            group=group,
            event=event,
            correlation_score=correlation_score,
        )

        self._update_group_content(
            group=group,
            new_event=event,
        )

        self._refresh_group_statistics(
            session=session,
            group=group,
        )

        return {
            "event_group_id": group.id,
            "group_action": group_action,
            "source_linked": source_linked,
            "source_count": (
                group.source_count
                or 0
            ),
            "correlation_score": (
                correlation_score
            ),
        }

    def _create_group(
        self,
        *,
        session,
        event: Dict[str, Any],
    ) -> EventGroup:
        """
        Creates and persists a new EventGroup.
        """

        payload = (
            self.repository
            .build_new_group_payload(
                event
            )
        )

        now = datetime.utcnow()

        source_types = (
            payload.get(
                "source_types"
            )
            or []
        )

        group = EventGroup(
            event_type=(
                payload.get(
                    "event_type"
                )
                or "UNKNOWN_EVENT"
            ),
            title=payload.get(
                "title"
            ),
            representative_text=(
                payload.get(
                    "representative_text"
                )
            ),
            primary_region=payload.get(
                "primary_region"
            ),
            primary_location=payload.get(
                "primary_location"
            ),
            country=payload.get(
                "country"
            ),
            latitude=payload.get(
                "latitude"
            ),
            longitude=payload.get(
                "longitude"
            ),
            first_seen=self._make_naive_datetime(
                payload.get(
                    "first_seen"
                )
            ),
            last_seen=self._make_naive_datetime(
                payload.get(
                    "last_seen"
                )
            ),
            source_count=0,
            source_types=self._serialize_source_types(
                source_types
            ),
            status=(
                payload.get(
                    "status"
                )
                or "ACTIVE"
            ),
            confidence=payload.get(
                "confidence"
            ),
            created_at=now,
            updated_at=now,
        )

        session.add(group)
        session.commit()
        session.refresh(group)

        return group

    def _attach_source(
        self,
        *,
        session,
        group: EventGroup,
        event: Dict[str, Any],
        correlation_score: Optional[
            float
        ],
    ) -> bool:
        """
        Links one source event to an EventGroup.

        Duplicate links are ignored safely.
        """

        if self._source_already_linked(
            session=session,
            group_id=group.id,
            event=event,
        ):
            return False

        source = event.get(
            "source"
        )

        source_post_id = event.get(
            "source_post_id"
        )

        post = self._find_post(
            session=session,
            source=source,
            source_post_id=source_post_id,
        )

        payload = (
            self.repository
            .build_source_link_payload(
                event_group_id=group.id,
                event=event,
                correlation_score=correlation_score,
            )
        )

        link = EventGroupSource(
            event_group_id=group.id,
            post_id=(
                post.id
                if post
                else None
            ),
            source=payload.get(
                "source"
            ),
            source_post_id=str(
                payload.get(
                    "source_post_id"
                )
                or ""
            ),
            author=payload.get(
                "author"
            ),
            published_at=(
                self._make_naive_datetime(
                    payload.get(
                        "published_at"
                    )
                )
            ),
            event_type=payload.get(
                "event_type"
            ),
            text=payload.get(
                "text"
            ),
            source_url=payload.get(
                "source_url"
            ),
            correlation_score=(
                payload.get(
                    "correlation_score"
                )
            ),
            created_at=datetime.utcnow(),
        )

        try:
            session.add(link)
            session.commit()
            session.refresh(link)

            return True

        except IntegrityError:
            session.rollback()

            return False

    def _find_group_by_source_event(
        self,
        *,
        session,
        event: Dict[str, Any],
    ) -> Optional[EventGroup]:
        """
        Finds an EventGroup using a source event.
        """

        source = event.get(
            "source"
        )

        source_post_id = event.get(
            "source_post_id"
        )

        if not source or not source_post_id:
            return None

        statement = (
            select(EventGroup)
            .join(
                EventGroupSource,
                EventGroupSource.event_group_id
                == EventGroup.id,
            )
            .where(
                EventGroupSource.source
                == source
            )
            .where(
                EventGroupSource.source_post_id
                == str(source_post_id)
            )
            .limit(1)
        )

        return (
            session.execute(
                statement
            )
            .scalars()
            .first()
        )

    def _source_already_linked(
        self,
        *,
        session,
        group_id: int,
        event: Dict[str, Any],
    ) -> bool:
        """
        Checks whether this exact source post
        already belongs to the EventGroup.
        """

        source = event.get(
            "source"
        )

        source_post_id = event.get(
            "source_post_id"
        )

        if not source or not source_post_id:
            return False

        statement = (
            select(
                EventGroupSource.id
            )
            .where(
                EventGroupSource.event_group_id
                == group_id
            )
            .where(
                EventGroupSource.source
                == source
            )
            .where(
                EventGroupSource.source_post_id
                == str(source_post_id)
            )
            .limit(1)
        )

        result = session.execute(
            statement
        ).scalar_one_or_none()

        return result is not None

    def _find_post(
        self,
        *,
        session,
        source,
        source_post_id,
    ) -> Optional[Post]:
        """
        Finds the corresponding existing Post record.

        EventGroupSource can still exist without a Post FK,
        which will later allow new collectors to be integrated
        safely.
        """

        if not source or not source_post_id:
            return None

        statement = (
            select(Post)
            .where(
                Post.source == source
            )
            .where(
                Post.post_id
                == str(source_post_id)
            )
            .limit(1)
        )

        return (
            session.execute(
                statement
            )
            .scalars()
            .first()
        )

    def _update_group_content(
        self,
        *,
        group: EventGroup,
        new_event: Dict[str, Any],
    ):
        """
        Updates EventGroup content fields using a new
        correlated source.
        """

        existing_group = {
            "first_seen": (
                group.first_seen
            ),
            "last_seen": (
                group.last_seen
            ),
            "source_count": (
                group.source_count
            ),
            "source_types": (
                self._deserialize_source_types(
                    group.source_types
                )
            ),
            "confidence": (
                group.confidence
            ),
            "representative_text": (
                group.representative_text
            ),
        }

        payload = (
            self.repository
            .build_group_update_payload(
                existing_group=existing_group,
                new_event=new_event,
            )
        )

        group.first_seen = (
            self._make_naive_datetime(
                payload.get(
                    "first_seen"
                )
            )
        )

        group.last_seen = (
            self._make_naive_datetime(
                payload.get(
                    "last_seen"
                )
            )
        )

        group.confidence = (
            payload.get(
                "confidence"
            )
        )

        group.representative_text = (
            payload.get(
                "representative_text"
            )
        )

        group.status = (
            payload.get(
                "status"
            )
            or "ACTIVE"
        )

        group.updated_at = (
            datetime.utcnow()
        )

    def _refresh_group_statistics(
        self,
        *,
        session,
        group: EventGroup,
    ):
        """
        Recalculates EventGroup statistics from
        the actual linked EventGroupSource rows.

        This avoids source_count drift.
        """

        count_statement = (
            select(
                func.count(
                    EventGroupSource.id
                )
            )
            .where(
                EventGroupSource.event_group_id
                == group.id
            )
        )

        source_count = (
            session.execute(
                count_statement
            )
            .scalar_one()
        )

        source_statement = (
            select(
                EventGroupSource.source
            )
            .where(
                EventGroupSource.event_group_id
                == group.id
            )
        )

        source_values = (
            session.execute(
                source_statement
            )
            .scalars()
            .all()
        )

        source_types = []

        for source in source_values:
            if (
                source
                and source
                not in source_types
            ):
                source_types.append(
                    source
                )

        group.source_count = (
            int(source_count or 0)
        )

        group.source_types = (
            self._serialize_source_types(
                source_types
            )
        )

        time_statement = (
            select(
                EventGroupSource.published_at
            )
            .where(
                EventGroupSource.event_group_id
                == group.id
            )
            .where(
                EventGroupSource.published_at
                .is_not(None)
            )
        )

        published_times = (
            session.execute(
                time_statement
            )
            .scalars()
            .all()
        )

        if published_times:
            group.first_seen = min(
                published_times
            )

            group.last_seen = max(
                published_times
            )

        group.updated_at = (
            datetime.utcnow()
        )

        session.add(group)
        session.commit()
        session.refresh(group)

    def _serialize_source_types(
        self,
        source_types,
    ) -> str:
        """
        Stores source types as JSON text.
        """

        unique_sources = []

        for source in (
            source_types
            or []
        ):
            if (
                source
                and source
                not in unique_sources
            ):
                unique_sources.append(
                    source
                )

        return json.dumps(
            unique_sources,
            ensure_ascii=False,
        )

    def _deserialize_source_types(
        self,
        value,
    ):
        """
        Reads source types from JSON text.
        """

        if not value:
            return []

        try:
            result = json.loads(
                value
            )

            if isinstance(
                result,
                list,
            ):
                return result

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            pass

        return []

    def _make_naive_datetime(
        self,
        value,
    ) -> Optional[datetime]:
        """
        Converts timezone-aware values into naive UTC
        datetimes for compatibility with the current
        SQLite DateTime columns.
        """

        if value is None:
            return None

        if not isinstance(
            value,
            datetime,
        ):
            try:
                value = datetime.fromisoformat(
                    str(value).replace(
                        "Z",
                        "+00:00",
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                return None

        if value.tzinfo is not None:
            return (
                value
                .astimezone()
                .replace(
                    tzinfo=None
                )
            )

        return value
