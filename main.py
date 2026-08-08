"""
Migration OSINT Monitor

File:
main.py

Description:
Application entry point using:

- X + Reddit + Mastodon Collectors
- Query Engine
- Noise Filter
- Operational Event Filter
- Signal Classification
- Influence Signal Detection
- Location Extraction
- Time Extraction
- Region Resolution
- Database-backed Event Correlation
- Persistent Event Groups / Clusters
- SQLite Event Storage

The correlation engine compares new operational events against:
1. recent operational events already stored in SQLite
2. operational events detected during the current run

The Event Group Engine then:
- creates new persistent event groups
- attaches correlated source events to existing groups
- maintains source counts and event-group history
"""

import json
import re
import uuid
from datetime import datetime, timezone

from dateutil import parser as date_parser

from collectors.x_collector import XCollector
from collectors.reddit_collector import RedditCollector
from collectors.mastodon_collector import MastodonCollector

from analysis.keyword_filter import KeywordFilter
from analysis.classifier import SignalClassifier
from analysis.influence_signal_detector import InfluenceSignalDetector
from analysis.location_extractor import LocationExtractor
from analysis.time_extractor import TimeExtractor
from analysis.scoring import RelevanceScorer
from analysis.event_extractor import EventExtractor
from analysis.query_engine import QueryEngine
from analysis.noise_filter import NoiseFilter
from analysis.operational_event_filter import OperationalEventFilter
from analysis.event_correlator import EventCorrelator
from analysis.region_resolver import RegionResolver
from analysis.event_group_engine import EventGroupEngine

from database.init_db import initialize_database
from database.database import get_session
from database.event_repository import EventRepository
from database.correlation_repository import CorrelationRepository
from database.models import MonitorRun, CollectedPost, InfluenceSignal



def build_reddit_query(query_text):
    """
    Converts an X-style query into a simpler Reddit RSS search query.

    X-specific operators are removed while normal search terms, quoted
    phrases, parentheses and Boolean OR expressions are preserved.
    """

    query = str(query_text or "").strip()

    if not query:
        return ""

    # Remove common X-only search operators.
    query = re.sub(
        r"(?<!\S)-?is:[^\s()]+",
        " ",
        query,
        flags=re.IGNORECASE,
    )

    query = re.sub(
        r"(?<!\S)lang:[^\s()]+",
        " ",
        query,
        flags=re.IGNORECASE,
    )

    query = re.sub(
        r"(?<!\S)(?:from|to|has|url|context|conversation_id):[^\s()]+",
        " ",
        query,
        flags=re.IGNORECASE,
    )

    query = re.sub(
        r"\s+",
        " ",
        query,
    ).strip()

    # Avoid dangling Boolean operators after operator removal.
    query = re.sub(
        r"^(?:AND|OR)\s+",
        "",
        query,
        flags=re.IGNORECASE,
    )

    query = re.sub(
        r"\s+(?:AND|OR)$",
        "",
        query,
        flags=re.IGNORECASE,
    )

    return query.strip()



def apply_region_resolution(
    event,
    region_resolver,
):
    """
    Adds normalized region information to an event.
    """

    region_result = region_resolver.resolve(
        event
    )

    event["primary_region"] = (
        region_result.get(
            "primary_region"
        )
    )

    event["matched_regions"] = (
        region_result.get(
            "matched_regions",
            [],
        )
    )

    event["region_names"] = (
        region_result.get(
            "region_names",
            [],
        )
    )

    event["matched_countries"] = (
        region_result.get(
            "matched_countries",
            [],
        )
    )

    event["matched_region_terms"] = (
        region_result.get(
            "matched_region_terms",
            [],
        )
    )

    event["region_confidence"] = (
        region_result.get(
            "confidence"
        )
    )

    return event


def analyze_post(
    post,
    keyword_filter,
    classifier,
    location_extractor,
    time_extractor,
    scorer,
    event_extractor,
    region_resolver,
):
    """
    Runs the analytical pipeline for a single post.
    """

    text = post.get(
        "text",
        "",
    )

    has_migration_keyword = (
        keyword_filter.contains_migration_keyword(
            text
        )
    )

    classification = classifier.classify(
        text
    )

    matched_signals = (
        classification.get(
            "matched_signals",
            [],
        )
    )

    locations = (
        location_extractor.extract_locations(
            text
        )
    )

    time_result = time_extractor.extract(
        text=text,
        published_at=post.get("published_at"),
    )

    score_result = scorer.calculate_score(
        has_migration_keyword=has_migration_keyword,
        location_count=len(locations),
        has_time_reference=(
            time_result is not None
        ),
        has_movement_signal=(
            "ROUTE_INFORMATION"
            in matched_signals

            or "DEPARTURE_SIGNAL"
            in matched_signals

            or "BORDER_CROSSING"
            in matched_signals

            or "ARRIVAL"
            in matched_signals
        ),
        has_advice_signal=(
            "TRAVEL_ADVICE"
            in matched_signals
        ),
        has_coordination_signal=(
            "COORDINATION"
            in matched_signals
        ),
        has_transport_signal=(
            "TRANSPORT_OFFER"
            in matched_signals
        ),
    )

    event = event_extractor.extract_event(
        post=post,
        classification=classification,
        locations=locations,
        time_result=time_result,
        score_result=score_result,
    )

    event = apply_region_resolution(
        event=event,
        region_resolver=region_resolver,
    )

    return event


def build_correlation_candidates(
    new_event,
    correlation_events,
):
    """
    Removes the exact same source post from the
    correlation candidate set.

    This prevents a previously stored source post
    from matching itself when it is collected again
    during a later workflow run.
    """

    new_source = new_event.get(
        "source"
    )

    new_post_id = str(
        new_event.get(
            "source_post_id"
        )
        or ""
    )

    candidates = []

    for event in correlation_events:
        existing_source = event.get(
            "source"
        )

        existing_post_id = str(
            event.get(
                "source_post_id"
            )
            or ""
        )

        same_source_post = (
            new_post_id
            and existing_post_id
            and new_source == existing_source
            and new_post_id == existing_post_id
        )

        if same_source_post:
            continue

        candidates.append(
            event
        )

    return candidates



