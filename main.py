"""
Migration OSINT Monitor

File:
main.py

Description:
Application entry point using the Query Engine,
Noise Filter, Operational Event Filter, X collection,
analysis, event extraction, event correlation and SQLite storage.
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

from database.init_db import initialize_database
from database.database import get_session
from database.event_repository import EventRepository


def analyze_post(
    post,
    keyword_filter,
    classifier,
    location_extractor,
    time_extractor,
    scorer,
    event_extractor,
):
    """
    Runs the analytical pipeline for a single post.
    """

    text = post.get("text", "")

    has_migration_keyword = (
        keyword_filter.contains_migration_keyword(text)
    )

    classification = classifier.classify(text)

    matched_signals = classification.get(
        "matched_signals",
        [],
    )

    locations = location_extractor.extract_locations(text)

    time_result = time_extractor.extract(
        text=text,
        published_at=None,
    )

    score_result = scorer.calculate_score(
        has_migration_keyword=has_migration_keyword,
        location_count=len(locations),
        has_time_reference=time_result is not None,
        has_movement_signal=(
            "ROUTE_INFORMATION" in matched_signals
            or "DEPARTURE_SIGNAL" in matched_signals
            or "BORDER_CROSSING" in matched_signals
            or "ARRIVAL" in matched_signals
        ),
        has_advice_signal=(
            "TRAVEL_ADVICE" in matched_signals
        ),
        has_coordination_signal=(
            "COORDINATION" in matched_signals
        ),
        has_transport_signal=(
            "TRANSPORT_OFFER" in matched_signals
        ),
    )

    return event_extractor.extract_event(
        post=post,
        classification=classification,
        locations=locations,
        time_result=time_result,
        score_result=score_result,
    )


def print_event(
    event,
    saved,
    correlation_result,
):
    """
    Prints a normalized event, database status and
    correlation information.
    """

    primary_location = event.get("primary_location")

    print("-----------------------------------")
    print("EVENT")
    print(f"Type: {event.get('event_type')}")
    print(f"Confidence: {event.get('event_confidence')}")
    print(f"Score: {event.get('relevance_score')}")
    print(f"Level: {event.get('relevance_level')}")

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
        print("Primary location: None")

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
        matched_event = correlation_result.get("event") or {}

        print("Correlation: MATCH")
        print(
            "Correlation score: "
            f"{correlation_result.get('correlation_score')}"
        )
        print(
            "Correlated source post: "
            f"{matched_event.get('source_post_id')}"
        )
        print(
            "Correlated event type: "
            f"{matched_event.get('event_type')}"
        )
    else:
        print("Correlation: NEW EVENT")

    print(f"Author: {event.get('author')}")
    print(f"Published: {event.get('published_at')}")
    print(f"Language: {event.get('language')}")
    print(f"Text: {event.get('text')}")
    print(f"URL: {event.get('source_url')}")

    if saved:
        print("Database: SAVED")
    else:
        print("Database: ALREADY EXISTS")


def main():
    """
    Main execution flow.
    """

    print("===================================")
    print(" Migration OSINT Monitor")
    print("===================================")

    initialize_database()

    collector = XCollector()

    keyword_filter = KeywordFilter()
    classifier = SignalClassifier()
    location_extractor = LocationExtractor()
    time_extractor = TimeExtractor()
    scorer = RelevanceScorer()
    event_extractor = EventExtractor()
    query_engine = QueryEngine()
    noise_filter = NoiseFilter()
    operational_filter = OperationalEventFilter()
    event_correlator = EventCorrelator()
    event_repository = EventRepository()

    session = get_session()

    queries = query_engine.load_queries()

    print(
        f"Loaded queries: "
        f"{len(queries)}"
    )

    seen_post_ids = set()
    analyzed_events = []

    total_posts_found = 0
    total_noise_filtered = 0
    total_non_operational_filtered = 0
    total_operational_events = 0
    total_events_saved = 0
    total_events_existing = 0
    total_correlated_events = 0
    total_new_events = 0

    try:
        for query_definition in queries:
            query_id = query_definition.get("id")
            query_group = query_definition.get("query_group")
            query_text = query_definition.get("query")

            if not query_text:
                continue

            print("===================================")
            print(f"Query group: {query_group}")
            print(f"Query ID: {query_id}")
            print("===================================")

            posts = collector.search_recent(
                query=query_text,
                max_results=10,
                max_pages=1,
            )

            total_posts_found += len(posts)

            print(
                f"Posts found: "
                f"{len(posts)}"
            )

            for post in posts:
                post_id = post.get("post_id")

                if post_id in seen_post_ids:
                    continue

                if post_id:
                    seen_post_ids.add(post_id)

                text = post.get("text", "")

                noise_result = noise_filter.analyze(text)

                if noise_result.get("is_noise"):
                    total_noise_filtered += 1

                    print("-----------------------------------")
                    print("NOISE FILTERED")
                    print(
                        "Categories: "
                        f"{noise_result.get('noise_categories')}"
                    )
                    print(
                        "Matched phrases: "
                        f"{noise_result.get('matched_noise_phrases')}"
                    )
                    print(f"Text: {text}")

                    continue

                operational_result = (
                    operational_filter.analyze(text)
                )

                if not operational_result.get("is_operational"):
                    total_non_operational_filtered += 1

                    print("-----------------------------------")
                    print("NON-OPERATIONAL FILTERED")
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
                    print(f"Text: {text}")

                    continue

                print("-----------------------------------")
                print("OPERATIONAL SIGNAL")
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
                )

                total_operational_events += 1

                correlation_result = (
                    event_correlator.find_match(
                        new_event=event,
                        existing_events=analyzed_events,
                    )
                )

                if correlation_result:
                    total_correlated_events += 1
                else:
                    total_new_events += 1

                saved = event_repository.save_event(
                    session=session,
                    event=event,
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

                analyzed_events.append(event)

    finally:
        session.close()

    print("===================================")
    print("RUN SUMMARY")
    print("===================================")

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
        "New correlation groups: "
        f"{total_new_events}"
    )

    print(
        "Events correlated with existing groups: "
        f"{total_correlated_events}"
    )

    print(
        "New events saved to database: "
        f"{total_events_saved}"
    )

    print(
        "Events already in database: "
        f"{total_events_existing}"
    )

    print("System run completed successfully.")


if __name__ == "__main__":
    main()
