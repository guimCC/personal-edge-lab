from __future__ import annotations

import sqlite3

import pytest

from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection


def test_shared_connection_enables_required_safety_settings(tmp_path) -> None:
    database = tmp_path / "connection.db"
    with open_connection(database, timeout_seconds=1.25) as connection:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        row = connection.execute("SELECT 1 AS value").fetchone()

    assert foreign_keys == 1
    assert busy_timeout == 1250
    assert row["value"] == 1


def test_shared_connection_enforces_foreign_keys(tmp_path) -> None:
    database = tmp_path / "foreign-keys.db"
    with open_connection(database) as connection:
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            """
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent(id)
            )
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO child (id, parent_id) VALUES (1, 999)")