def print_influence_signal(
    post,
    influence_result,
):
    """
    Prints a detected migration-related influence signal.

    Influence signals are logged independently from the
    operational event pipeline and do not alter event
    correlation or EventGroup processing.
    """

    print(
        "-----------------------------------"
    )

    print(
        "INFLUENCE SIGNAL"
    )

    print(
        "Primary influence signal: "
        f"{influence_result.get('primary_signal')}"
    )

    print(
        "Matched influence signals: "
        f"{influence_result.get('matched_signals')}"
    )

    print(
        "Matched influence phrases: "
        f"{influence_result.get('matched_phrases')}"
    )

    print(
        "Migration context: "
        f"{influence_result.get('migration_context')}"
    )

    print(
        "Context matches: "
        f"{influence_result.get('context_matches')}"
    )

    print(
        "High-value match: "
        f"{influence_result.get('high_value_match')}"
    )

    print(
        "Influence confidence: "
        f"{influence_result.get('confidence')}"
    )

    print(
        "Author: "
        f"{post.get('author')}"
    )

    print(
        "Published: "
        f"{post.get('published_at')}"
    )

    print(
        "Source: "
        f"{post.get('source')}"
    )

    print(
        "Text: "
        f"{post.get('text')}"
    )

    print(
        "URL: "
        f"{post.get('url')}"
    )


def print_event(
    event,
    saved,
    correlation_result,
    event_group_result,
):
    """
    Prints normalized event, region, correlation,
    EventGroup and database information.
    """

    primary_location = event.get(
        "primary_location"
    )

    print(
        "-----------------------------------"
    )

    print(
        "EVENT"
    )

    print(
        f"Type: "
        f"{event.get('event_type')}"
    )

    print(
        f"Confidence: "
        f"{event.get('event_confidence')}"
    )

    print(
        f"Score: "
        f"{event.get('relevance_score')}"
    )

    print(
        f"Level: "
        f"{event.get('relevance_level')}"
    )

    if primary_location:
        print(
            "Primary location: "
            f"{primary_location.get('name')}, "
            f"{primary_location.get('country')}"
        )

        print(
            "Coordinates: "
            f"{primary_location.get('latitude')}, "
            f"{primary_location.get('longitude')}"
        )

    else:
        print(
            "Primary location: None"
        )

    print(
        "Primary region: "
        f"{event.get('primary_region')}"
    )

    print(
        "Matched regions: "
        f"{event.get('matched_regions')}"
    )

    print(
        "Region names: "
        f"{event.get('region_names')}"
    )

    print(
        "Matched countries: "
        f"{event.get('matched_countries')}"
    )

    print(
        "Matched region terms: "
        f"{event.get('matched_region_terms')}"
    )

    print(
        "Region confidence: "
        f"{event.get('region_confidence')}"
    )

    print(
        "Event time: "
        f"{event.get('event_time_normalized')}"
    )

    print(
        "Time confidence: "
        f"{event.get('event_time_confidence')}"
    )

    print(
        "Matched signals: "
        f"{event.get('matched_signals')}"
    )

    print(
        "Matched phrases: "
        f"{event.get('matched_phrases')}"
    )

    if correlation_result:
        matched_event = (
            correlation_result.get(
                "event"
            )
            or {}
        )

        details = (
            correlation_result.get(
                "correlation_details"
            )
            or {}
        )

        print(
            "Correlation: MATCH"
        )

        print(
            "Correlation score: "
            f"{correlation_result.get('correlation_score')}"
        )

        print(
            "Correlation event type score: "
            f"{details.get('event_type_score')}"
        )

        print(
            "Correlation region score: "
            f"{details.get('region_score')}"
        )

        print(
            "Correlation location score: "
            f"{details.get('location_score')}"
        )

        print(
            "Correlation time score: "
            f"{details.get('time_score')}"
        )

        print(
            "Correlation number score: "
            f"{details.get('number_score')}"
        )

        print(
            "Correlation entity score: "
            f"{details.get('entity_score')}"
        )

        print(
            "Correlation text score: "
            f"{details.get('text_score')}"
        )

        print(
            "Shared regions: "
            f"{details.get('shared_regions')}"
        )

        print(
            "Shared numbers: "
            f"{details.get('shared_numbers')}"
        )

        print(
            "Shared entities: "
            f"{details.get('shared_entities')}"
        )

        print(
            "Shared locations: "
            f"{details.get('shared_locations')}"
        )

        print(
            "Correlated source: "
            f"{matched_event.get('source')}"
        )

        print(
            "Correlated source post: "
            f"{matched_event.get('source_post_id')}"
        )

        print(
            "Correlated event type: "
            f"{matched_event.get('event_type')}"
        )

        print(
            "Correlated published: "
            f"{matched_event.get('published_at')}"
        )

    else:
        print(
            "Correlation: NEW EVENT"
        )

    if event_group_result:
        print(
            "Event group ID: "
            f"{event_group_result.get('event_group_id')}"
        )

        print(
            "Event group action: "
            f"{event_group_result.get('group_action')}"
        )

        print(
            "Event group source linked: "
            f"{event_group_result.get('source_linked')}"
        )

        print(
            "Event group source count: "
            f"{event_group_result.get('source_count')}"
        )

        print(
            "Event group correlation score: "
            f"{event_group_result.get('correlation_score')}"
        )

    else:
        print(
            "Event group: NONE"
        )

    print(
        f"Author: "
        f"{event.get('author')}"
    )

    print(
        f"Published: "
        f"{event.get('published_at')}"
    )

    print(
        f"Language: "
        f"{event.get('language')}"
    )

    print(
        f"Text: "
        f"{event.get('text')}"
    )

    print(
        f"URL: "
        f"{event.get('source_url')}"
    )

    if saved:
        print(
            "Database: SAVED"
        )

    else:
        print(
            "Database: ALREADY EXISTS"
        )



def utcnow():
    """
    Returns a naive UTC datetime compatible with the existing SQLite models.
    """
    return datetime.utcnow()


