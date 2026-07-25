"""FastAPI composition root for read-only platform queries."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from personal_edge_lab import __version__
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.apps.api.schemas import (
    CollectorHealthResponse,
    CommandAuditResponse,
    CommandHistoryResponse,
    DatabaseHealthResponse,
    EdgeNodeHealthResponse,
    HealthResponse,
    TelemetryHealthResponse,
    TemperatureHistoryResponse,
    TemperatureReadingResponse,
    TemperatureSeriesResponse,
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
from personal_edge_lab.modules.home import ListCommandHistory
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
DASHBOARD_DIRECTORY = Path(__file__).parent / "static" / "dashboard"
DASHBOARD_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)


def create_app(
    settings: Settings,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
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
    async def dashboard_asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
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
    def latest_temperature(device_id: DeviceId = None) -> TemperatureReadingResponse:
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
    def command_history(limit: CommandLimit = 20) -> CommandHistoryResponse:
        with SqliteCommandAuditRepository(settings.database_path) as repository:
            entries = ListCommandHistory(repository).execute(limit=limit)
        items = [CommandAuditResponse.from_domain(entry) for entry in entries]
        return CommandHistoryResponse(count=len(items), limit=limit, items=items)

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
