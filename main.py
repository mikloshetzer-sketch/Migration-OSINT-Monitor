"""
Migration OSINT Monitor

File:
main.py

Description:
Application entry point using:

- Query Engine
- Noise Filter
- Operational Event Filter
- Signal Classification
- Location Extraction
- Time Extraction
- Region Resolution
- Database-backed Event Correlation
- SQLite Event Storage

The correlation engine compares new operational events against:
1. recent operational events already stored in SQLite
2. operational events detected during the current run
"""

from collectors.x_collector import XCollector

from analysis.keyword_filter import KeywordFilter
from analysis.classifier import SignalClassifier
from analysis.location_extractor import LocationExtractor
from analysis.time_extractor import TimeExtractor
from analysis.scoring import RelevanceScorer
from analysis.event_extractor import EventExtractor
from analysis.query_engine import QueryEngine
from analysis.noise_filter import NoiseFilter
from analysis.operational_event_filter import OperationalEventFilter
from analysis.event_correlator import EventCorrelator
from analysis.region_resolver import RegionResolver

from database.init_db import initialize_database
from database.database import get_session
from database.event_repository import EventRepository
from database.correlation_repository import CorrelationRepository


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
        published_at=None,
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

    This prevents a previously stored X post from
    matching itself when the same post is collected
    again in a later workflow run.
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


def print_event(
    event,
    saved,
    correlation_result,
):
    """
    Prints a normalized event, region information,
    database status and correlation information.
    """

    primary_location = event.get(
        "primary_location"
    )

    print(
        "-----------------------------------"
    )
    print("EVENT")

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

    collector = XCollector()

    keyword_filter = KeywordFilter()

    classifier = SignalClassifier()

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

    event_repository = (
        EventRepository()
    )

    correlation_repository = (
        CorrelationRepository(
            lookback_days=7
        )
    )

    session = get_session()

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
    # in the current V1 database schema.
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

    seen_post_ids = set()

    total_posts_found = 0
    total_noise_filtered = 0
    total_non_operational_filtered = 0
    total_operational_events = 0
    total_events_saved = 0
    total_events_existing = 0

    total_correlated_events = 0
    total_new_events = 0

    total_database_correlations = 0
    total_current_run_correlations = 0

    # IDs of events loaded from SQLite.
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

            posts = collector.search_recent(
                query=query_text,
                max_results=10,
                max_pages=1,
            )

            total_posts_found += (
                len(posts)
            )

            print(
                f"Posts found: "
                f"{len(posts)}"
            )

            for post in posts:

                post_id = post.get(
                    "post_id"
                )

                if (
                    post_id
                    in seen_post_ids
                ):
                    continue

                if post_id:
                    seen_post_ids.add(
                        post_id
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

                print_event(
                    event=event,
                    saved=saved,
                    correlation_result=correlation_result,
                )

                # The new event becomes immediately available
                # for correlation with later posts from the
                # same workflow run.
                correlation_events.append(
                    event
                )

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
        f"{len(seen_post_ids)}"
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
        "System run completed successfully."
    )


if __name__ == "__main__":
    main()
