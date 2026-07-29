"""Owner authentication contracts."""

from datetime import datetime

from pydantic import ConfigDict, Field

from personal_edge_lab.apps.api.schemas.common import ApiModel


class SessionResponse(ApiModel):
    authenticated: bool
    auth_enabled: bool
    controls_enabled: bool
    email_triage_workspace_enabled: bool = False
    email_triage_review_enabled: bool = False
    email_triage_feedback_enabled: bool = False
    actor_id: str | None = None
    csrf_token: str | None = None
    idle_expires_at_utc: datetime | None = None
    absolute_expires_at_utc: datetime | None = None


class LoginRequest(ApiModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    password: str = Field(min_length=1)
