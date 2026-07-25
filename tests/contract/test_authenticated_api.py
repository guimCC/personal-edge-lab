from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pwdlib import PasswordHash
from starlette.testclient import TestClient

from personal_edge_lab.apps.api.application import create_app
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.domain.ac import AcState, CommandOutcome, CommandResult
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
ORIGIN = "https://rubik-edge-01.local"
PASSWORD = "fourteen-chars!"


class RecordingController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, AcState | None]] = []

    def set_state(self, state: AcState) -> CommandResult:
        self.calls.append(("set_state", state))
        return CommandResult(
            outcome=CommandOutcome.CONFIRMED_SUCCESS,
            http_status=200,
            response_body='{"ok":true}',
        )

    def power_off(self) -> CommandResult:
        self.calls.append(("power_off", None))
        return CommandResult(
            outcome=CommandOutcome.CONFIRMED_SUCCESS,
            http_status=200,
            response_body='{"power":false,"status":"ok"}',
        )


def authenticated_settings(tmp_path) -> Settings:
    password_hash = tmp_path / "owner-password.hash"
    password_hash.write_text(
        PasswordHash.recommended().hash(PASSWORD),
        encoding="utf-8",
    )
    password_hash.chmod(0o600)
    return Settings(
        host="127.0.0.1",
        port=8000,
        telemetry_stale_after_seconds=45,
        docs_enabled=False,
        database_path=tmp_path / "telemetry.db",
        device_id="node-1",
        log_level=20,
        log_level_name="INFO",
        public_origin=ORIGIN,
        auth_enabled=True,
        ac_control_enabled=True,
        password_hash_file=password_hash,
    )


def login(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()


def write_headers(session: dict[str, object], key: str) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "X-CSRF-Token": str(session["csrf_token"]),
        "Idempotency-Key": key,
    }


def set_state() -> dict[str, object]:
    return {
        "command_type": "set_state",
        "state": {
            "power": True,
            "temperature_c": 24,
            "mode": "cool",
            "fan": "auto",
            "vertical_vane": "middle",
        },
    }


