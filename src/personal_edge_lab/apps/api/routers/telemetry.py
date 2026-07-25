"""Stored telemetry routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from personal_edge_lab.apps.api.context import ApiContext
from personal_edge_lab.apps.api.schemas import (
    TemperatureHistoryResponse,
    TemperatureReadingResponse,
    TemperatureSeriesResponse,
)
from personal_edge_lab.apps.api.types import DeviceId, TelemetryLimit
from personal_edge_lab.domain.auth import AuthenticatedSession
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.telemetry import (
    GetLatestTemperature,
    GetTemperatureSeries,
    ListTemperatureHistory,
    TelemetryWindow,
)


def create_telemetry_router(context: ApiContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])
    settings = context.settings

    @router.get("/latest", response_model=TemperatureReadingResponse)
    def latest_temperature(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(context.require_session),
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

    @router.get("/history", response_model=TemperatureHistoryResponse)
    def telemetry_history(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(context.require_session),
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

    @router.get("/series", response_model=TemperatureSeriesResponse)
    def telemetry_series(
        _session: Annotated[
            AuthenticatedSession | None,
            Depends(context.require_session),
        ],
        window: TelemetryWindow = TelemetryWindow.SIX_HOURS,
        device_id: DeviceId = None,
    ) -> TemperatureSeriesResponse:
        selected_device = device_id or settings.device_id
        with SqliteTelemetryRepository(settings.database_path) as repository:
            series = GetTemperatureSeries(
                repository,
                clock=context.clock,
            ).execute(selected_device, window=window)
        return TemperatureSeriesResponse.from_application(series)

    return router
