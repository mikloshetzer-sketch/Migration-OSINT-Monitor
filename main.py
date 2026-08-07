"""
Migration OSINT Monitor

File:
main.py

Description:
Application entry point.
"""

from database.init_db import initialize_database


def main():
    print("===================================")
    print(" Migration OSINT Monitor")
    print("===================================")

    initialize_database()

    print("System initialized successfully.")


if __name__ == "__main__":
    main()
