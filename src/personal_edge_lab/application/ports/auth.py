"""Authentication persistence port."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from personal_edge_lab.domain.auth import LoginThrottle, SessionRecord


class AuthRepository(Protocol):
    def create_session(self, session: SessionRecord) -> None: ...

    def get_session(self, token_hash: str) -> SessionRecord | None: ...

    def touch_session(
        self,
        token_hash: str,
        *,
        last_seen_at_utc: datetime,
        idle_expires_at_utc: datetime,
    ) -> None: ...

    def revoke_session(self, token_hash: str) -> None: ...

    def revoke_all_sessions(self) -> None: ...

    def delete_expired_sessions(self, *, now: datetime) -> None: ...

    def get_login_throttle(self, actor_id: str) -> LoginThrottle | None: ...

    def save_login_throttle(self, throttle: LoginThrottle) -> None: ...

    def record_login_failure(
        self,
        *,
        actor_id: str,
        attempted_at: datetime,
        window_seconds: int,
        max_failures: int,
        block_seconds: int,
    ) -> LoginThrottle: ...

    def clear_login_throttle(self, actor_id: str) -> None: ...
