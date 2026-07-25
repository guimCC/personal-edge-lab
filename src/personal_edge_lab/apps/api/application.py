"""FastAPI composition root for the authenticated edge platform."""

import logging
import secrets
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pwdlib import PasswordHash

from personal_edge_lab import __version__
from personal_edge_lab.application.ports.ac import AcController
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.apps.api.schemas import (
    AcCommandRequest,
    AcCommandResponse,
    CollectorHealthResponse,
    CommandAuditResponse,
    CommandHistoryResponse,
    DatabaseHealthResponse,
    EdgeNodeHealthResponse,
    HealthResponse,
    LivenessResponse,
    LoginRequest,
    SessionResponse,
    TelemetryHealthResponse,
    TemperatureHistoryResponse,
    TemperatureReadingResponse,
    TemperatureSeriesResponse,
)
from personal_edge_lab.domain.ac import (
    AcMode,
    AcState,
    CommandRequestContext,
    ValidationError,
)
from personal_edge_lab.domain.auth import AuthenticatedSession
from personal_edge_lab.infrastructure.esp32.ac_controller import AcCommandClient
from personal_edge_lab.infrastructure.persistence.sqlite.auth import (
    SqliteAuthRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.collector_status import (
    SqliteCollectorStatusRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.authentication import (
    AuthenticationError,
    AuthenticationService,
    LoginRateLimited,
)
from personal_edge_lab.modules.home import (
    CommandConflictError,
    CommandInProgressError,
    CommandRateLimitedError,
    CommandService,
    DeviceBusyError,
    ListCommandHistory,
)
from personal_edge_lab.modules.telemetry import (
    GetLatestTemperature,
    GetOperationalHealth,
    GetTelemetryHealth,
    GetTemperatureSeries,
    ListTemperatureHistory,
    TelemetryFreshness,
    TelemetryWindow,
)

LOGGER = logging.getLogger(__name__)
DeviceId = Annotated[str | None, Query(pattern=r"\S")]
TelemetryLimit = Annotated[int, Query(ge=1, le=1000)]
CommandLimit = Annotated[int, Query(ge=1, le=100)]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=16,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
DASHBOARD_DIRECTORY = Path(__file__).parent / "static" / "dashboard"
SESSION_COOKIE = "__Host-pel_session"
DASHBOARD_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
    "form-action 'self'"
)


def create_app(
    settings: Settings,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    token_generator: Callable[[], str] | None = None,
    ac_controller_factory: Callable[[], AcController] | None = None,
) -> FastAPI:
    password_hasher = PasswordHash.recommended()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        run_migrations(settings.database_path)
        yield

    app = FastAPI(
        title="Personal Edge Lab API",
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )

    assets_directory = DASHBOARD_DIRECTORY / "assets"
    if assets_directory.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_directory),
            name="dashboard-assets",
        )

    @app.middleware("http")
    async def response_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(sqlite3.Error)
    async def database_error_handler(
        _request: Request,
        error: sqlite3.Error,
    ) -> JSONResponse:
        LOGGER.error("API database operation failed", exc_info=error)
        return JSONResponse(
            status_code=503,
            content={"detail": "database unavailable"},
        )

    def authentication_service(repository: SqliteAuthRepository) -> AuthenticationService:
        arguments: dict[str, object] = {}
        if token_generator is not None:
            arguments["token_generator"] = token_generator
        return AuthenticationService(
            repository,
            actor_id=settings.owner_id,
            verify_password=password_hasher.verify,
            idle_seconds=settings.session_idle_seconds,
            absolute_seconds=settings.session_absolute_seconds,
            max_failures=settings.login_max_failures,
            failure_window_seconds=settings.login_window_seconds,
            block_seconds=settings.login_block_seconds,
            clock=clock,
            **arguments,
        )

    def read_password_hash() -> str:
        try:
            password_hash = settings.password_hash_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            LOGGER.error("Owner credential could not be read")
            raise HTTPException(status_code=503, detail="authentication unavailable") from error
        if not password_hash:
            raise HTTPException(status_code=503, detail="authentication unavailable")
        return password_hash

    def current_session(request: Request) -> AuthenticatedSession | None:
        if not settings.auth_enabled:
            return None
        with SqliteAuthRepository(settings.database_path) as repository:
            return authentication_service(repository).authenticate(
                request.cookies.get(SESSION_COOKIE),
                read_password_hash(),
            )

    def require_session(request: Request) -> AuthenticatedSession | None:
        session = current_session(request)
        if settings.auth_enabled and session is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return session

    def require_csrf(
        request: Request,
        session: Annotated[AuthenticatedSession | None, Depends(require_session)],
    ) -> AuthenticatedSession:
        if session is None:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        supplied_token = request.headers.get("x-csrf-token")
        if (
            origin != settings.public_origin
            or fetch_site not in {"same-origin", "same-site", "none"}
            or supplied_token is None
            or not secrets.compare_digest(supplied_token, session.csrf_token)
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        return session

    def require_command_csrf(
        session: Annotated[AuthenticatedSession, Depends(require_csrf)],
    ) -> AuthenticatedSession:
        if not settings.ac_control_enabled:
            raise HTTPException(status_code=404, detail="not found")
        return session

    @app.get(
        "/health/live",
        response_model=LivenessResponse,
        include_in_schema=False,
    )
    def liveness(request: Request) -> LivenessResponse:
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            raise HTTPException(status_code=404, detail="not found")
        return LivenessResponse(version=__version__)

    @app.get(
        "/api/v1/auth/session",
        response_model=SessionResponse,
        tags=["authentication"],
    )
    def auth_session(request: Request, response: Response) -> SessionResponse:
        if not settings.auth_enabled:
            return SessionResponse(
                authenticated=False,
                auth_enabled=False,
                controls_enabled=False,
            )
        session = current_session(request)
        if session is None:
            _clear_session_cookie(response)
            return SessionResponse(
                authenticated=False,
                auth_enabled=True,
                controls_enabled=settings.ac_control_enabled,
            )
        return SessionResponse(
            authenticated=True,
            auth_enabled=True,
            controls_enabled=settings.ac_control_enabled,
            actor_id=session.actor_id,
            csrf_token=session.csrf_token,
            idle_expires_at_utc=session.idle_expires_at_utc,
            absolute_expires_at_utc=session.absolute_expires_at_utc,
        )

    @app.post(
        "/api/v1/auth/login",
        response_model=SessionResponse,
        tags=["authentication"],
    )
    def login(body: LoginRequest, response: Response) -> SessionResponse:
        if not settings.auth_enabled:
            raise HTTPException(status_code=404, detail="not found")
        with SqliteAuthRepository(settings.database_path) as repository:
            try:
                result = authentication_service(repository).login(
                    body.password,
                    read_password_hash(),
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
        return SessionResponse(
            authenticated=True,
            auth_enabled=True,
            controls_enabled=settings.ac_control_enabled,
            actor_id=result.session.actor_id,
            csrf_token=result.session.csrf_token,
            idle_expires_at_utc=result.session.idle_expires_at_utc,
            absolute_expires_at_utc=result.session.absolute_expires_at_utc,
        )

    @app.post(
        "/api/v1/auth/logout",
        status_code=204,
        tags=["authentication"],
    )
    def logout(
        request: Request,
        response: Response,
        _session: Annotated[AuthenticatedSession, Depends(require_csrf)],
    ) -> None:
        with SqliteAuthRepository(settings.database_path) as repository:
            authentication_service(repository).logout(request.cookies.get(SESSION_COOKIE))
        _clear_session_cookie(response)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(require_session),
        ],
    ) -> HealthResponse:
        checked_at = clock()
        with SqliteTelemetryRepository(settings.database_path) as repository:
            telemetry = GetTelemetryHealth(
                repository,
                device_id=settings.device_id,
                stale_after_seconds=settings.telemetry_stale_after_seconds,
                clock=lambda: checked_at,
            ).execute()
        with SqliteCollectorStatusRepository(settings.database_path) as repository:
            operational = GetOperationalHealth(
                repository,
                device_id=settings.device_id,
                stale_after_seconds=settings.collector_stale_after_seconds,
                clock=lambda: checked_at,
            ).execute()
        overall = (
            "healthy"
            if (
                telemetry.status is TelemetryFreshness.FRESH
                and operational.collector.status.value == "running"
                and operational.edge_node.status.value == "reachable"
            )
            else "degraded"
        )
        return HealthResponse(
            status=overall,
            version=__version__,
            checked_at_utc=checked_at,
            database=DatabaseHealthResponse(),
            telemetry=TelemetryHealthResponse.from_application(telemetry),
            collector=CollectorHealthResponse.from_application(operational.collector),
            edge_node=EdgeNodeHealthResponse.from_application(operational.edge_node),
        )

    @app.get(
        "/api/v1/telemetry/latest",
        response_model=TemperatureReadingResponse,
        tags=["telemetry"],
    )
    def latest_temperature(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(require_session),
        ],
        device_id: DeviceId = None,
    ) -> TemperatureReadingResponse:
        selected_device = device_id or settings.device_id
        with SqliteTelemetryRepository(settings.database_path) as repository:
            reading = GetLatestTemperature(repository).execute(selected_device)
        if reading is None:
            raise HTTPException(
                status_code=404,
                detail="no telemetry reading found for device",
            )
        return TemperatureReadingResponse.from_domain(reading)

    @app.get(
        "/api/v1/telemetry/history",
        response_model=TemperatureHistoryResponse,
        tags=["telemetry"],
    )
    def telemetry_history(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(require_session),
        ],
        limit: TelemetryLimit = 100,
        device_id: DeviceId = None,
    ) -> TemperatureHistoryResponse:
        selected_device = device_id or settings.device_id
        with SqliteTelemetryRepository(settings.database_path) as repository:
            readings = ListTemperatureHistory(repository).execute(
                selected_device,
                limit=limit,
            )
        items = [TemperatureReadingResponse.from_domain(reading) for reading in readings]
        return TemperatureHistoryResponse(count=len(items), limit=limit, items=items)

    @app.get(
        "/api/v1/telemetry/series",
        response_model=TemperatureSeriesResponse,
        tags=["telemetry"],
    )
    def telemetry_series(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(require_session),
        ],
        window: TelemetryWindow = TelemetryWindow.SIX_HOURS,
        device_id: DeviceId = None,
    ) -> TemperatureSeriesResponse:
        selected_device = device_id or settings.device_id
        with SqliteTelemetryRepository(settings.database_path) as repository:
            series = GetTemperatureSeries(
                repository,
                clock=clock,
            ).execute(selected_device, window=window)
        return TemperatureSeriesResponse.from_application(series)

    @app.get(
        "/api/v1/ac/history",
        response_model=CommandHistoryResponse,
        tags=["air conditioner"],
    )
    def command_history(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(require_session),
        ],
        limit: CommandLimit = 20,
    ) -> CommandHistoryResponse:
        with SqliteCommandAuditRepository(settings.database_path) as repository:
            entries = ListCommandHistory(repository).execute(limit=limit)
        items = [CommandAuditResponse.from_domain(entry) for entry in entries]
        return CommandHistoryResponse(count=len(items), limit=limit, items=items)

    @app.post(
        "/api/v1/ac/commands",
        response_model=AcCommandResponse,
        responses={
            200: {"model": AcCommandResponse},
            409: {"description": "Idempotency conflict or command in progress"},
            429: {"description": "Command rate limit exceeded"},
        },
        tags=["air conditioner"],
        include_in_schema=settings.ac_control_enabled,
    )
    def ac_command(
        body: AcCommandRequest,
        idempotency_key: IdempotencyKey,
        session: Annotated[AuthenticatedSession, Depends(require_command_csrf)],
    ) -> JSONResponse:
        if not settings.ac_control_enabled:
            raise HTTPException(status_code=404, detail="not found")
        context = CommandRequestContext(
            actor_id=session.actor_id,
            request_source="dashboard",
            idempotency_key=idempotency_key,
            rate_limit=settings.command_rate_limit_per_minute,
            rate_window_seconds=60,
            lock_lease_seconds=settings.ac_command_timeout_seconds + 10,
        )
        controller = (
            ac_controller_factory()
            if ac_controller_factory is not None
            else AcCommandClient(
                base_url=settings.ac_node_base_url,
                timeout_seconds=settings.ac_command_timeout_seconds,
            )
        )
        should_close = ac_controller_factory is None
        try:
            with SqliteCommandAuditRepository(settings.database_path) as repository:
                service = CommandService(
                    device_id=settings.device_id,
                    controller=controller,
                    audit_repository=repository,
                    context=context,
                    clock=clock,
                )
                execution = _execute_browser_command(service, body)
                entry = repository.get(execution.command_id)
                if entry is None:
                    raise sqlite3.DatabaseError("command audit record was not found")
        except CommandConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (CommandInProgressError, DeviceBusyError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CommandRateLimitedError as error:
            raise HTTPException(
                status_code=429,
                detail="command rate limit exceeded",
                headers={"Retry-After": str(error.retry_after_seconds)},
            ) from error
        finally:
            if should_close:
                close = getattr(controller, "close", None)
                if callable(close):
                    close()
        response = AcCommandResponse(
            audit=CommandAuditResponse.from_domain(entry),
            replayed=execution.replayed,
        )
        return JSONResponse(
            status_code=200 if execution.replayed else 201,
            content=response.model_dump(mode="json"),
        )

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        index = DASHBOARD_DIRECTORY / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail="dashboard unavailable")
        return FileResponse(
            index,
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": DASHBOARD_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    return app


def _execute_browser_command(
    service: CommandService,
    body: AcCommandRequest,
):
    attempted_payload = body.model_dump(exclude_none=True)
    if body.command_type == "power_off":
        if body.state is not None:
            return service.reject(
                command_type=body.command_type,
                attempted_payload=attempted_payload,
                message="power_off must not include state",
            )
        return service.power_off()
    if body.command_type != "set_state":
        return service.reject(
            command_type=body.command_type,
            attempted_payload=attempted_payload,
            message="command_type must be set_state or power_off",
        )
    if body.state is None:
        return service.reject(
            command_type=body.command_type,
            attempted_payload=attempted_payload,
            message="set_state requires state",
        )
    expected_fields = {
        "power",
        "temperature_c",
        "mode",
        "fan",
        "vertical_vane",
    }
    if set(body.state) != expected_fields:
        return service.reject(
            command_type=body.command_type,
            attempted_payload=attempted_payload,
            message="set_state requires exactly power, temperature_c, mode, fan, and vertical_vane",
        )
    try:
        state = AcState.from_values(
            power=body.state.get("power"),
            temperature_c=body.state.get("temperature_c"),
            mode=body.state.get("mode"),
            fan=body.state.get("fan"),
            vertical_vane=body.state.get("vertical_vane"),
        )
        if not state.power:
            raise ValidationError("set_state requires power=true")
        if state.mode is not AcMode.COOL:
            raise ValidationError("browser controls currently authorize only cool mode")
    except ValidationError as error:
        return service.reject(
            command_type=body.command_type,
            attempted_payload=attempted_payload,
            message=str(error),
        )
    return service.set_state(state)


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
