"""Shared Pydantic response behavior."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class StoredDataError(RuntimeError):
    """Raised when persisted data cannot satisfy a public response contract."""
