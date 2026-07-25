from __future__ import annotations

import httpx
import pytest

from personal_edge_lab.domain.ac import AcState, CommandOutcome
from personal_edge_lab.infrastructure.esp32.ac_controller import AcCommandClient
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.home.commands import CommandService


def state() -> AcState:
    return AcState.from_values(
        power="on",
        temperature_c="24",
        mode="cool",
        fan="auto",
        vertical_vane="middle",
    )


def test_every_http_outcome_is_audited(tmp_path) -> None:
    responses = [
        httpx.Response(
            200,
            json={**state().as_payload(), "state_source": "last_command"},
        ),
        httpx.Response(503, json={"error": "controller_failed"}),
        httpx.Response(200, json={"unexpected": True}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with (
        SqliteCommandAuditRepository(database) as store,
        AcCommandClient(
            base_url="http://node.local",
            timeout_seconds=1,
            transport=httpx.MockTransport(handler),
        ) as client,
    ):
        service = CommandService(
            device_id="node-1",
            controller=client,
            audit_repository=store,
        )
        executions = [service.set_state(state()) for _ in range(3)]
        rows = store.history(limit=10)

    assert [execution.result.outcome for execution in executions] == [
        CommandOutcome.CONFIRMED_SUCCESS,
        CommandOutcome.NODE_REPORTED_FAILURE,
        CommandOutcome.RESPONSE_UNKNOWN,
    ]
    assert {row.outcome for row in rows} == {
        CommandOutcome.CONFIRMED_SUCCESS,
        CommandOutcome.NODE_REPORTED_FAILURE,
        CommandOutcome.RESPONSE_UNKNOWN,
    }


def test_local_rejection_is_audited_without_http_request(tmp_path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with (
        SqliteCommandAuditRepository(database) as store,
        AcCommandClient(
            base_url="http://node.local",
            timeout_seconds=1,
            transport=httpx.MockTransport(handler),
        ) as client,
    ):
        execution = CommandService(
            device_id="node-1",
            controller=client,
            audit_repository=store,
        ).reject(
            command_type="set_state",
            attempted_payload={"temperature_c": "50"},
            message="temperature is invalid",
        )
        row = store.get(execution.command_id)

    assert calls == 0
    assert execution.result.outcome is CommandOutcome.REJECTED_LOCALLY
    assert row is not None
    assert row.outcome is CommandOutcome.REJECTED_LOCALLY


@pytest.mark.parametrize(
    ("exception_type", "expected_outcome"),
    [
        (httpx.ConnectError, CommandOutcome.NODE_UNREACHABLE),
        (httpx.ReadTimeout, CommandOutcome.TIMEOUT_UNKNOWN),
    ],
)
def test_transport_outcomes_are_audited(
    tmp_path,
    exception_type,
    expected_outcome: CommandOutcome,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("transport failure", request=request)

    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with (
        SqliteCommandAuditRepository(database) as store,
        AcCommandClient(
            base_url="http://node.local",
            timeout_seconds=1,
            transport=httpx.MockTransport(handler),
        ) as client,
    ):
        execution = CommandService(
            device_id="node-1",
            controller=client,
            audit_repository=store,
        ).set_state(state())
        row = store.get(execution.command_id)

    assert execution.result.outcome is expected_outcome
    assert row is not None
    assert row.outcome is expected_outcome
