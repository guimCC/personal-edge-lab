"""Owner authentication routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from personal_edge_lab.apps.api.context import SESSION_COOKIE, ApiContext
from personal_edge_lab.apps.api.schemas import LoginRequest, SessionResponse
from personal_edge_lab.domain.auth import AuthenticatedSession
from personal_edge_lab.infrastructure.persistence.sqlite.auth import SqliteAuthRepository
from personal_edge_lab.modules.authentication import AuthenticationError, LoginRateLimited


def create_auth_router(context: ApiContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
    settings = context.settings

    @router.get("/session", response_model=SessionResponse)
    def auth_session(request: Request, response: Response) -> SessionResponse:
        if not settings.auth_enabled:
            return SessionResponse(
                authenticated=False,
                auth_enabled=False,
                controls_enabled=False,
                email_triage_workspace_enabled=False,
                email_triage_review_enabled=False,
            )
        session = context.current_session(request)
        if session is None:
            clear_session_cookie(response)
            return SessionResponse(
                authenticated=False,
                auth_enabled=True,
                controls_enabled=settings.ac_control_enabled,
                email_triage_workspace_enabled=False,
                email_triage_review_enabled=False,
            )
        return _session_response(
            session,
            controls_enabled=settings.ac_control_enabled,
            email_triage_workspace_enabled=settings.triage_workspace_enabled,
        )

    @router.post("/login", response_model=SessionResponse)
    def login(body: LoginRequest, response: Response) -> SessionResponse:
        if not settings.auth_enabled:
            raise HTTPException(status_code=404, detail="not found")
        with SqliteAuthRepository(settings.database_path) as repository:
            try:
                result = context.authentication_service(repository).login(
                    body.password,
                    context.read_password_hash(),
                )
            except LoginRateLimited as error:
                raise HTTPException(
                    status_code=429,
                    detail="too many login attempts",
                    headers={"Retry-After": str(error.retry_after_seconds)},
                ) from error
            except AuthenticationError as error:
                raise HTTPException(
                    status_code=401,
                    detail="invalid credentials",
                ) from error
        response.set_cookie(
            SESSION_COOKIE,
            result.raw_session_token,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
            max_age=None,
        )
        return _session_response(
            result.session,
            controls_enabled=settings.ac_control_enabled,
            email_triage_workspace_enabled=settings.triage_workspace_enabled,
        )

    @router.post("/logout", status_code=204)
    def logout(
        request: Request,
        response: Response,
        _session: Annotated[
            AuthenticatedSession,
            Depends(context.require_csrf),
        ],
    ) -> None:
        with SqliteAuthRepository(settings.database_path) as repository:
            context.authentication_service(repository).logout(request.cookies.get(SESSION_COOKIE))
        clear_session_cookie(response)

    return router


def _session_response(
    session: AuthenticatedSession,
    *,
    controls_enabled: bool,
    email_triage_workspace_enabled: bool,
) -> SessionResponse:
    return SessionResponse(
        authenticated=True,
        auth_enabled=True,
        controls_enabled=controls_enabled,
        email_triage_workspace_enabled=email_triage_workspace_enabled,
        email_triage_review_enabled=email_triage_workspace_enabled,
        actor_id=session.actor_id,
        csrf_token=session.csrf_token,
        idle_expires_at_utc=session.idle_expires_at_utc,
        absolute_expires_at_utc=session.absolute_expires_at_utc,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
