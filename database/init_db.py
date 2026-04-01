#!/usr/bin/env python3
"""Initialize the SQLite database schema for the Notemaster notes app.

This script is intended to run in the dedicated `database` container.
It creates:
- notes: core note records
- tags: unique tag names
- note_tags: many-to-many between notes and tags
- notes_fts: FTS5 virtual table for full-text search over note title+content
- triggers to keep the FTS index in sync

Environment:
- SQLITE_DB: optional; absolute/relative path to the SQLite database file.
  If not provided, defaults to ./myapp.db

Notes:
- FTS5 is available in most modern SQLite builds. If unavailable, the script will
  fall back to basic schema creation without FTS (search will still work using
  LIKE in the backend).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_NAME = "myapp.db"


def _get_db_path() -> Path:
    """Resolve the SQLite database file path from env or default."""
    env_path = os.getenv("SQLITE_DB")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path.cwd() / DEFAULT_DB_NAME


def _connect(db_path: Path) -> sqlite3.Connection:
    """Create a SQLite connection with pragmas suitable for this app."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Reasonable defaults for a single-file app.
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def _fts5_available(conn: sqlite3.Connection) -> bool:
    """Return True if SQLite FTS5 appears to be available."""
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __fts5_test USING fts5(content);")
        conn.execute("DROP TABLE IF EXISTS __fts5_test;")
        return True
    except sqlite3.Error:
        return False


def _create_schema(conn: sqlite3.Connection, *, enable_fts: bool) -> None:
    """Create app schema and optionally FTS support."""
    # Core tables.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_notes_updated_at ON notes(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notes_archived ON notes(is_archived);

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS note_tags (
            note_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (note_id, tag_id),
            FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_note_tags_note_id ON note_tags(note_id);
        CREATE INDEX IF NOT EXISTS idx_note_tags_tag_id ON note_tags(tag_id);
        """
    )

    if not enable_fts:
        return

    # FTS table: keep an external-content-like pattern by syncing via triggers.
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
        USING fts5(
            title,
            content,
            note_id UNINDEXED,
            tokenize = 'unicode61'
        );

        CREATE INDEX IF NOT EXISTS idx_notes_fts_note_id ON notes_fts(note_id);

        CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
            INSERT INTO notes_fts(rowid, title, content, note_id)
            VALUES (new.id, new.title, new.content, new.id);
        END;

        CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
            DELETE FROM notes_fts WHERE rowid = old.id;
        END;

        CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
            UPDATE notes_fts
            SET title = new.title,
                content = new.content,
                note_id = new.id
            WHERE rowid = old.id;
        END;
        """
    )

    # Backfill FTS for existing notes (idempotent).
    conn.execute("DELETE FROM notes_fts;")
    conn.execute(
        """
        INSERT INTO notes_fts(rowid, title, content, note_id)
        SELECT id, title, content, id FROM notes;
        """
    )


def _seed_example_data(conn: sqlite3.Connection) -> None:
    """Insert a small amount of example data (idempotent-ish)."""
    # If already has notes, don't re-seed.
    existing = conn.execute("SELECT COUNT(1) AS c FROM notes;").fetchone()["c"]
    if existing and int(existing) > 0:
        return

    notes = [
        ("Welcome to Notemaster", "Create notes, tag them, and search instantly."),
        ("Shopping list", "- Coffee\n- Eggs\n- Bread\n- Olive oil"),
        ("Project ideas", "1) Personal knowledge base\n2) Habit tracker\n3) CLI journal"),
    ]
    for title, content in notes:
        conn.execute("INSERT INTO notes(title, content) VALUES(?, ?);", (title, content))

    # Tags
    for t in ["welcome", "personal", "todo", "ideas"]:
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES(?);", (t,))

    # Attach some tags
    note_ids = [r["id"] for r in conn.execute("SELECT id FROM notes ORDER BY id;").fetchall()]
    tag_map = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM tags;").fetchall()}

    def attach(note_id: int, tag_name: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES(?, ?);",
            (note_id, tag_map[tag_name]),
        )

    if len(note_ids) >= 3:
        attach(note_ids[0], "welcome")
        attach(note_ids[0], "personal")
        attach(note_ids[1], "todo")
        attach(note_ids[2], "ideas")
        attach(note_ids[2], "personal")


def main() -> None:
    """Entrypoint for initializing database."""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print("Starting SQLite setup for Notemaster...")
    print(f"Database path: {db_path}")

    conn = _connect(db_path)
    try:
        enable_fts = _fts5_available(conn)
        if enable_fts:
            print("FTS5: available; enabling full-text search index.")
        else:
            print("FTS5: NOT available; search will fall back to LIKE queries.")

        _create_schema(conn, enable_fts=enable_fts)
        _seed_example_data(conn)
        conn.commit()

        # Write a helper env file for the bundled db_visualizer.
        visualizer_dir = Path.cwd() / "db_visualizer"
        visualizer_dir.mkdir(parents=True, exist_ok=True)
        sqlite_env_path = visualizer_dir / "sqlite.env"
        sqlite_env_path.write_text(f'export SQLITE_DB="{db_path}"\n', encoding="utf-8")

        print("SQLite setup complete.")
        print("Wrote db_visualizer/sqlite.env (source it to point the viewer at this DB).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
