"""Liveness, platform health, and durable alert routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from personal_edge_lab import __version__
from personal_edge_lab.apps.api.context import ApiContext
from personal_edge_lab.apps.api.schemas import (
    AlertListResponse,
    HealthResponse,
    LivenessResponse,
)
from personal_edge_lab.apps.api.types import AlertLimit, DeviceId
from personal_edge_lab.domain.auth import AuthenticatedSession
from personal_edge_lab.infrastructure.persistence.sqlite.alert_queries import (
    SqliteAlertQueryRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.collector_status import (
    SqliteCollectorStatusRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.alerting import AlertHistoryFilter, GetOperationalAlerts
from personal_edge_lab.modules.platform_status import GetPlatformHealth


def create_operations_router(context: ApiContext) -> APIRouter:
    router = APIRouter()
    settings = context.settings

    @router.get(
        "/health/live",
        response_model=LivenessResponse,
        include_in_schema=False,
    )
    def liveness(request: Request) -> LivenessResponse:
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            raise HTTPException(status_code=404, detail="not found")
        return LivenessResponse(version=__version__)

    @router.get("/health", response_model=HealthResponse, tags=["health"])
    def health(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(context.require_session),
        ],
    ) -> HealthResponse:
        result = GetPlatformHealth(
            telemetry_repository_factory=lambda: SqliteTelemetryRepository(settings.database_path),
            collector_repository_factory=lambda: SqliteCollectorStatusRepository(
                settings.database_path
            ),
            alert_repository_factory=lambda: SqliteAlertQueryRepository(settings.database_path),
            device_id=settings.device_id,
            telemetry_stale_after_seconds=settings.telemetry_stale_after_seconds,
            collector_stale_after_seconds=settings.collector_stale_after_seconds,
            evaluator_stale_after_seconds=settings.alert_evaluator_stale_after_seconds,
            clock=context.clock,
        ).execute()
        return HealthResponse.from_application(result, version=__version__)

    @router.get(
        "/api/v1/alerts",
        response_model=AlertListResponse,
        tags=["alerts"],
    )
    def alerts(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(context.require_session),
        ],
        status: AlertHistoryFilter = AlertHistoryFilter.ALL,
        limit: AlertLimit = 20,
        device_id: DeviceId = None,
    ) -> AlertListResponse:
        checked_at = context.clock()
        overview = GetOperationalAlerts(
            lambda: SqliteAlertQueryRepository(settings.database_path),
            evaluator_stale_after_seconds=settings.alert_evaluator_stale_after_seconds,
            clock=lambda: checked_at,
        ).execute(
            device_id or settings.device_id,
            history_filter=status,
            limit=limit,
        )
        return AlertListResponse.from_application(overview, checked_at=checked_at)

    return router
