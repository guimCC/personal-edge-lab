from __future__ import annotations

import io
import sqlite3

import httpx
import pytest

from ac_control.__main__ import main


@pytest.fixture
def configured_environment(monkeypatch, tmp_path):
    database = tmp_path / "telemetry.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("AC_NODE_BASE_URL", "http://node.local")
    monkeypatch.setenv("AC_DEVICE_ID", "node-1")
    return database


def run_cli(arguments: list[str], handler) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        arguments,
        stdout=stdout,
        stderr=stderr,
        transport=httpx.MockTransport(handler),
    )
    return exit_code, stdout.getvalue(), stderr.getvalue()


def valid_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "power": True,
            "mode": "cool",
            "temperature_c": 24,
            "fan": "auto",
            "vertical_vane": "middle",
            "state_source": "last_command",
        },
    )


def set_arguments() -> list[str]:
    return [
        "set",
        "--power",
        "on",
        "--temperature",
        "24",
        "--mode",
        "cool",
        "--fan",
        "auto",
        "--vertical-vane",
        "middle",
    ]


def test_successful_set_prints_normalized_command_and_returns_zero(
    configured_environment,
) -> None:
    exit_code, stdout, stderr = run_cli(set_arguments(), valid_response)
    assert exit_code == 0
    assert '"temperature_c":24' in stdout
    assert "confirmed_success" in stdout
    assert stderr == ""


@pytest.mark.parametrize(
    ("handler", "expected_exit", "expected_outcome"),
    [
        (
            lambda request: httpx.Response(503, json={"error": "controller_failed"}),
            5,
            "node_reported_failure",
        ),
        (
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline")),
            3,
            "node_unreachable",
        ),
        (
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)),
            4,
            "timeout_unknown",
        ),
        (
            lambda request: httpx.Response(200, json={"unexpected": True}),
            4,
            "response_unknown",
        ),
    ],
)
def test_unsuccessful_outcome_exit_codes(
    configured_environment,
    handler,
    expected_exit: int,
    expected_outcome: str,
) -> None:
    exit_code, stdout, stderr = run_cli(set_arguments(), handler)
    assert exit_code == expected_exit
    assert expected_outcome in stderr


def test_invalid_set_is_audited_and_returns_two(configured_environment) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    arguments = set_arguments()
    arguments[arguments.index("24")] = "50"
    exit_code, stdout, stderr = run_cli(arguments, handler)

    assert exit_code == 2
    assert "rejected_locally" in stderr
    assert calls == 0
    with sqlite3.connect(configured_environment) as connection:
        outcome = connection.execute("SELECT outcome FROM ac_command_audit").fetchone()[0]
    assert outcome == "rejected_locally"


def test_history_displays_recent_audit(configured_environment) -> None:
    run_cli(set_arguments(), valid_response)
    exit_code, stdout, stderr = run_cli(
        ["history", "--limit", "10"],
        lambda request: httpx.Response(500),
    )
    assert exit_code == 0
    assert "confirmed_success" in stdout
    assert "set_state" in stdout
    assert stderr == ""
