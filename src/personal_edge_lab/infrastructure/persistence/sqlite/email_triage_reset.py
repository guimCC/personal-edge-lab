"""Explicit, backed-up reset for disposable email-triage development data."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection

RESET_CONFIRMATION = "DELETE-ALL-EMAIL-TRIAGE-DATA"
TRIAGE_TABLES = (
    "email_triage_evaluation_content",
    "email_triage_attempts",
    "email_triage_run_items",
    "email_triage_evaluations",
    "email_triage_content_snapshots",
    "email_triage_messages",
    "email_triage_runs",
)


class TriageDevelopmentResetError(RuntimeError):
    """Sanitized failure for the explicitly destructive development reset."""


@dataclass(frozen=True, slots=True)
class TriageDevelopmentResetResult:
    backup_path: Path
    deleted_counts: dict[str, int]


def reset_triage_development_data(
    database_path: Path,
    *,
    confirmation: str,
    now: datetime,
) -> TriageDevelopmentResetResult:
    if confirmation != RESET_CONFIRMATION:
        raise TriageDevelopmentResetError("exact reset confirmation is required")
    database_path = database_path.resolve()
    backup_directory = database_path.parent / "backups"
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_directory / f"{database_path.stem}-triage-reset-{stamp}.db"
    if backup_path.exists():
        raise TriageDevelopmentResetError("triage reset backup already exists")

    with open_connection(database_path) as source:
        unfinished = int(
            source.execute(
                """
                SELECT COUNT(*) FROM email_triage_runs
                WHERE status IN ('requested', 'retrieving', 'classifying')
                """
            ).fetchone()[0]
        )
        if unfinished:
            raise TriageDevelopmentResetError("unfinished triage work prevents reset")
        backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(backup_directory, 0o700)
        with sqlite3.connect(backup_path) as backup:
            source.backup(backup)
        os.chmod(backup_path, 0o600)

        source.execute("BEGIN IMMEDIATE")
        try:
            unfinished = int(
                source.execute(
                    """
                    SELECT COUNT(*) FROM email_triage_runs
                    WHERE status IN ('requested', 'retrieving', 'classifying')
                    """
                ).fetchone()[0]
            )
            if unfinished:
                raise TriageDevelopmentResetError("unfinished triage work prevents reset")
            deleted_counts = {
                table: int(source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in TRIAGE_TABLES
            }
            for table in TRIAGE_TABLES:
                source.execute(f"DELETE FROM {table}")
            source.commit()
        except BaseException:
            source.rollback()
            raise

    return TriageDevelopmentResetResult(
        backup_path=backup_path,
        deleted_counts=deleted_counts,
    )
