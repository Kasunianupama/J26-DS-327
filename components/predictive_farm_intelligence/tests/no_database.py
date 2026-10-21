"""Opt-in pytest safety plugin: fail before SQLAlchemy or SQLite connects.

Run with -p components.predictive_farm_intelligence.tests.no_database.
Database writer integration tests must be deselected, never loosened to pass.
"""
import sqlite3

from sqlalchemy.engine import Engine


def _blocked(*args, **kwargs):
    raise AssertionError("Database connections are forbidden in this test run; mock the database")


def pytest_sessionstart(session):
    Engine.connect = _blocked
    Engine.raw_connection = _blocked
    sqlite3.connect = _blocked