def test_shell_and_session_are_public_but_platform_data_is_protected(tmp_path) -> None:
    settings = authenticated_settings(tmp_path)
    with TestClient(
        create_app(settings, clock=lambda: NOW),
        base_url=ORIGIN,
    ) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        assert client.get("/health").status_code == 401
        assert client.get("/api/v1/telemetry/history").status_code == 401
        assert client.get("/api/v1/ac/history").status_code == 401
        assert client.get("/api/v1/alerts").status_code == 401
        assert client.get("/health/live").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        cors = client.options(
            "/health",
            headers={
                "Origin": "https://attacker.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in cors.headers


def test_login_cookie_session_and_logout_contract(tmp_path) -> None:
    settings = authenticated_settings(tmp_path)
    with TestClient(
        create_app(settings, clock=lambda: NOW),
        base_url=ORIGIN,
    ) as client:
        bad = client.post("/api/v1/auth/login", json={"password": "incorrect"})
        assert bad.status_code == 401
        assert bad.json() == {"detail": "invalid credentials"}

        response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "__Host-pel_session=" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert "Path=/" in cookie
        session = response.json()
        assert session["actor_id"] == "owner"
        assert session["csrf_token"]

        rejected = client.post("/api/v1/auth/logout", json={})
        assert rejected.status_code == 403
        accepted = client.post(
            "/api/v1/auth/logout",
            json={},
            headers=write_headers(session, "unused-idempotency-key"),
        )
        assert accepted.status_code == 204
        assert client.get("/health").status_code == 401


def test_command_is_sent_once_and_completed_duplicate_is_replayed(tmp_path) -> None:
    settings = authenticated_settings(tmp_path)
    controller = RecordingController()
    with TestClient(
        create_app(
            settings,
            clock=lambda: NOW,
            ac_controller_factory=lambda: controller,
        ),
        base_url=ORIGIN,
    ) as client:
        session = login(client)
        headers = write_headers(session, "550e8400-e29b-41d4-a716-446655440000")
        first = client.post("/api/v1/ac/commands", json=set_state(), headers=headers)
        replay = client.post("/api/v1/ac/commands", json=set_state(), headers=headers)

    assert first.status_code == 201
    assert first.json()["replayed"] is False
    assert first.json()["audit"]["actor_id"] == "owner"
    assert first.json()["audit"]["request_source"] == "dashboard"
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["audit"]["id"] == first.json()["audit"]["id"]
    assert len(controller.calls) == 1


def test_idempotency_conflict_and_cool_only_rejection_never_contact_node(tmp_path) -> None:
    settings = authenticated_settings(tmp_path)
    controller = RecordingController()
    with TestClient(
        create_app(
            settings,
            clock=lambda: NOW,
            ac_controller_factory=lambda: controller,
        ),
        base_url=ORIGIN,
    ) as client:
        session = login(client)
        headers = write_headers(session, "550e8400-e29b-41d4-a716-446655440001")
        invalid = set_state()
        assert isinstance(invalid["state"], dict)
        invalid["state"]["mode"] = "heat"
        rejected = client.post("/api/v1/ac/commands", json=invalid, headers=headers)
        assert rejected.status_code == 201
        assert rejected.json()["audit"]["outcome"] == "rejected_locally"

        conflict = client.post(
            "/api/v1/ac/commands",
            json={"command_type": "power_off"},
            headers=headers,
        )
        assert conflict.status_code == 409

    assert controller.calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://attacker.invalid", "Sec-Fetch-Site": "cross-site"},
        {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": "wrong"},
    ],
)
def test_command_security_failures_are_not_audited(tmp_path, headers) -> None:
    settings = authenticated_settings(tmp_path)
    controller = RecordingController()
    with TestClient(
        create_app(settings, ac_controller_factory=lambda: controller),
        base_url=ORIGIN,
    ) as client:
        login(client)
        supplied = {
            "Idempotency-Key": "550e8400-e29b-41d4-a716-446655440002",
            **headers,
        }
        response = client.post("/api/v1/ac/commands", json=set_state(), headers=supplied)

    assert response.status_code in {401, 403}
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ac_command_audit").fetchone() == (0,)
    assert controller.calls == []


def test_malformed_request_is_not_audited(tmp_path) -> None:
    settings = authenticated_settings(tmp_path)
    controller = RecordingController()
    with TestClient(
        create_app(settings, ac_controller_factory=lambda: controller),
        base_url=ORIGIN,
    ) as client:
        session = login(client)
        response = client.post(
            "/api/v1/ac/commands",
            content="{",
            headers={
                **write_headers(
                    session,
                    "550e8400-e29b-41d4-a716-446655440003",
                ),
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 422
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ac_command_audit").fetchone() == (0,)
    assert controller.calls == []


def test_seventh_new_attempt_in_one_minute_is_rate_limited(tmp_path) -> None:
    settings = authenticated_settings(tmp_path)
    controller = RecordingController()
    invalid = set_state()
    assert isinstance(invalid["state"], dict)
    invalid["state"]["mode"] = "heat"
    with TestClient(
        create_app(
            settings,
            clock=lambda: NOW,
            ac_controller_factory=lambda: controller,
        ),
        base_url=ORIGIN,
    ) as client:
        session = login(client)
        for index in range(6):
            response = client.post(
                "/api/v1/ac/commands",
                json=invalid,
                headers=write_headers(session, f"rate-limit-key-{index:02d}"),
            )
            assert response.status_code == 201
        limited = client.post(
            "/api/v1/ac/commands",
            json=invalid,
            headers=write_headers(session, "rate-limit-key-06"),
        )

    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert controller.calls == []


def test_controls_disabled_returns_not_found_and_does_not_enter_openapi(tmp_path) -> None:
    settings = replace(
        authenticated_settings(tmp_path),
        ac_control_enabled=False,
        docs_enabled=True,
    )
    run_migrations(settings.database_path)
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        session = login(client)
        response = client.post(
            "/api/v1/ac/commands",
            json=set_state(),
            headers=write_headers(session, "550e8400-e29b-41d4-a716-446655440004"),
        )
        schema = client.get("/openapi.json").json()

    assert response.status_code == 404
    assert "/api/v1/ac/commands" not in schema["paths"]


def test_controls_disabled_without_authentication_still_returns_not_found(
    tmp_path,
) -> None:
    settings = replace(
        authenticated_settings(tmp_path),
        auth_enabled=False,
        ac_control_enabled=False,
        docs_enabled=True,
    )
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        response = client.post(
            "/api/v1/ac/commands",
            json=set_state(),
            headers={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440005"},
        )

    assert response.status_code == 404
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ac_command_audit").fetchone() == (0,)
