"""Shared SQLite connection policy for every platform repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 5.0


def open_connection(
    database_path: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> sqlite3.Connection:
    """Open a connection with the platform's required safety settings."""
    connection = sqlite3.connect(database_path, timeout=timeout_seconds)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
