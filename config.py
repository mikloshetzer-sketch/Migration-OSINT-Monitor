"""
Migration OSINT Monitor

File:
config.py

Description:
Global configuration and environment variable loading.
"""

from pathlib import Path
from dotenv import load_dotenv
import os

# Project root directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")

# API Keys
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "")

MASTODON_BASE_URL = os.getenv("MASTODON_BASE_URL", "")
MASTODON_ACCESS_TOKEN = os.getenv("MASTODON_ACCESS_TOKEN", "")
