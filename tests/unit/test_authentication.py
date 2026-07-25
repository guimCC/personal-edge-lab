from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pwdlib import PasswordHash

from personal_edge_lab.infrastructure.persistence.sqlite.auth import (
    SqliteAuthRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.authentication import (
    AuthenticationError,
    AuthenticationService,
    LoginRateLimited,
)

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)


def service(database, now, tokens) -> tuple[SqliteAuthRepository, AuthenticationService]:
    repository = SqliteAuthRepository(database)
    return repository, AuthenticationService(
        repository,
        actor_id="owner",
        verify_password=PasswordHash.recommended().verify,
        idle_seconds=86_400,
        absolute_seconds=604_800,
        max_failures=5,
        failure_window_seconds=900,
        block_seconds=900,
        clock=lambda: now[0],
        token_generator=lambda: next(tokens),
    )


def test_session_uses_hashed_token_and_exact_expiry_boundaries(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    now = [NOW]
    password_hash = PasswordHash.recommended().hash("fourteen-chars!")
    repository, authentication = service(
        database,
        now,
        iter(("raw-session-token", "csrf-token")),
    )
    try:
        result = authentication.login("fourteen-chars!", password_hash)
        assert repository.get_session("raw-session-token") is None
        assert (
            authentication.authenticate(
                result.raw_session_token,
                password_hash,
            )
            is not None
        )

        now[0] = NOW + timedelta(seconds=86_400)
        assert (
            authentication.authenticate(
                result.raw_session_token,
                password_hash,
            )
            is None
        )
    finally:
        repository.close()


def test_credential_rotation_revokes_session_on_next_use(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    now = [NOW]
    hasher = PasswordHash.recommended()
    first_hash = hasher.hash("fourteen-chars!")
    second_hash = hasher.hash("another-secret!")
    repository, authentication = service(
        database,
        now,
        iter(("session-token", "csrf-token")),
    )
    try:
        result = authentication.login("fourteen-chars!", first_hash)
        assert authentication.authenticate(result.raw_session_token, second_hash) is None
    finally:
        repository.close()


def test_fifth_failure_is_durably_rate_limited(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    now = [NOW]
    password_hash = PasswordHash.recommended().hash("fourteen-chars!")
    repository, authentication = service(database, now, iter(()))
    try:
        for _ in range(4):
            with pytest.raises(AuthenticationError):
                authentication.login("wrong-password", password_hash)
        with pytest.raises(LoginRateLimited) as blocked:
            authentication.login("wrong-password", password_hash)
        assert blocked.value.retry_after_seconds == 900
    finally:
        repository.close()

    other_repository, after_restart = service(database, now, iter(()))
    try:
        with pytest.raises(LoginRateLimited):
            after_restart.login("fourteen-chars!", password_hash)
    finally:
        other_repository.close()


def test_concurrent_failures_cannot_bypass_durable_throttle(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    now = [NOW]
    password_hash = PasswordHash.recommended().hash("fourteen-chars!")

    def fail_login(_index: int) -> type[BaseException]:
        repository, authentication = service(database, now, iter(()))
        try:
            authentication.login("wrong-password", password_hash)
        except BaseException as error:
            return type(error)
        finally:
            repository.close()
        raise AssertionError("invalid login unexpectedly succeeded")

    with ThreadPoolExecutor(max_workers=5) as pool:
        errors = list(pool.map(fail_login, range(5)))

    assert errors.count(LoginRateLimited) == 1
    assert errors.count(AuthenticationError) == 4
    with SqliteAuthRepository(database) as repository:
        throttle = repository.get_login_throttle("owner")
    assert throttle is not None
    assert throttle.failed_attempts == 5
    assert throttle.blocked_until_utc == NOW + timedelta(seconds=900)
