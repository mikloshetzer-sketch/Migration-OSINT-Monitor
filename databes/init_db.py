"""
Migration OSINT Monitor

File:
init_db.py

Description:
Creates the SQLite database and all tables.
"""

from database.database import engine
from database.models import Base


def initialize_database():
    """
    Create all database tables if they do not already exist.
    """
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully.")


if __name__ == "__main__":
    initialize_database()
