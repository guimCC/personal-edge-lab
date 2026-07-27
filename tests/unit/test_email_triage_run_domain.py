from __future__ import annotations

import pytest

from personal_edge_lab.domain.email_triage_runs import (
    MAX_RECENT_RUNS,
    TriageRunValidationError,
    validate_recent_run_limit,
)


@pytest.mark.parametrize("limit", [1, 20, MAX_RECENT_RUNS])
def test_recent_run_query_bounds_are_valid(limit: int) -> None:
    assert validate_recent_run_limit(limit) == limit


@pytest.mark.parametrize("limit", [True, 0, 101])
def test_recent_run_query_rejects_invalid_bounds(limit: int) -> None:
    with pytest.raises(TriageRunValidationError):
        validate_recent_run_limit(limit)
