from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from personal_edge_lab.application.ports.telemetry import SourceFailureCategory
from personal_edge_lab.apps.api.application import create_app
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.domain.ac import CommandOutcome, CommandResult
from personal_edge_lab.domain.alerting import AlertPolicy
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.infrastructure.persistence.sqlite.alert_evaluation import (
    SqliteAlertEvaluationRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.collector_status import (
    SqliteCollectorStatusRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.alerting import EvaluateOperationalAlerts

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)


def settings(database, *, docs_enabled: bool = True) -> Settings:
    return Settings(
        host="0.0.0.0",
        port=8000,
        telemetry_stale_after_seconds=45,
        docs_enabled=docs_enabled,
        database_path=database,
        device_id="node-1",
        log_level=20,
        log_level_name="INFO",
    )


def reading(
    *,
    device_id: str = "node-1",
    received_at: datetime = NOW - timedelta(seconds=30),
    temperature_c: float = 24.5,
) -> TemperatureReading:
    return TemperatureReading.from_payload(
        {
            "sensor": "thermistor",
            "temperature_c": temperature_c,
            "raw_adc": 1700,
            "age_ms": 500,
            "sample_interval_ms": 2000,
        },
        device_id=device_id,
        received_at=received_at,
    )


def seed_telemetry(database, *values: TemperatureReading) -> None:
    run_migrations(database)
    with SqliteTelemetryRepository(database) as repository:
        for value in values:
            repository.insert(value)


def seed_running_collector(database) -> None:
    run_migrations(database)
    with SqliteCollectorStatusRepository(database) as repository:
        repository.start("node-1", started_at=NOW - timedelta(hours=1))
        repository.record_success("node-1", attempted_at=NOW - timedelta(seconds=5))


def evaluate_alerts(database, *, now: datetime = NOW) -> None:
    EvaluateOperationalAlerts(
        lambda: SqliteAlertEvaluationRepository(database),
        device_id="node-1",
        policy=AlertPolicy(
            telemetry_suspect_after_seconds=45,
            telemetry_alert_after_seconds=180,
            edge_min_consecutive_failures=4,
            edge_alert_after_seconds=45,
            recovery_display_seconds=300,
        ),
        clock=lambda: now,
    ).execute()


def test_health_reports_fresh_telemetry(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(database, reading())
    seed_running_collector(database)
    evaluate_alerts(database)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "version": "0.6.0",
        "checked_at_utc": "2026-07-25T14:00:00Z",
        "database": {"status": "healthy"},
        "telemetry": {
            "status": "fresh",
            "device_id": "node-1",
            "last_received_at_utc": "2026-07-25T13:59:30Z",
            "age_seconds": 30.0,
            "stale_after_seconds": 45.0,
        },
        "collector": {
            "status": "running",
            "device_id": "node-1",
            "process_started_at_utc": "2026-07-25T13:00:00Z",
            "heartbeat_at_utc": "2026-07-25T13:59:55Z",
            "heartbeat_age_seconds": 5.0,
            "stale_after_seconds": 45.0,
            "stopped_at_utc": None,
            "last_attempt_at_utc": "2026-07-25T13:59:55Z",
            "last_success_at_utc": "2026-07-25T13:59:55Z",
            "consecutive_failures": 0,
        },
        "edge_node": {
            "status": "reachable",
            "device_id": "node-1",
            "last_attempt_at_utc": "2026-07-25T13:59:55Z",
            "last_success_at_utc": "2026-07-25T13:59:55Z",
            "last_failure_at_utc": None,
            "last_failure_category": None,
            "last_failure_message": None,
        },
        "alerts": {
            "status": "healthy",
            "active_count": 0,
            "suspect_count": 0,
            "latest_transition_at_utc": None,
            "evaluator_last_run_at_utc": "2026-07-25T14:00:00Z",
            "evaluator_age_seconds": 0.0,
        },
    }


@pytest.mark.parametrize(
    ("values", "expected_status"),
    [
        ([reading(received_at=NOW - timedelta(seconds=45.001))], "stale"),
        ([], "no_data"),
    ],
)
def test_health_reports_degraded_telemetry(
    tmp_path,
    values: list[TemperatureReading],
    expected_status: str,
) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(database, *values)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["telemetry"]["status"] == expected_status


def test_health_distinguishes_running_collector_from_unreachable_edge_node(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(database, reading(received_at=NOW - timedelta(minutes=2)))
    with SqliteCollectorStatusRepository(database) as repository:
        repository.start("node-1", started_at=NOW - timedelta(hours=1))
        repository.record_failure(
            "node-1",
            attempted_at=NOW - timedelta(seconds=5),
            category=SourceFailureCategory.TIMEOUT,
            message="temperature request timed out",
        )
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/health")

    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["collector"]["status"] == "running"
    assert payload["collector"]["consecutive_failures"] == 1
    assert payload["edge_node"]["status"] == "unreachable"
    assert payload["edge_node"]["last_failure_category"] == "timeout"
    assert "node.local" not in response.text


def test_alerts_endpoint_reports_one_active_incident_and_current_states(tmp_path) -> None:
    database = tmp_path / "alerts.db"
    seed_telemetry(
        database,
        reading(received_at=NOW - timedelta(minutes=10)),
    )
    evaluate_alerts(database)
    checked_at = NOW + timedelta(seconds=30)
    evaluate_alerts(database, now=checked_at)

    with TestClient(create_app(settings(database), clock=lambda: checked_at)) as client:
        response = client.get(
            "/api/v1/alerts",
            params={"status": "active", "limit": 5},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["device_id"] == "node-1"
    assert payload["status"] == "alerting"
    assert payload["count"] == 1
    assert payload["limit"] == 5
    assert len(payload["states"]) == 2
    telemetry_state = next(
        item for item in payload["states"] if item["alert_type"] == "telemetry_stale"
    )
    assert telemetry_state["lifecycle"] == "alerting"
    assert telemetry_state["active_incident_id"] == payload["incidents"][0]["id"]
    assert payload["incidents"][0]["status"] == "active"
    assert payload["incidents"][0]["duration_seconds"] == 0.0
    assert "database" not in response.text.lower()


def test_alerts_endpoint_returns_unknown_and_empty_before_first_evaluation(tmp_path) -> None:
    database = tmp_path / "empty-alerts.db"
    run_migrations(database)

    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/api/v1/alerts")

    assert response.status_code == 200
    assert response.json() == {
        "device_id": "node-1",
        "status": "unknown",
        "evaluator_last_run_at_utc": None,
        "evaluator_age_seconds": None,
        "count": 0,
        "limit": 20,
        "states": [],
        "incidents": [],
    }


def test_alerts_endpoint_reports_recovered_incident_duration(tmp_path) -> None:
    database = tmp_path / "recovered-alert.db"
    seed_telemetry(
        database,
        reading(received_at=NOW - timedelta(minutes=10)),
    )
    evaluate_alerts(database)
    alerting_at = NOW + timedelta(seconds=30)
    evaluate_alerts(database, now=alerting_at)
    recovered_at = alerting_at + timedelta(seconds=15)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(received_at=recovered_at))
    evaluate_alerts(database, now=recovered_at)

    with TestClient(create_app(settings(database), clock=lambda: recovered_at)) as client:
        response = client.get(
            "/api/v1/alerts",
            params={"status": "recovered", "limit": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "recovered"
    assert payload["count"] == 1
    assert payload["incidents"][0]["status"] == "recovered"
    assert payload["incidents"][0]["recovered_at_utc"] == "2026-07-25T14:00:45Z"
    assert payload["incidents"][0]["duration_seconds"] == 15.0


def test_latest_temperature_contract_and_device_override(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(database, reading(), reading(device_id="node-2", temperature_c=30))
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get(
            "/api/v1/telemetry/latest",
            params={"device_id": "node-2"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "device_id": "node-2",
        "sensor": "thermistor",
        "received_at_utc": "2026-07-25T13:59:30Z",
        "estimated_sample_at_utc": "2026-07-25T13:59:29.500000Z",
        "temperature_c": 30.0,
        "raw_adc": 1700,
        "age_ms": 500,
        "sample_interval_ms": 2000,
    }


def test_latest_returns_not_found_for_unknown_device(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(database)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get(
            "/api/v1/telemetry/latest",
            params={"device_id": "unknown"},
        )
    assert response.status_code == 404
    assert response.json() == {"detail": "no telemetry reading found for device"}


def test_telemetry_history_is_bounded_newest_first(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(
        database,
        reading(received_at=NOW - timedelta(minutes=2), temperature_c=20),
        reading(device_id="node-2", temperature_c=30),
        reading(received_at=NOW - timedelta(minutes=1), temperature_c=21),
        reading(temperature_c=22),
    )
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/api/v1/telemetry/history", params={"limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["limit"] == 2
    assert [item["temperature_c"] for item in payload["items"]] == [22.0, 21.0]
    assert {item["device_id"] for item in payload["items"]} == {"node-1"}


def test_empty_histories_return_lists(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        telemetry = client.get("/api/v1/telemetry/history")
        commands = client.get("/api/v1/ac/history")

    assert telemetry.json() == {"count": 0, "limit": 100, "items": []}
    assert commands.json() == {"count": 0, "limit": 20, "items": []}


def test_telemetry_series_returns_chronological_buckets_and_gaps(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(
        database,
        reading(received_at=NOW - timedelta(minutes=10), temperature_c=20),
        reading(received_at=NOW - timedelta(minutes=9, seconds=30), temperature_c=22),
    )
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/api/v1/telemetry/series", params={"window": "1h"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["window"] == "1h"
    assert payload["bucket_seconds"] == 60
    assert payload["sample_count"] == 2
    assert len(payload["items"]) == 60
    populated = [item for item in payload["items"] if item["sample_count"]]
    assert len(populated) == 1
    assert populated[0]["temperature_minimum_c"] == 20.0
    assert populated[0]["temperature_average_c"] == 21.0
    assert populated[0]["temperature_maximum_c"] == 22.0
    assert payload["items"][0]["bucket_start_at_utc"] < payload["items"][-1]["bucket_start_at_utc"]


def test_stored_queries_work_without_esp32_connectivity(tmp_path, monkeypatch) -> None:
    database = tmp_path / "telemetry.db"
    seed_telemetry(database, reading())

    def fail_if_called(*args, **kwargs):
        raise AssertionError("read-only API must not contact the ESP32")

    monkeypatch.setattr("httpx.Client.request", fail_if_called)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/api/v1/telemetry/latest")

    assert response.status_code == 200
    assert response.json()["temperature_c"] == 24.5


def test_ac_history_returns_structured_payload_and_pending_nulls(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteCommandAuditRepository(database) as repository:
        completed_id = repository.begin(
            device_id="node-1",
            command_type="power_off",
            payload_json='{"power":false}',
            requested_at=NOW,
        )
        repository.complete(
            completed_id,
            CommandResult(
                outcome=CommandOutcome.CONFIRMED_SUCCESS,
                http_status=200,
                response_body='{"power":false,"status":"ok"}',
            ),
            completed_at=NOW,
        )
        repository.begin(
            device_id="node-1",
            command_type="set_state",
            payload_json='{"temperature_c":24}',
            requested_at=NOW,
        )

    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/api/v1/ac/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    pending, completed = payload["items"]
    assert pending["command_payload"] == {"temperature_c": 24}
    assert pending["outcome"] == "pending"
    assert pending["completed_at_utc"] is None
    assert pending["http_status"] is None
    assert completed["command_payload"] == {"power": False}
    assert completed["outcome"] == "confirmed_success"
    assert completed["http_status"] == 200


def test_ac_history_returns_sanitized_503_for_corrupt_stored_payload(tmp_path) -> None:
    database = tmp_path / "corrupt-audit.db"
    run_migrations(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO ac_command_audit (
                device_id, command_type, command_payload_json,
                requested_at_utc, outcome, request_source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("node-1", "power_off", "{invalid", NOW.isoformat(), "pending", "local_cli"),
        )

    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/api/v1/ac/history")

    assert response.status_code == 503
    assert response.json() == {"detail": "stored data unavailable"}
    assert "invalid" not in response.text


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/telemetry/latest", {"device_id": "   "}),
        ("/api/v1/telemetry/history", {"limit": 0}),
        ("/api/v1/telemetry/history", {"limit": 1001}),
        ("/api/v1/telemetry/series", {"window": "week"}),
        ("/api/v1/ac/history", {"limit": 0}),
        ("/api/v1/ac/history", {"limit": 101}),
        ("/api/v1/alerts", {"status": "invalid"}),
        ("/api/v1/alerts", {"limit": 0}),
        ("/api/v1/alerts", {"limit": 101}),
    ],
)
def test_invalid_queries_return_422(tmp_path, path: str, params: dict[str, object]) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get(path, params=params)
    assert response.status_code == 422


def test_database_errors_return_sanitized_503(tmp_path, monkeypatch) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)

    def fail(_repository, _device_id):
        raise sqlite3.OperationalError(f"secret database path: {database}")

    monkeypatch.setattr(SqliteTelemetryRepository, "latest", fail)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
    assert str(database) not in response.text


def test_docs_and_openapi_expose_auth_and_read_routes_when_controls_disabled(
    tmp_path,
) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        docs = client.get("/docs")
        schema = client.get("/openapi.json").json()

    assert docs.status_code == 200
    assert set(schema["paths"]) == {
        "/health",
        "/api/v1/auth/session",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/telemetry/latest",
        "/api/v1/telemetry/history",
        "/api/v1/telemetry/series",
        "/api/v1/ac/history",
        "/api/v1/alerts",
    }
    assert set(schema["paths"]["/api/v1/auth/session"]) == {"get"}
    assert set(schema["paths"]["/api/v1/auth/login"]) == {"post"}
    assert set(schema["paths"]["/api/v1/auth/logout"]) == {"post"}
    assert "/api/v1/ac/commands" not in schema["paths"]


def test_dashboard_is_served_with_restrictive_headers_and_not_in_openapi(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        dashboard = client.get("/")
        schema = client.get("/openapi.json").json()
        asset_path = next(
            path
            for path in dashboard.text.split('"')
            if path.startswith("/assets/") and path.endswith(".js")
        )
        asset = client.get(asset_path)

    assert dashboard.status_code == 200
    assert "RUBIK · Edge Lab" in dashboard.text
    assert dashboard.headers["cache-control"] == "no-cache"
    assert "default-src 'self'" in dashboard.headers["content-security-policy"]
    assert "/" not in schema["paths"]
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]


def test_docs_can_be_disabled(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with TestClient(
        create_app(settings(database, docs_enabled=False), clock=lambda: NOW)
    ) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_mutating_methods_are_not_available(tmp_path, method: str) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with TestClient(create_app(settings(database), clock=lambda: NOW)) as client:
        response = client.request(
            method.upper(),
            "/api/v1/ac/history",
            json={"power": False},
        )

    assert response.status_code == 405
    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM ac_command_audit").fetchone()
    assert count == (0,)
