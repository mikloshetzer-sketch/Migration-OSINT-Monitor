"""
Migration OSINT Monitor

File:
x_collector.py

Description:
X (Twitter) API collector.
"""

import requests

from config import X_BEARER_TOKEN


class XCollector:
    """
    Handles communication with the X API.
    """

    BASE_URL = "https://api.x.com/2"

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {X_BEARER_TOKEN}"
        }

    def is_configured(self) -> bool:
        """
        Returns True if an API token is configured.
        """
        return bool(X_BEARER_TOKEN)

    def get_headers(self) -> dict:
        """
        Returns the request headers.
        """
        return self.headers
