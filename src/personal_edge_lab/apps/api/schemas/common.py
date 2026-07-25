"""Shared Pydantic response behavior."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)
