"""Explicit runtime dependencies shared by API routers."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException, Request
from pwdlib import PasswordHash

from personal_edge_lab.application.ports.ac import AcController
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.domain.auth import AuthenticatedSession
from personal_edge_lab.infrastructure.persistence.sqlite.auth import SqliteAuthRepository
from personal_edge_lab.modules.authentication import AuthenticationService

LOGGER = logging.getLogger(__name__)
SESSION_COOKIE = "__Host-pel_session"


class ApiContext:
    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], datetime],
        token_generator: Callable[[], str] | None,
        ac_controller_factory: Callable[[], AcController] | None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.token_generator = token_generator
        self.ac_controller_factory = ac_controller_factory
        self.password_hasher = PasswordHash.recommended()

    def authentication_service(
        self,
        repository: SqliteAuthRepository,
    ) -> AuthenticationService:
        arguments = {
            "actor_id": self.settings.owner_id,
            "verify_password": self.password_hasher.verify,
            "idle_seconds": self.settings.session_idle_seconds,
            "absolute_seconds": self.settings.session_absolute_seconds,
            "max_failures": self.settings.login_max_failures,
            "failure_window_seconds": self.settings.login_window_seconds,
            "block_seconds": self.settings.login_block_seconds,
            "clock": self.clock,
        }
        if self.token_generator is None:
            return AuthenticationService(repository, **arguments)
        return AuthenticationService(
            repository,
            token_generator=self.token_generator,
            **arguments,
        )

    def read_password_hash(self) -> str:
        try:
            password_hash = self.settings.password_hash_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            LOGGER.error("Owner credential could not be read")
            raise HTTPException(
                status_code=503,
                detail="authentication unavailable",
            ) from error
        if not password_hash:
            raise HTTPException(status_code=503, detail="authentication unavailable")
        return password_hash

    def current_session(self, request: Request) -> AuthenticatedSession | None:
        if not self.settings.auth_enabled:
            return None
        with SqliteAuthRepository(self.settings.database_path) as repository:
            return self.authentication_service(repository).authenticate(
                request.cookies.get(SESSION_COOKIE),
                self.read_password_hash(),
            )

    def require_session(self, request: Request) -> AuthenticatedSession | None:
        session = self.current_session(request)
        if self.settings.auth_enabled and session is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return session

    def require_triage_workspace(self, request: Request) -> AuthenticatedSession | None:
        if not self.settings.triage_workspace_enabled:
            raise HTTPException(status_code=404, detail="not found")
        return self.require_session(request)

    def require_triage_review(self, request: Request) -> AuthenticatedSession | None:
        """Compatibility alias for the 0.14 review dependency."""
        return self.require_triage_workspace(request)

    def require_csrf(
        self,
        request: Request,
    ) -> AuthenticatedSession:
        return self.validate_csrf(request, self.require_session(request))

    def validate_csrf(
        self,
        request: Request,
        session: AuthenticatedSession | None,
    ) -> AuthenticatedSession:
        if session is None:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        supplied_token = request.headers.get("x-csrf-token")
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if (
            origin != self.settings.public_origin
            or fetch_site not in {"same-origin", "same-site", "none"}
            or supplied_token is None
            or not secrets.compare_digest(supplied_token, session.csrf_token)
            or content_type.strip().lower() != "application/json"
        ):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        return session

    def require_command_csrf(self, request: Request) -> AuthenticatedSession:
        if not self.settings.ac_control_enabled:
            raise HTTPException(status_code=404, detail="not found")
        return self.validate_csrf(request, self.require_session(request))

    def require_triage_feedback_csrf(self, request: Request) -> AuthenticatedSession:
        if not self.settings.email_triage_feedback_enabled:
            raise HTTPException(status_code=404, detail="not found")
        return self.validate_csrf(request, self.require_session(request))
