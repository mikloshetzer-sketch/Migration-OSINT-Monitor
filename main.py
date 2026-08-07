"""
Migration OSINT Monitor

File:
main.py

Description:
Application entry point with X API collection and basic analysis pipeline.
"""

from collectors.x_collector import XCollector
from analysis.keyword_filter import KeywordFilter
from analysis.classifier import SignalClassifier
from analysis.location_extractor import LocationExtractor
from analysis.time_extractor import TimeExtractor
from analysis.scoring import RelevanceScorer
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
        matched_signals = classification.get("matched_signals", [])

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

        location_names = [
            location.get("name")
            for location in locations
        ]

        print("-----------------------------------")
        print(f"Author: {post.get('author')}")
        print(f"Published: {post.get('published_at')}")
        print(f"Language: {post.get('language')}")
        print(f"Signal type: {classification.get('signal_type')}")
        print(f"Matched signals: {matched_signals}")
        print(f"Score: {score_result.get('score')}")
        print(f"Level: {score_result.get('level')}")
        print(f"Locations: {location_names}")

        if time_result:
            print(
                "Event time: "
                f"{time_result.get('event_time_normalized')}"
            )
            print(
                "Time confidence: "
                f"{time_result.get('event_time_confidence')}"
            )
        else:
            print("Event time: None")

        print(f"Text: {text}")
        print(f"URL: {post.get('url')}")

    print("-----------------------------------")
    print("System run completed successfully.")


if __name__ == "__main__":
    main()
