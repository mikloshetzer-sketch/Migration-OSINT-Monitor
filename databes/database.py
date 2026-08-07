"""
Migration OSINT Monitor

File:
database.py

Description:
SQLite database initialization and connection management.
"""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database location
DATABASE_DIR = Path(__file__).resolve().parent
DATABASE_FILE = DATABASE_DIR / "migration_osint_monitor.db"

# SQLAlchemy engine
engine = create_engine(f"sqlite:///{DATABASE_FILE}", echo=False)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_session():
    """
    Returns a new database session.
    """
    return SessionLocal()
