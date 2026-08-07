"""
Migration OSINT Monitor

File:
test_database.py

Description:
Basic database initialization test.
"""

from database.init_db import initialize_database
from database.database import get_session


def test_database_initialization():
    """
    Tests whether the database can be initialized
    and a session can be created.
    """

    initialize_database()

    session = get_session()

    assert session is not None

    session.close()
