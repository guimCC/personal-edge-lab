"""SQLite authentication repository."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from personal_edge_lab.domain.auth import LoginThrottle, SessionRecord
from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection


class SqliteAuthRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = open_connection(database_path, timeout_seconds=timeout_seconds)

    def __enter__(self) -> SqliteAuthRepository:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def create_session(self, session: SessionRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO auth_sessions (
                token_hash, actor_id, csrf_token, credential_fingerprint,
                created_at_utc, last_seen_at_utc, idle_expires_at_utc,
                absolute_expires_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.token_hash,
                session.actor_id,
                session.csrf_token,
                session.credential_fingerprint,
                session.created_at_utc.isoformat(),
                session.last_seen_at_utc.isoformat(),
                session.idle_expires_at_utc.isoformat(),
                session.absolute_expires_at_utc.isoformat(),
            ),
        )
        self._connection.commit()

    def get_session(self, token_hash: str) -> SessionRecord | None:
        row = self._connection.execute(
            "SELECT * FROM auth_sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        return None if row is None else _session_from_row(row)

    def touch_session(
        self,
        token_hash: str,
        *,
        last_seen_at_utc: datetime,
        idle_expires_at_utc: datetime,
    ) -> None:
        self._connection.execute(
            """
            UPDATE auth_sessions
            SET last_seen_at_utc = ?, idle_expires_at_utc = ?
            WHERE token_hash = ?
            """,
            (last_seen_at_utc.isoformat(), idle_expires_at_utc.isoformat(), token_hash),
        )
        self._connection.commit()

    def revoke_session(self, token_hash: str) -> None:
        self._connection.execute(
            "DELETE FROM auth_sessions WHERE token_hash = ?",
            (token_hash,),
        )
        self._connection.commit()

    def revoke_all_sessions(self) -> None:
        self._connection.execute("DELETE FROM auth_sessions")
        self._connection.commit()

    def delete_expired_sessions(self, *, now: datetime) -> None:
        timestamp = now.isoformat()
        self._connection.execute(
            """
            DELETE FROM auth_sessions
            WHERE idle_expires_at_utc <= ? OR absolute_expires_at_utc <= ?
            """,
            (timestamp, timestamp),
        )
        self._connection.commit()

    def get_login_throttle(self, actor_id: str) -> LoginThrottle | None:
        row = self._connection.execute(
            "SELECT * FROM auth_login_throttle WHERE actor_id = ?",
            (actor_id,),
        ).fetchone()
        if row is None:
            return None
        blocked = row["blocked_until_utc"]
        return LoginThrottle(
            actor_id=str(row["actor_id"]),
            window_started_at_utc=datetime.fromisoformat(row["window_started_at_utc"]),
            failed_attempts=int(row["failed_attempts"]),
            blocked_until_utc=None if blocked is None else datetime.fromisoformat(blocked),
        )

    def save_login_throttle(self, throttle: LoginThrottle) -> None:
        self._connection.execute(
            """
            INSERT INTO auth_login_throttle (
                actor_id, window_started_at_utc, failed_attempts, blocked_until_utc
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(actor_id) DO UPDATE SET
                window_started_at_utc = excluded.window_started_at_utc,
                failed_attempts = excluded.failed_attempts,
                blocked_until_utc = excluded.blocked_until_utc
            """,
            (
                throttle.actor_id,
                throttle.window_started_at_utc.isoformat(),
                throttle.failed_attempts,
                None
                if throttle.blocked_until_utc is None
                else throttle.blocked_until_utc.isoformat(),
            ),
        )
        self._connection.commit()

    def record_login_failure(
        self,
        *,
        actor_id: str,
        attempted_at: datetime,
        window_seconds: int,
        max_failures: int,
        block_seconds: int,
    ) -> LoginThrottle:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.get_login_throttle(actor_id)
            window = timedelta(seconds=window_seconds)
            if (
                current is not None
                and current.blocked_until_utc is not None
                and attempted_at < current.blocked_until_utc
            ):
                self._connection.commit()
                return current
            if current is None or attempted_at >= current.window_started_at_utc + window:
                failed_attempts = 1
                window_started = attempted_at
            else:
                failed_attempts = current.failed_attempts + 1
                window_started = current.window_started_at_utc
            blocked_until = (
                attempted_at + timedelta(seconds=block_seconds)
                if failed_attempts >= max_failures
                else None
            )
            throttle = LoginThrottle(
                actor_id=actor_id,
                window_started_at_utc=window_started,
                failed_attempts=failed_attempts,
                blocked_until_utc=blocked_until,
            )
            self._connection.execute(
                """
                INSERT INTO auth_login_throttle (
                    actor_id, window_started_at_utc, failed_attempts,
                    blocked_until_utc
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(actor_id) DO UPDATE SET
                    window_started_at_utc = excluded.window_started_at_utc,
                    failed_attempts = excluded.failed_attempts,
                    blocked_until_utc = excluded.blocked_until_utc
                """,
                (
                    throttle.actor_id,
                    throttle.window_started_at_utc.isoformat(),
                    throttle.failed_attempts,
                    None
                    if throttle.blocked_until_utc is None
                    else throttle.blocked_until_utc.isoformat(),
                ),
            )
            self._connection.commit()
            return throttle
        except BaseException:
            self._connection.rollback()
            raise

    def clear_login_throttle(self, actor_id: str) -> None:
        self._connection.execute(
            "DELETE FROM auth_login_throttle WHERE actor_id = ?",
            (actor_id,),
        )
        self._connection.commit()


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        token_hash=str(row["token_hash"]),
        actor_id=str(row["actor_id"]),
        csrf_token=str(row["csrf_token"]),
        credential_fingerprint=str(row["credential_fingerprint"]),
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        last_seen_at_utc=datetime.fromisoformat(row["last_seen_at_utc"]),
        idle_expires_at_utc=datetime.fromisoformat(row["idle_expires_at_utc"]),
        absolute_expires_at_utc=datetime.fromisoformat(row["absolute_expires_at_utc"]),
    )
