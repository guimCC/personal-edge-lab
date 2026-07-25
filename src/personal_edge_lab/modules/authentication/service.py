"""Framework-independent single-owner authentication."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from math import ceil

from personal_edge_lab.application.ports.auth import AuthRepository
from personal_edge_lab.domain.auth import (
    AuthenticatedSession,
    SessionRecord,
)

SESSION_TOUCH_INTERVAL_SECONDS = 300


class AuthenticationError(ValueError):
    """Raised when owner authentication fails."""


class LoginRateLimited(AuthenticationError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many login attempts")
        self.retry_after_seconds = max(1, retry_after_seconds)


@dataclass(frozen=True, slots=True)
class LoginResult:
    raw_session_token: str
    session: AuthenticatedSession


class AuthenticationService:
    def __init__(
        self,
        repository: AuthRepository,
        *,
        actor_id: str,
        verify_password: Callable[[str, str], bool],
        idle_seconds: int,
        absolute_seconds: int,
        max_failures: int,
        failure_window_seconds: int,
        block_seconds: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_generator: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self._repository = repository
        self._actor_id = actor_id
        self._verify_password = verify_password
        self._idle_seconds = idle_seconds
        self._absolute_seconds = absolute_seconds
        self._max_failures = max_failures
        self._failure_window_seconds = failure_window_seconds
        self._block_seconds = block_seconds
        self._clock = clock
        self._token_generator = token_generator

    def login(self, password: str, password_hash: str) -> LoginResult:
        now = self._clock()
        self._repository.delete_expired_sessions(now=now)
        throttle = self._repository.get_login_throttle(self._actor_id)
        if throttle is not None and throttle.blocked_until_utc is not None:
            if now < throttle.blocked_until_utc:
                raise LoginRateLimited(ceil((throttle.blocked_until_utc - now).total_seconds()))
            throttle = None
            self._repository.clear_login_throttle(self._actor_id)

        if not self._verify_password(password, password_hash):
            blocked_until = self._record_failure(now)
            if blocked_until is not None:
                raise LoginRateLimited(ceil((blocked_until - now).total_seconds()))
            raise AuthenticationError("invalid credentials")

        self._repository.clear_login_throttle(self._actor_id)
        raw_token = self._token_generator()
        csrf_token = self._token_generator()
        absolute_expiry = now + timedelta(seconds=self._absolute_seconds)
        idle_expiry = min(
            now + timedelta(seconds=self._idle_seconds),
            absolute_expiry,
        )
        record = SessionRecord(
            token_hash=_token_hash(raw_token),
            actor_id=self._actor_id,
            csrf_token=csrf_token,
            credential_fingerprint=_credential_fingerprint(password_hash),
            created_at_utc=now,
            last_seen_at_utc=now,
            idle_expires_at_utc=idle_expiry,
            absolute_expires_at_utc=absolute_expiry,
        )
        self._repository.create_session(record)
        return LoginResult(raw_token, _authenticated(record))

    def authenticate(
        self,
        raw_token: str | None,
        password_hash: str,
    ) -> AuthenticatedSession | None:
        if not raw_token:
            return None
        token_hash = _token_hash(raw_token)
        record = self._repository.get_session(token_hash)
        if record is None:
            return None

        now = self._clock()
        credentials_changed = not compare_digest(
            record.credential_fingerprint,
            _credential_fingerprint(password_hash),
        )
        if (
            credentials_changed
            or now >= record.idle_expires_at_utc
            or now >= record.absolute_expires_at_utc
        ):
            self._repository.revoke_session(token_hash)
            return None

        if (now - record.last_seen_at_utc).total_seconds() >= SESSION_TOUCH_INTERVAL_SECONDS:
            idle_expiry = min(
                now + timedelta(seconds=self._idle_seconds),
                record.absolute_expires_at_utc,
            )
            self._repository.touch_session(
                token_hash,
                last_seen_at_utc=now,
                idle_expires_at_utc=idle_expiry,
            )
            record = SessionRecord(
                token_hash=record.token_hash,
                actor_id=record.actor_id,
                csrf_token=record.csrf_token,
                credential_fingerprint=record.credential_fingerprint,
                created_at_utc=record.created_at_utc,
                last_seen_at_utc=now,
                idle_expires_at_utc=idle_expiry,
                absolute_expires_at_utc=record.absolute_expires_at_utc,
            )
        return _authenticated(record)

    def logout(self, raw_token: str | None) -> None:
        if raw_token:
            self._repository.revoke_session(_token_hash(raw_token))

    def revoke_all(self) -> None:
        self._repository.revoke_all_sessions()

    def _record_failure(
        self,
        now: datetime,
    ) -> datetime | None:
        throttle = self._repository.record_login_failure(
            actor_id=self._actor_id,
            attempted_at=now,
            window_seconds=self._failure_window_seconds,
            max_failures=self._max_failures,
            block_seconds=self._block_seconds,
        )
        return throttle.blocked_until_utc


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _credential_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()


def _authenticated(record: SessionRecord) -> AuthenticatedSession:
    return AuthenticatedSession(
        actor_id=record.actor_id,
        csrf_token=record.csrf_token,
        idle_expires_at_utc=record.idle_expires_at_utc,
        absolute_expires_at_utc=record.absolute_expires_at_utc,
    )
