"""
Migration OSINT Monitor

File:
main.py

Description:
Application entry point with X API collection, analysis,
and normalized event extraction.
"""

from collectors.x_collector import XCollector
from analysis.keyword_filter import KeywordFilter
from analysis.classifier import SignalClassifier
from analysis.location_extractor import LocationExtractor
from analysis.time_extractor import TimeExtractor
from analysis.scoring import RelevanceScorer
from analysis.event_extractor import EventExtractor
from database.init_db import initialize_database


def main():
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

    query = (
        '(migration OR migrant OR "irregular migration" OR crossing) '
        '(Morocco OR Spain OR Ceuta OR Melilla OR Nador OR Tangier) '
        '-is:retweet'
    )

    posts = collector.search_recent(
        query=query,
        max_results=10,
        max_pages=1,
    )

    print(f"X API test successful. Posts found: {len(posts)}")

    for post in posts:
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

        event = event_extractor.extract_event(
            post=post,
            classification=classification,
            locations=locations,
            time_result=time_result,
            score_result=score_result,
        )

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
            f"Event time: "
            f"{event.get('event_time_normalized')}"
        )

        print(
            f"Time confidence: "
            f"{event.get('event_time_confidence')}"
        )

        print(
            f"Matched signals: "
            f"{event.get('matched_signals')}"
        )

        print(
            f"Matched phrases: "
            f"{event.get('matched_phrases')}"
        )

        print(f"Author: {event.get('author')}")
        print(f"Published: {event.get('published_at')}")
        print(f"Language: {event.get('language')}")
        print(f"Text: {event.get('text')}")
        print(f"URL: {event.get('source_url')}")

    print("-----------------------------------")
    print("System run completed successfully.")


if __name__ == "__main__":
    main()
