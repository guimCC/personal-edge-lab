"""FastAPI composition root for the authenticated edge platform."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from personal_edge_lab import __version__
from personal_edge_lab.application.ports.ac import AcController
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.apps.api.context import ApiContext
from personal_edge_lab.apps.api.routers.ac import create_ac_router
from personal_edge_lab.apps.api.routers.auth import create_auth_router
from personal_edge_lab.apps.api.routers.dashboard import create_dashboard_router
from personal_edge_lab.apps.api.routers.operations import create_operations_router
from personal_edge_lab.apps.api.routers.telemetry import create_telemetry_router
from personal_edge_lab.apps.api.schemas.common import StoredDataError
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

LOGGER = logging.getLogger(__name__)
DASHBOARD_DIRECTORY = Path(__file__).parent / "static" / "dashboard"


def create_app(
    settings: Settings,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    token_generator: Callable[[], str] | None = None,
    ac_controller_factory: Callable[[], AcController] | None = None,
) -> FastAPI:
    context = ApiContext(
        settings,
        clock=clock,
        token_generator=token_generator,
        ac_controller_factory=ac_controller_factory,
    )

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
    _configure_error_handling(app)
    _configure_security_headers(app)
    _mount_dashboard_assets(app)
    app.include_router(create_auth_router(context))
    app.include_router(create_operations_router(context))
    app.include_router(create_telemetry_router(context))
    app.include_router(create_ac_router(context))
    app.include_router(create_dashboard_router(DASHBOARD_DIRECTORY))
    return app


def _configure_error_handling(app: FastAPI) -> None:
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

    @app.exception_handler(StoredDataError)
    async def stored_data_error_handler(
        _request: Request,
        error: StoredDataError,
    ) -> JSONResponse:
        LOGGER.error("API stored data validation failed", exc_info=error)
        return JSONResponse(
            status_code=503,
            content={"detail": "stored data unavailable"},
        )


def _configure_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def response_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


def _mount_dashboard_assets(app: FastAPI) -> None:
    assets_directory = DASHBOARD_DIRECTORY / "assets"
    if assets_directory.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_directory),
            name="dashboard-assets",
        )
