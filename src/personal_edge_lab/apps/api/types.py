"""Reusable FastAPI parameter contracts."""

from typing import Annotated

from fastapi import Header, Query

DeviceId = Annotated[str | None, Query(pattern=r"\S")]
TelemetryLimit = Annotated[int, Query(ge=1, le=1000)]
CommandLimit = Annotated[int, Query(ge=1, le=100)]
AlertLimit = Annotated[int, Query(ge=1, le=100)]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=16,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
