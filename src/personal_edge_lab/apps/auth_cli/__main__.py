"""Local owner credential administration entry point."""

from __future__ import annotations

import argparse
import getpass
import os
import tempfile
from pathlib import Path

from pwdlib import PasswordHash

from personal_edge_lab.infrastructure.persistence.sqlite.auth import (
    SqliteAuthRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

MINIMUM_PASSWORD_LENGTH = 14


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the dashboard owner credential")
    parser.add_argument(
        "command",
        choices=("set-password", "revoke-sessions"),
    )
    args = parser.parse_args(argv)
    database_path = Path(os.getenv("DATABASE_PATH", "./data/telemetry.db")).expanduser()
    password_hash_path = Path(
        os.getenv(
            "AUTH_PASSWORD_HASH_FILE",
            "./secrets/owner-password.hash",
        )
    ).expanduser()
    run_migrations(database_path)

    if args.command == "set-password":
        password = getpass.getpass("New owner password: ")
        confirmation = getpass.getpass("Repeat owner password: ")
        if password != confirmation:
            parser.error("passwords do not match")
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            parser.error(f"password must contain at least {MINIMUM_PASSWORD_LENGTH} characters")
        password_hash = PasswordHash.recommended().hash(password)
        _write_private_file(password_hash_path, f"{password_hash}\n")
        with SqliteAuthRepository(database_path) as repository:
            repository.revoke_all_sessions()
        print("Owner password updated; all dashboard sessions were revoked.")
        return 0

    with SqliteAuthRepository(database_path) as repository:
        repository.revoke_all_sessions()
    print("All dashboard sessions were revoked.")
    return 0


def _write_private_file(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
        path.chmod(0o600)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