def normalize_datetime(value):
    """
    Converts collector timestamps into naive UTC datetime objects
    compatible with the existing SQLite DateTime columns.

    Accepts:
    - datetime
    - ISO/RFC3339 strings, including values ending in Z
    - None

    Invalid or empty values return None.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value

    elif isinstance(value, str):
        raw = value.strip()

        if not raw:
            return None

        try:
            parsed = date_parser.parse(raw)
        except (
            ValueError,
            TypeError,
            OverflowError,
        ):
            return None

    else:
        try:
            parsed = date_parser.parse(
                str(value)
            )
        except (
            ValueError,
            TypeError,
            OverflowError,
        ):
            return None

    if parsed.tzinfo is not None:
        parsed = (
            parsed
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

    return parsed


def json_text(value):
    """
    Safely serializes detector lists/dictionaries for Text columns.
    """
    if value is None:
        return None

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        return json.dumps(
            str(value),
            ensure_ascii=False,
        )


def normalize_source_post_id(post):
    """
    Returns the stable source post identifier used by the history tables.
    """
    value = (
        post.get("post_id")
        or post.get("url")
    )

    if value:
        return str(value)

    # Last-resort deterministic fallback for collectors that provide
    # neither a platform ID nor a URL.
    source = str(
        post.get("source")
        or "UNKNOWN"
    ).upper()

    author = str(
        post.get("author")
        or ""
    )

    published = str(
        post.get("published_at")
        or ""
    )

    body = str(
        post.get("text")
        or ""
    )

    return (
        f"fallback:{source}:"
        f"{author}:{published}:{body}"
    )[:255]


def get_or_create_collected_post(
    session,
    post,
    monitor_run,
    query_id=None,
    query_group=None,
    search_query=None,
):
    """
    Persists every unique collected source post.

    Repeated manual runs do not create duplicate rows. Existing records
    receive an updated last-seen timestamp and collection counter.
    """
    source = str(
        post.get("source")
        or "UNKNOWN"
    ).upper()

    source_post_id = normalize_source_post_id(
        post
    )

    now = utcnow()

    record = (
        session.query(CollectedPost)
        .filter(
            CollectedPost.source == source,
            CollectedPost.source_post_id == source_post_id,
        )
        .one_or_none()
    )

    if record is None:
        record = CollectedPost(
            source=source,
            source_post_id=source_post_id,
            author=post.get("author"),
            text=post.get("text") or "",
            language=post.get("language"),
            published_at=normalize_datetime(
                post.get("published_at")
            ),
            url=post.get("url"),
            first_collected_at=now,
            last_collected_at=now,
            collection_count=1,
            first_run_id=monitor_run.id,
            last_run_id=monitor_run.id,
            first_query_id=(
                str(query_id)
                if query_id is not None
                else None
            ),
            last_query_id=(
                str(query_id)
                if query_id is not None
                else None
            ),
            first_query_group=(
                str(query_group)
                if query_group is not None
                else None
            ),
            last_query_group=(
                str(query_group)
                if query_group is not None
                else None
            ),
            last_search_query=search_query,
        )

        session.add(record)
        session.flush()

        return record, True

    record.author = (
        post.get("author")
        or record.author
    )

    record.text = (
        post.get("text")
        or record.text
        or ""
    )

    record.language = (
        post.get("language")
        or record.language
    )

    normalized_published_at = (
        normalize_datetime(
            post.get("published_at")
        )
    )

    record.published_at = (
        normalized_published_at
        or record.published_at
    )

    record.url = (
        post.get("url")
        or record.url
    )

    record.last_collected_at = now
    record.last_run_id = monitor_run.id
    record.last_query_id = (
        str(query_id)
        if query_id is not None
        else record.last_query_id
    )
    record.last_query_group = (
        str(query_group)
        if query_group is not None
        else record.last_query_group
    )
    record.last_search_query = (
        search_query
        or record.last_search_query
    )
    record.collection_count = (
        int(record.collection_count or 0)
        + 1
    )

    session.flush()

    return record, False


def update_collected_post_analysis(
    collected_post,
    *,
    is_noise=None,
    is_operational=None,
    operational_confidence=None,
    influence_detected=None,
):
    """
    Updates the latest analytical state of a CollectedPost without
    affecting the existing operational Post/EventGroup pipeline.
    """
    if collected_post is None:
        return

    if is_noise is not None:
        collected_post.is_noise = bool(
            is_noise
        )

    if is_operational is not None:
        collected_post.is_operational = bool(
            is_operational
        )

    if operational_confidence is not None:
        collected_post.operational_confidence = (
            operational_confidence
        )

    if influence_detected is not None:
        collected_post.influence_detected = bool(
            influence_detected
        )


def infer_influence_priority(
    primary_signal,
    confidence,
):
    """
    Converts detector output into a simple analyst-review priority.
    This does not alter the detector or operational classification.
    """
    signal = str(
        primary_signal
        or ""
    ).upper()

    try:
        confidence_value = float(
            confidence
            or 0.0
        )
    except (TypeError, ValueError):
        confidence_value = 0.0

    high_value_signals = {
        "CROSSING_FACILITATION",
        "RECRUITMENT_COORDINATION",
        "MOBILIZATION_COORDINATION",
        "MOBILIZATION_REPORT",
    }

    medium_value_signals = {
        "DECISION_INFLUENCE",
        "ONLINE_INFLUENCE_REPORT",
        "LEGAL_MIGRATION_SIGNAL",
    }

    if (
        signal in high_value_signals
        and confidence_value >= 0.75
    ):
        return "HIGH"

    if (
        signal in high_value_signals
        or signal in medium_value_signals
        or confidence_value >= 0.65
    ):
        return "MEDIUM"

    return "LOW"


def infer_signal_intent(primary_signal):
    """
    Human-facing intent label used later by the dashboard exporter.
    """
    mapping = {
        "CROSSING_FACILITATION": "EASIER_CROSSING",
        "LEGAL_MIGRATION_SIGNAL": "LEGAL_ACCESS",
        "POLICY_SIGNAL": "POLICY_CHANGE",
        "RECRUITMENT_COORDINATION": "RECRUITMENT_COORDINATION",
        "MOBILIZATION_COORDINATION": "MOBILIZATION_COORDINATION",
        "MOBILIZATION_REPORT": "PLANNED_CROSSING",
        "DECISION_INFLUENCE": "DECISION_INFLUENCE",
        "ONLINE_INFLUENCE_REPORT": "ONLINE_INFLUENCE",
    }

    signal = str(
        primary_signal
        or ""
    ).upper()

    return mapping.get(
        signal,
        signal or None,
    )


def save_influence_signal(
    session,
    *,
    post,
    collected_post,
    influence_result,
    monitor_run,
    location_extractor,
    region_resolver,
):
    """
    Persists one detected influence signal independently from the
    operational event pipeline.

    The same source post + primary signal is updated on later runs
    rather than inserted repeatedly.
    """
    source = str(
        post.get("source")
        or "UNKNOWN"
    ).upper()

    source_post_id = normalize_source_post_id(
        post
    )

    primary_signal = str(
        influence_result.get(
            "primary_signal"
        )
        or "UNKNOWN_INFLUENCE_SIGNAL"
    ).upper()

    now = utcnow()

    locations = (
        location_extractor
        .extract_locations(
            post.get("text") or ""
        )
    )

    primary_location = (
        locations[0]
        if locations
        else None
    )

    location_name = None
    country = None
    latitude = None
    longitude = None

    if isinstance(
        primary_location,
        dict,
    ):
        location_name = (
            primary_location.get("name")
        )

        country = (
            primary_location.get("country")
        )

        latitude = (
            primary_location.get("latitude")
        )

        longitude = (
            primary_location.get("longitude")
        )

    region_event = {
        "text": post.get("text") or "",
        "primary_location": primary_location,
        "locations": locations,
    }

    region_result = (
        region_resolver.resolve(
            region_event
        )
        or {}
    )

    primary_region = (
        region_result.get(
            "primary_region"
        )
    )

    confidence = (
        influence_result.get(
            "confidence"
        )
    )

    record = (
        session.query(InfluenceSignal)
        .filter(
            InfluenceSignal.source == source,
            InfluenceSignal.source_post_id == source_post_id,
            InfluenceSignal.primary_signal == primary_signal,
        )
        .one_or_none()
    )

    if record is None:
        record = InfluenceSignal(
            collected_post_id=(
                collected_post.id
                if collected_post
                else None
            ),
            source=source,
            source_post_id=source_post_id,
            author=post.get("author"),
            language=post.get("language"),
            published_at=normalize_datetime(
                post.get("published_at")
            ),
            text=post.get("text") or "",
            source_url=post.get("url"),
            primary_signal=primary_signal,
            signal_mode=influence_result.get(
                "signal_mode"
            ),
            signal_intent=infer_signal_intent(
                primary_signal
            ),
            priority=infer_influence_priority(
                primary_signal,
                confidence,
            ),
            confidence=confidence,
            score=influence_result.get(
                "score"
            ),
            matched_signals=json_text(
                influence_result.get(
                    "matched_signals"
                )
            ),
            matched_phrases=json_text(
                influence_result.get(
                    "matched_phrases"
                )
            ),
            matched_groups=json_text(
                influence_result.get(
                    "matched_groups"
                )
            ),
            context_matches=json_text(
                influence_result.get(
                    "context_matches"
                )
            ),
            high_value_matches=json_text(
                influence_result.get(
                    "high_value_matches"
                )
                or influence_result.get(
                    "high_value_match"
                )
            ),
            signal_context_rejections=json_text(
                influence_result.get(
                    "signal_context_rejections"
                )
            ),
            rules_version=influence_result.get(
                "rules_version"
            ),
            migration_context=influence_result.get(
                "migration_context"
            ),
            human_migration_context=influence_result.get(
                "human_migration_context"
            ),
            historical_reference=bool(
                influence_result.get(
                    "historical_reference"
                )
            ),
            historical_reason=influence_result.get(
                "historical_reason"
            ),
            historical_reference_text=influence_result.get(
                "historical_reference_text"
            ),
            primary_location=location_name,
            country=country,
            primary_region=primary_region,
            latitude=latitude,
            longitude=longitude,
            first_detected_at=now,
            last_detected_at=now,
            detection_count=1,
            first_run_id=monitor_run.id,
            last_run_id=monitor_run.id,
        )

        session.add(record)
        session.flush()

        return record, True

    record.collected_post_id = (
        collected_post.id
        if collected_post
        else record.collected_post_id
    )

    record.author = (
        post.get("author")
        or record.author
    )

    record.language = (
        post.get("language")
        or record.language
    )

    normalized_published_at = (
        normalize_datetime(
            post.get("published_at")
        )
    )

    record.published_at = (
        normalized_published_at
        or record.published_at
    )

    record.text = (
        post.get("text")
        or record.text
        or ""
    )

    record.source_url = (
        post.get("url")
        or record.source_url
    )

    record.signal_mode = (
        influence_result.get(
            "signal_mode"
        )
        or record.signal_mode
    )

    record.signal_intent = (
        infer_signal_intent(
            primary_signal
        )
    )

    record.priority = (
        infer_influence_priority(
            primary_signal,
            confidence,
        )
    )

    record.confidence = (
        confidence
        if confidence is not None
        else record.confidence
    )

    record.score = (
        influence_result.get(
            "score"
        )
        if influence_result.get(
            "score"
        ) is not None
        else record.score
    )

    record.matched_signals = json_text(
        influence_result.get(
            "matched_signals"
        )
    )

    record.matched_phrases = json_text(
        influence_result.get(
            "matched_phrases"
        )
    )

    record.matched_groups = json_text(
        influence_result.get(
            "matched_groups"
        )
    )

    record.context_matches = json_text(
        influence_result.get(
            "context_matches"
        )
    )

    record.high_value_matches = json_text(
        influence_result.get(
            "high_value_matches"
        )
        or influence_result.get(
            "high_value_match"
        )
    )

    record.signal_context_rejections = json_text(
        influence_result.get(
            "signal_context_rejections"
        )
    )

    record.rules_version = (
        influence_result.get(
            "rules_version"
        )
        or record.rules_version
    )

    if influence_result.get(
        "migration_context"
    ) is not None:
        record.migration_context = (
            influence_result.get(
                "migration_context"
            )
        )

    if influence_result.get(
        "human_migration_context"
    ) is not None:
        record.human_migration_context = (
            influence_result.get(
                "human_migration_context"
            )
        )

    record.historical_reference = bool(
        influence_result.get(
            "historical_reference"
        )
    )

    record.historical_reason = (
        influence_result.get(
            "historical_reason"
        )
    )

    record.historical_reference_text = (
        influence_result.get(
            "historical_reference_text"
        )
    )

    record.primary_location = (
        location_name
        or record.primary_location
    )

    record.country = (
        country
        or record.country
    )

    record.primary_region = (
        primary_region
        or record.primary_region
    )

    record.latitude = (
        latitude
        if latitude is not None
        else record.latitude
    )

    record.longitude = (
        longitude
        if longitude is not None
        else record.longitude
    )

    record.last_detected_at = now
    record.last_run_id = monitor_run.id
    record.detection_count = (
        int(record.detection_count or 0)
        + 1
    )

    session.flush()

    return record, False


def update_monitor_run(
    monitor_run,
    *,
    total_posts_found,
    seen_post_keys,
    total_x_posts_found,
    total_reddit_posts_found,
    total_mastodon_posts_found,
    unique_source_counts,
    x_collector_errors,
    reddit_collector_errors,
    mastodon_collector_errors,
    total_noise_filtered,
    total_non_operational_filtered,
    total_historical_filtered,
    total_influence_signals,
    influence_signal_counts,
    total_operational_events,
    stored_events,
    total_new_events,
    total_correlated_events,
    total_database_correlations,
    total_current_run_correlations,
    total_events_saved,
    total_events_existing,
    total_new_event_groups,
    total_updated_event_groups,
    total_bootstrapped_event_groups,
    total_existing_event_groups,
    total_group_sources_linked,
    status,
    error_message=None,
):
    """
    Copies current run counters into MonitorRun.
    """
    monitor_run.completed_at = utcnow()
    monitor_run.status = status

    monitor_run.posts_returned = (
        total_posts_found
    )

    monitor_run.unique_posts_collected = (
        len(seen_post_keys)
    )

    monitor_run.x_posts_returned = (
        total_x_posts_found
    )

    monitor_run.reddit_posts_returned = (
        total_reddit_posts_found
    )

    monitor_run.mastodon_posts_returned = (
        total_mastodon_posts_found
    )

    monitor_run.unique_x_posts = (
        unique_source_counts.get(
            "X",
            0,
        )
    )

    monitor_run.unique_reddit_posts = (
        unique_source_counts.get(
            "REDDIT",
            0,
        )
    )

    monitor_run.unique_mastodon_posts = (
        unique_source_counts.get(
            "MASTODON",
            0,
        )
    )

    monitor_run.noise_filtered = (
        total_noise_filtered
    )

    monitor_run.non_operational_filtered = (
        total_non_operational_filtered
    )

    monitor_run.historical_references_filtered = (
        total_historical_filtered
    )

    monitor_run.influence_signals_detected = (
        total_influence_signals
    )

    monitor_run.crossing_facilitation_signals = (
        influence_signal_counts.get(
            "CROSSING_FACILITATION",
            0,
        )
    )

    monitor_run.legal_migration_signals = (
        influence_signal_counts.get(
            "LEGAL_MIGRATION_SIGNAL",
            0,
        )
    )

    monitor_run.policy_signals = (
        influence_signal_counts.get(
            "POLICY_SIGNAL",
            0,
        )
    )

    monitor_run.recruitment_coordination_signals = (
        influence_signal_counts.get(
            "RECRUITMENT_COORDINATION",
            0,
        )
    )

    monitor_run.mobilization_coordination_signals = (
        influence_signal_counts.get(
            "MOBILIZATION_COORDINATION",
            0,
        )
    )

    monitor_run.mobilization_report_signals = (
        influence_signal_counts.get(
            "MOBILIZATION_REPORT",
            0,
        )
    )

    monitor_run.decision_influence_signals = (
        influence_signal_counts.get(
            "DECISION_INFLUENCE",
            0,
        )
    )

    monitor_run.online_influence_report_signals = (
        influence_signal_counts.get(
            "ONLINE_INFLUENCE_REPORT",
            0,
        )
    )

    monitor_run.operational_events_analyzed = (
        total_operational_events
    )

    monitor_run.historical_events_available = (
        len(stored_events)
    )

    monitor_run.new_correlation_groups = (
        total_new_events
    )

    monitor_run.events_correlated_existing = (
        total_correlated_events
    )

    monitor_run.database_correlations = (
        total_database_correlations
    )

    monitor_run.current_run_correlations = (
        total_current_run_correlations
    )

    monitor_run.new_events_saved = (
        total_events_saved
    )

    monitor_run.events_already_existing = (
        total_events_existing
    )

    monitor_run.new_event_groups = (
        total_new_event_groups
    )

    monitor_run.updated_event_groups = (
        total_updated_event_groups
    )

    monitor_run.bootstrapped_event_groups = (
        total_bootstrapped_event_groups
    )

    monitor_run.existing_event_groups_reused = (
        total_existing_event_groups
    )

    monitor_run.event_group_sources_linked = (
        total_group_sources_linked
    )

    monitor_run.x_collector_errors = (
        x_collector_errors
    )

    monitor_run.reddit_collector_errors = (
        reddit_collector_errors
    )

    monitor_run.mastodon_collector_errors = (
        mastodon_collector_errors
    )

    monitor_run.error_message = (
        str(error_message)[:4000]
        if error_message
        else None
    )


def main():
    """
    Main execution flow.
    """

    print(
        "==================================="
    )

    print(
        " Migration OSINT Monitor"
    )

    print(
        "==================================="
    )

    initialize_database()

    x_collector = XCollector()

    reddit_collector = (
        RedditCollector()
    )

    mastodon_collector = (
        MastodonCollector()
    )

    keyword_filter = KeywordFilter()

    classifier = SignalClassifier()

    influence_detector = (
        InfluenceSignalDetector()
    )

    location_extractor = (
        LocationExtractor()
    )

    time_extractor = (
        TimeExtractor()
    )

    scorer = RelevanceScorer()

    event_extractor = (
        EventExtractor()
    )

    query_engine = QueryEngine()

    noise_filter = NoiseFilter()

    operational_filter = (
        OperationalEventFilter()
    )

    region_resolver = (
        RegionResolver()
    )

    event_correlator = (
        EventCorrelator()
    )

    event_group_engine = (
        EventGroupEngine()
    )

    event_repository = (
        EventRepository()
    )

    correlation_repository = (
        CorrelationRepository(
            lookback_days=7
        )
    )

    session = get_session()

    monitor_run = MonitorRun(
        run_uuid=str(uuid.uuid4()),
        started_at=utcnow(),
        status="RUNNING",
    )

    session.add(monitor_run)
    session.commit()

    print(
        "Monitor run ID: "
        f"{monitor_run.id}"
    )

    print(
        "Monitor run UUID: "
        f"{monitor_run.run_uuid}"
    )

    queries = (
        query_engine.load_queries()
    )

    print(
        f"Loaded queries: "
        f"{len(queries)}"
    )

    # --------------------------------
    # DATABASE-BACKED CORRELATION
    # --------------------------------

    stored_events = (
        correlation_repository
        .get_recent_events_as_dicts(
            session
        )
    )

    # Region fields are not yet stored
    # in the current Post schema.
    # Reconstruct them when historical
    # events are loaded.
    for stored_event in stored_events:
        apply_region_resolution(
            event=stored_event,
            region_resolver=region_resolver,
        )

    correlation_events = list(
        stored_events
    )

    print(
        "Historical correlation events loaded: "
        f"{len(stored_events)}"
    )

    print(
        "Correlation lookback window: "
        "7 days"
    )

    # Source-aware de-duplication. The same numeric/string ID from two
    # different platforms must not collide.
    seen_post_keys = set()

    total_posts_found = 0
    total_x_posts_found = 0
    total_reddit_posts_found = 0
    total_mastodon_posts_found = 0

    unique_source_counts = {
        "X": 0,
        "REDDIT": 0,
        "MASTODON": 0,
    }

    x_collector_errors = 0
    reddit_collector_errors = 0
    mastodon_collector_errors = 0

    total_noise_filtered = 0
    total_non_operational_filtered = 0
    total_historical_filtered = 0
    total_operational_events = 0
    total_events_saved = 0
    total_events_existing = 0

    # Influence Signal statistics
    total_influence_signals = 0
    influence_signal_counts = {
        "CROSSING_FACILITATION": 0,
        "LEGAL_MIGRATION_SIGNAL": 0,
        "POLICY_SIGNAL": 0,
        "RECRUITMENT_COORDINATION": 0,
        "MOBILIZATION_COORDINATION": 0,
        "MOBILIZATION_REPORT": 0,
        "DECISION_INFLUENCE": 0,
        "ONLINE_INFLUENCE_REPORT": 0,
    }

    total_correlated_events = 0
    total_new_events = 0

    total_database_correlations = 0
    total_current_run_correlations = 0

    # Event Group statistics
    total_new_event_groups = 0
    total_updated_event_groups = 0
    total_bootstrapped_event_groups = 0
    total_existing_event_groups = 0
    total_group_sources_linked = 0

    historical_post_ids = {
        str(
            event.get(
                "source_post_id"
            )
            or ""
        )
        for event in stored_events
        if event.get(
            "source_post_id"
        )
    }

    try:
        for query_definition in queries:

            query_id = (
                query_definition.get(
                    "id"
                )
            )

            query_group = (
                query_definition.get(
                    "query_group"
                )
            )

            query_text = (
                query_definition.get(
                    "query"
                )
            )

            if not query_text:
                continue

            print(
                "==================================="
            )

            print(
                f"Query group: "
                f"{query_group}"
            )

            print(
                f"Query ID: "
                f"{query_id}"
            )

            print(
                "==================================="
            )

            # --------------------------------
            # MULTI-SOURCE COLLECTION
            # --------------------------------

            x_posts = []
            reddit_posts = []
            mastodon_posts = []

            try:
                x_posts = (
                    x_collector.search_recent(
                        query=query_text,
                        max_results=10,
                        max_pages=1,
                    )
                )

            except Exception as error:
                x_collector_errors += 1

                print(
                    "X COLLECTOR WARNING: "
                    f"{error}"
                )

            reddit_query = (
                build_reddit_query(
                    query_text
                )
            )

            if reddit_query:
                try:
                    reddit_posts = (
                        reddit_collector.search_recent(
                            query=reddit_query,
                            max_results=10,
                            max_pages=1,
                        )
                    )

                except Exception as error:
                    reddit_collector_errors += 1

                    print(
                        "REDDIT COLLECTOR WARNING: "
                        f"{error}"
                    )

            try:
                mastodon_posts = (
                    mastodon_collector.search_recent(
                        query=query_text,
                        max_results=10,
                        max_pages=1,
                    )
                )

            except Exception as error:
                mastodon_collector_errors += 1

                print(
                    "MASTODON COLLECTOR WARNING: "
                    f"{error}"
                )

            total_x_posts_found += (
                len(x_posts)
            )

            total_reddit_posts_found += (
                len(reddit_posts)
            )

            total_mastodon_posts_found += (
                len(mastodon_posts)
            )

            posts = (
                x_posts
                + reddit_posts
                + mastodon_posts
            )

            total_posts_found += (
                len(posts)
            )

            print(
                "X posts found: "
                f"{len(x_posts)}"
            )

            print(
                "Reddit query: "
                f"{reddit_query}"
            )

            print(
                "Reddit posts found: "
                f"{len(reddit_posts)}"
            )

            print(
                "Mastodon posts found: "
                f"{len(mastodon_posts)}"
            )

            print(
                "Combined posts found: "
                f"{len(posts)}"
            )

            for post in posts:

                post_id = post.get(
                    "post_id"
                )

                source = (
                    str(
                        post.get(
                            "source"
                        )
                        or "UNKNOWN"
                    )
                    .upper()
                )

                post_key = (
                    source,
                    str(
                        post_id
                        or post.get("url")
                        or post.get("text", "")
                    ),
                )

                if post_key in seen_post_keys:
                    continue

                seen_post_keys.add(
                    post_key
                )

                if source in unique_source_counts:
                    unique_source_counts[
                        source
                    ] += 1

                collected_post, collected_post_created = (
                    get_or_create_collected_post(
                        session=session,
                        post=post,
                        monitor_run=monitor_run,
                        query_id=query_id,
                        query_group=query_group,
                        search_query=query_text,
                    )
                )

                text = post.get(
                    "text",
                    "",
                )

                noise_result = (
                    noise_filter.analyze(
                        text
                    )
                )

                if noise_result.get(
                    "is_noise"
                ):
                    total_noise_filtered += 1

                    update_collected_post_analysis(
                        collected_post,
                        is_noise=True,
                        is_operational=False,
                        influence_detected=False,
                    )

                    session.commit()

                    print(
                        "-----------------------------------"
                    )

                    print(
                        "NOISE FILTERED"
                    )

                    print(
                        "Categories: "
                        f"{noise_result.get('noise_categories')}"
                    )

                    print(
                        "Matched phrases: "
                        f"{noise_result.get('matched_noise_phrases')}"
                    )

                    print(
                        f"Text: "
                        f"{text}"
                    )

                    continue

                # --------------------------------
                # INFLUENCE SIGNAL DETECTION
                # --------------------------------
                #
                # This detector runs before the operational
                # event filter so that legal, policy,
                # facilitation and coordination signals can
                # still be identified even when they are not
                # direct operational migration events.
                #
                # Influence signals are persisted in a parallel
                # history layer. They still do not change event
                # classification, correlation or EventGroup processing.

                influence_result = (
                    influence_detector.detect(
                        text
                    )
                )

                if influence_result.get(
                    "detected"
                ):
                    total_influence_signals += 1

                    primary_influence_signal = (
                        influence_result.get(
                            "primary_signal"
                        )
                    )

                    if (
                        primary_influence_signal
                        in influence_signal_counts
                    ):
                        influence_signal_counts[
                            primary_influence_signal
                        ] += 1

                    save_influence_signal(
                        session=session,
                        post=post,
                        collected_post=collected_post,
                        influence_result=influence_result,
                        monitor_run=monitor_run,
                        location_extractor=location_extractor,
                        region_resolver=region_resolver,
                    )

                    update_collected_post_analysis(
                        collected_post,
                        influence_detected=True,
                    )

                    print_influence_signal(
                        post=post,
                        influence_result=influence_result,
                    )

                operational_result = (
                    operational_filter
                    .analyze(
                        text
                    )
                )

                if not operational_result.get(
                    "is_operational"
                ):
                    total_non_operational_filtered += 1

                    update_collected_post_analysis(
                        collected_post,
                        is_noise=False,
                        is_operational=False,
                        operational_confidence=(
                            operational_result.get(
                                "confidence"
                            )
                        ),
                        influence_detected=(
                            bool(
                                influence_result.get(
                                    "detected"
                                )
                            )
                        ),
                    )

                    session.commit()

                    print(
                        "-----------------------------------"
                    )

                    print(
                        "NON-OPERATIONAL FILTERED"
                    )

                    print(
                        "Non-operational categories: "
                        f"{operational_result.get('non_operational_categories')}"
                    )

                    print(
                        "Matched non-operational phrases: "
                        f"{operational_result.get('matched_non_operational_phrases')}"
                    )

                    print(
                        "Operational confidence: "
                        f"{operational_result.get('confidence')}"
                    )

                    print(
                        f"Text: "
                        f"{text}"
                    )

                    continue

                update_collected_post_analysis(
                    collected_post,
                    is_noise=False,
                    is_operational=True,
                    operational_confidence=(
                        operational_result.get(
                            "confidence"
                        )
                    ),
                    influence_detected=(
                        bool(
                            influence_result.get(
                                "detected"
                            )
                        )
                    ),
                )

                print(
                    "-----------------------------------"
                )

                print(
                    "OPERATIONAL SIGNAL"
                )

                print(
                    "Operational categories: "
                    f"{operational_result.get('operational_categories')}"
                )

                print(
                    "Matched operational phrases: "
                    f"{operational_result.get('matched_operational_phrases')}"
                )

                print(
                    "Operational confidence: "
                    f"{operational_result.get('confidence')}"
                )

                event = analyze_post(
                    post=post,
                    keyword_filter=keyword_filter,
                    classifier=classifier,
                    location_extractor=location_extractor,
                    time_extractor=time_extractor,
                    scorer=scorer,
                    event_extractor=event_extractor,
                    region_resolver=region_resolver,
                )

                if event.get("historical_reference"):
                    total_historical_filtered += 1

                    print(
                        "-----------------------------------"
                    )

                    print(
                        "HISTORICAL REFERENCE FILTERED"
                    )

                    print(
                        "Reason: "
                        f"{event.get('historical_reason')}"
                    )

                    print(
                        "Historical reference: "
                        f"{event.get('historical_reference_time')}"
                    )

                    print(
                        "Detected event type: "
                        f"{event.get('event_type')}"
                    )

                    print(
                        "Text: "
                        f"{text}"
                    )

                    session.commit()

                    continue

                total_operational_events += 1

                candidates = (
                    build_correlation_candidates(
                        new_event=event,
                        correlation_events=correlation_events,
                    )
                )

                correlation_result = (
                    event_correlator.find_match(
                        new_event=event,
                        existing_events=candidates,
                    )
                )

                if correlation_result:
                    total_correlated_events += 1

                    matched_event = (
                        correlation_result.get(
                            "event"
                        )
                        or {}
                    )

                    matched_post_id = str(
                        matched_event.get(
                            "source_post_id"
                        )
                        or ""
                    )

                    if (
                        matched_post_id
                        in historical_post_ids
                    ):
                        total_database_correlations += 1

                    else:
                        total_current_run_correlations += 1

                else:
                    total_new_events += 1

                # --------------------------------
                # POST / EVENT STORAGE
                # --------------------------------

                saved = (
                    event_repository.save_event(
                        session=session,
                        event=event,
                    )
                )

                if saved:
                    total_events_saved += 1

                else:
                    total_events_existing += 1

                # --------------------------------
                # EVENT GROUP / CLUSTER
                # --------------------------------

                event_group_result = (
                    event_group_engine.process(
                        session=session,
                        event=event,
                        correlation_result=correlation_result,
                    )
                )

                group_action = (
                    event_group_result.get(
                        "group_action"
                    )
                )

                if (
                    group_action
                    == "NEW_GROUP"
                ):
                    total_new_event_groups += 1

                elif (
                    group_action
                    == "UPDATED_GROUP"
                ):
                    total_updated_event_groups += 1

                elif (
                    group_action
                    == "BOOTSTRAPPED_GROUP"
                ):
                    total_bootstrapped_event_groups += 1

                elif group_action in {
                    "EXISTING_GROUP",
                    "EXISTING_SOURCE",
                }:
                    total_existing_event_groups += 1

                if event_group_result.get(
                    "source_linked"
                ):
                    total_group_sources_linked += 1

                print_event(
                    event=event,
                    saved=saved,
                    correlation_result=correlation_result,
                    event_group_result=event_group_result,
                )

                correlation_events.append(
                    event
                )

                session.commit()

        update_monitor_run(
            monitor_run,
            total_posts_found=total_posts_found,
            seen_post_keys=seen_post_keys,
            total_x_posts_found=total_x_posts_found,
            total_reddit_posts_found=total_reddit_posts_found,
            total_mastodon_posts_found=total_mastodon_posts_found,
            unique_source_counts=unique_source_counts,
            x_collector_errors=x_collector_errors,
            reddit_collector_errors=reddit_collector_errors,
            mastodon_collector_errors=mastodon_collector_errors,
            total_noise_filtered=total_noise_filtered,
            total_non_operational_filtered=total_non_operational_filtered,
            total_historical_filtered=total_historical_filtered,
            total_influence_signals=total_influence_signals,
            influence_signal_counts=influence_signal_counts,
            total_operational_events=total_operational_events,
            stored_events=stored_events,
            total_new_events=total_new_events,
            total_correlated_events=total_correlated_events,
            total_database_correlations=total_database_correlations,
            total_current_run_correlations=total_current_run_correlations,
            total_events_saved=total_events_saved,
            total_events_existing=total_events_existing,
            total_new_event_groups=total_new_event_groups,
            total_updated_event_groups=total_updated_event_groups,
            total_bootstrapped_event_groups=total_bootstrapped_event_groups,
            total_existing_event_groups=total_existing_event_groups,
            total_group_sources_linked=total_group_sources_linked,
            status="SUCCESS",
        )

        session.commit()

    except Exception as error:
        session.rollback()

        try:
            monitor_run = (
                session.query(MonitorRun)
                .filter(
                    MonitorRun.id == monitor_run.id
                )
                .one_or_none()
            )

            if monitor_run is not None:
                update_monitor_run(
                    monitor_run,
                    total_posts_found=total_posts_found,
                    seen_post_keys=seen_post_keys,
                    total_x_posts_found=total_x_posts_found,
                    total_reddit_posts_found=total_reddit_posts_found,
                    total_mastodon_posts_found=total_mastodon_posts_found,
                    unique_source_counts=unique_source_counts,
                    x_collector_errors=x_collector_errors,
                    reddit_collector_errors=reddit_collector_errors,
                    mastodon_collector_errors=mastodon_collector_errors,
                    total_noise_filtered=total_noise_filtered,
                    total_non_operational_filtered=total_non_operational_filtered,
                    total_historical_filtered=total_historical_filtered,
                    total_influence_signals=total_influence_signals,
                    influence_signal_counts=influence_signal_counts,
                    total_operational_events=total_operational_events,
                    stored_events=stored_events,
                    total_new_events=total_new_events,
                    total_correlated_events=total_correlated_events,
                    total_database_correlations=total_database_correlations,
                    total_current_run_correlations=total_current_run_correlations,
                    total_events_saved=total_events_saved,
                    total_events_existing=total_events_existing,
                    total_new_event_groups=total_new_event_groups,
                    total_updated_event_groups=total_updated_event_groups,
                    total_bootstrapped_event_groups=total_bootstrapped_event_groups,
                    total_existing_event_groups=total_existing_event_groups,
                    total_group_sources_linked=total_group_sources_linked,
                    status="FAILED",
                    error_message=error,
                )

                session.commit()

        except Exception as run_update_error:
            session.rollback()

            print(
                "MONITOR RUN HISTORY WARNING: "
                f"{run_update_error}"
            )

        raise

    finally:
        session.close()

    print(
        "==================================="
    )

    print(
        "RUN SUMMARY"
    )

    print(
        "==================================="
    )

    print(
        "Posts returned by queries: "
        f"{total_posts_found}"
    )

    print(
        "Unique posts collected: "
        f"{len(seen_post_keys)}"
    )

    print(
        "X posts returned: "
        f"{total_x_posts_found}"
    )

    print(
        "Reddit posts returned: "
        f"{total_reddit_posts_found}"
    )

    print(
        "Mastodon posts returned: "
        f"{total_mastodon_posts_found}"
    )

    print(
        "Unique X posts: "
        f"{unique_source_counts['X']}"
    )

    print(
        "Unique Reddit posts: "
        f"{unique_source_counts['REDDIT']}"
    )

    print(
        "Unique Mastodon posts: "
        f"{unique_source_counts['MASTODON']}"
    )

    print(
        "X collector errors: "
        f"{x_collector_errors}"
    )

    print(
        "Reddit collector errors: "
        f"{reddit_collector_errors}"
    )

    print(
        "Mastodon collector errors: "
        f"{mastodon_collector_errors}"
    )

    print(
        "Noise filtered: "
        f"{total_noise_filtered}"
    )

    print(
        "Non-operational filtered: "
        f"{total_non_operational_filtered}"
    )

    print(
        "Historical references filtered: "
        f"{total_historical_filtered}"
    )

    print(
        "Influence signals detected: "
        f"{total_influence_signals}"
    )

    print(
        "Crossing facilitation signals: "
        f"{influence_signal_counts['CROSSING_FACILITATION']}"
    )

    print(
        "Legal migration signals: "
        f"{influence_signal_counts['LEGAL_MIGRATION_SIGNAL']}"
    )

    print(
        "Policy signals: "
        f"{influence_signal_counts['POLICY_SIGNAL']}"
    )

    print(
        "Recruitment / coordination signals: "
        f"{influence_signal_counts['RECRUITMENT_COORDINATION']}"
    )

    print(
        "Mobilization / coordination signals: "
        f"{influence_signal_counts['MOBILIZATION_COORDINATION']}"
    )

    print(
        "Mobilization report signals: "
        f"{influence_signal_counts['MOBILIZATION_REPORT']}"
    )

    print(
        "Decision influence signals: "
        f"{influence_signal_counts['DECISION_INFLUENCE']}"
    )

    print(
        "Online influence report signals: "
        f"{influence_signal_counts['ONLINE_INFLUENCE_REPORT']}"
    )

    print(
        "Operational events analyzed: "
        f"{total_operational_events}"
    )

    print(
        "Historical events available for correlation: "
        f"{len(stored_events)}"
    )

    print(
        "New correlation groups: "
        f"{total_new_events}"
    )

    print(
        "Events correlated with existing groups: "
        f"{total_correlated_events}"
    )

    print(
        "Database-backed correlations: "
        f"{total_database_correlations}"
    )

    print(
        "Current-run correlations: "
        f"{total_current_run_correlations}"
    )

    print(
        "New events saved to database: "
        f"{total_events_saved}"
    )

    print(
        "Events already in database: "
        f"{total_events_existing}"
    )

    print(
        "New EventGroups created: "
        f"{total_new_event_groups}"
    )

    print(
        "EventGroups updated: "
        f"{total_updated_event_groups}"
    )

    print(
        "Historical EventGroups bootstrapped: "
        f"{total_bootstrapped_event_groups}"
    )

    print(
        "Existing EventGroups reused: "
        f"{total_existing_event_groups}"
    )

    print(
        "EventGroup sources linked: "
        f"{total_group_sources_linked}"
    )

    print(
        "System run completed successfully."
    )


if __name__ == "__main__":
    main()
