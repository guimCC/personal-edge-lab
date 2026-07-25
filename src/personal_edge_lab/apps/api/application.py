"""FastAPI composition root for read-only platform queries."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from personal_edge_lab import __version__
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.apps.api.schemas import (
    CommandAuditResponse,
    CommandHistoryResponse,
    DatabaseHealthResponse,
    HealthResponse,
    TelemetryHealthResponse,
    TemperatureHistoryResponse,
    TemperatureReadingResponse,
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
    GetTelemetryHealth,
    ListTemperatureHistory,
    TelemetryFreshness,
)

LOGGER = logging.getLogger(__name__)
DeviceId = Annotated[str | None, Query(pattern=r"\S")]
TelemetryLimit = Annotated[int, Query(ge=1, le=1000)]
CommandLimit = Annotated[int, Query(ge=1, le=100)]


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
        overall = "healthy" if telemetry.status is TelemetryFreshness.FRESH else "degraded"
        return HealthResponse(
            status=overall,
            version=__version__,
            checked_at_utc=checked_at,
            database=DatabaseHealthResponse(),
            telemetry=TelemetryHealthResponse.from_application(telemetry),
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
        "/api/v1/ac/history",
        response_model=CommandHistoryResponse,
        tags=["air conditioner"],
    )
    def command_history(limit: CommandLimit = 20) -> CommandHistoryResponse:
        with SqliteCommandAuditRepository(settings.database_path) as repository:
            entries = ListCommandHistory(repository).execute(limit=limit)
        items = [CommandAuditResponse.from_domain(entry) for entry in entries]
        return CommandHistoryResponse(count=len(items), limit=limit, items=items)

    return app
