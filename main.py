"""
Migration OSINT Monitor

File:
main.py

Description:
Application entry point and basic X API connectivity test.
"""

from database.init_db import initialize_database
from collectors.x_collector import XCollector


def main():
    print("===================================")
    print(" Migration OSINT Monitor")
    print("===================================")

    initialize_database()

    print("Testing X API connection...")

    collector = XCollector()

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

    for post in posts[:5]:
        print("-----------------------------------")
        print(f"Author: {post.get('author')}")
        print(f"Published: {post.get('published_at')}")
        print(f"Language: {post.get('language')}")
        print(f"Text: {post.get('text')}")
        print(f"URL: {post.get('url')}")

    print("-----------------------------------")
    print("System run completed successfully.")


if __name__ == "__main__":
    main()
