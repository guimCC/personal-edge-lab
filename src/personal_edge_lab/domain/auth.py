"""Authentication session and login-throttle domain records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SessionRecord:
    token_hash: str
    actor_id: str
    csrf_token: str
    credential_fingerprint: str
    created_at_utc: datetime
    last_seen_at_utc: datetime
    idle_expires_at_utc: datetime
    absolute_expires_at_utc: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    actor_id: str
    csrf_token: str
    idle_expires_at_utc: datetime
    absolute_expires_at_utc: datetime


@dataclass(frozen=True, slots=True)
class LoginThrottle:
    actor_id: str
    window_started_at_utc: datetime
    failed_attempts: int
    blocked_until_utc: datetime | None
