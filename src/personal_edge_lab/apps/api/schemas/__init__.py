"""Typed API contracts grouped by platform capability."""

from personal_edge_lab.apps.api.schemas.ac import (
    AcCommandRequest,
    AcCommandResponse,
    CommandAuditResponse,
    CommandHistoryResponse,
)
from personal_edge_lab.apps.api.schemas.auth import LoginRequest, SessionResponse
from personal_edge_lab.apps.api.schemas.email_triage import (
    TriageMessageDetailResponse,
    TriageMessageListResponse,
    TriageRunDetailResponse,
    TriageRunListResponse,
)
from personal_edge_lab.apps.api.schemas.operations import (
    AlertHealthResponse,
    AlertIncidentResponse,
    AlertListResponse,
    AlertStateResponse,
    CollectorHealthResponse,
    DatabaseHealthResponse,
    EdgeNodeHealthResponse,
    HealthResponse,
    LivenessResponse,
    TelemetryHealthResponse,
)
from personal_edge_lab.apps.api.schemas.telemetry import (
    TemperatureBucketResponse,
    TemperatureHistoryResponse,
    TemperatureReadingResponse,
    TemperatureSeriesResponse,
)

__all__ = [
    "AcCommandRequest",
    "AcCommandResponse",
    "AlertHealthResponse",
    "AlertIncidentResponse",
    "AlertListResponse",
    "AlertStateResponse",
    "CollectorHealthResponse",
    "CommandAuditResponse",
    "CommandHistoryResponse",
    "DatabaseHealthResponse",
    "EdgeNodeHealthResponse",
    "HealthResponse",
    "LivenessResponse",
    "LoginRequest",
    "SessionResponse",
    "TelemetryHealthResponse",
    "TemperatureBucketResponse",
    "TemperatureHistoryResponse",
    "TemperatureReadingResponse",
    "TemperatureSeriesResponse",
    "TriageMessageDetailResponse",
    "TriageMessageListResponse",
    "TriageRunDetailResponse",
    "TriageRunListResponse",
]
