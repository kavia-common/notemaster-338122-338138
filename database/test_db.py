#!/usr/bin/env python3
"""Pytest checks and optional CLI for verifying SQLite database connectivity.

This file is collected by pytest. It must not perform side effects (like exiting
the interpreter) at import time.

It provides:
- pytest tests (`test_*`) that validate the SQLite DB file exists and is readable.
- a small CLI (`python test_db.py`) that prints the SQLite version for humans.

By default it targets ./myapp.db, but you can override via SQLITE_DB.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_NAME_DEFAULT = "myapp.db"


def _get_db_path() -> Path:
    """Return database path from SQLITE_DB env var or the default relative path."""
    env_db = os.getenv("SQLITE_DB")
    return Path(env_db).expanduser().resolve() if env_db else (Path.cwd() / DB_NAME_DEFAULT)


def _get_sqlite_version(db_path: Path) -> str:
    """Connect to the database and return the sqlite engine version string."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT sqlite_version()")
        row = cur.fetchone()
        assert row is not None and row[0], "Expected sqlite_version() to return a value"
        return str(row[0])
    finally:
        conn.close()


def _can_open_db(db_path: Path) -> None:
    """Verify we can open the DB and run a trivial query."""
    # Using URI mode with immutable=1 prevents accidental writes during the test,
    # and will fail fast if the file is not a valid SQLite DB.
    uri = f"file:{db_path.as_posix()}?immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()


def test_sqlite_db_file_exists() -> None:
    """Ensure the SQLite DB file exists (this repo includes myapp.db)."""
    db_path = _get_db_path()
    assert db_path.exists(), f"Database file not found at {db_path}"
    assert db_path.is_file(), f"Database path is not a file: {db_path}"


def test_sqlite_db_can_be_opened() -> None:
    """Ensure the SQLite DB can be opened and a trivial query can run."""
    db_path = _get_db_path()
    _can_open_db(db_path)


def test_sqlite_version_query_returns_value() -> None:
    """Ensure sqlite_version() query returns a non-empty string."""
    db_path = _get_db_path()
    version = _get_sqlite_version(db_path)
    assert isinstance(version, str) and version.strip(), "SQLite version should be a non-empty string"


def main() -> int:
    """CLI entrypoint: print DB path and SQLite version.

    Returns:
        Process exit code (0 success, 1 failure).
    """
    db_path = _get_db_path()
    if not db_path.exists():
        print(f"Database file not found: {db_path}")
        return 1

    try:
        version = _get_sqlite_version(db_path)
    except sqlite3.Error as e:
        print(f"Connection failed: {e}")
        return 1

    print(f"Database: {db_path}")
    print(f"SQLite version: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
