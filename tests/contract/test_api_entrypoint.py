from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from personal_edge_lab.apps.api import __main__ as api_main


def test_entrypoint_starts_single_worker_without_reload(monkeypatch, tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8080")
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("API_AC_CONTROL_ENABLED", "false")
    monkeypatch.setenv("EMAIL_TRIAGE_WORKSPACE_ENABLED", "false")
    monkeypatch.setenv("GMAIL_TRIAGE_REVIEW_ENABLED", "false")
    monkeypatch.setenv("API_DOCS_ENABLED", "true")
    captured: dict[str, object] = {}

    def run(app, **kwargs) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(api_main.uvicorn, "run", run)
    assert api_main.main() == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8080
    assert captured["workers"] == 1
    assert captured["reload"] is False
    assert captured["log_level"] == "info"


def test_entrypoint_rejects_invalid_configuration(monkeypatch) -> None:
    monkeypatch.setenv("API_PORT", "invalid")
    called = False

    def run(*args, **kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(api_main.uvicorn, "run", run)
    assert api_main.main() == 2
    assert called is False


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_health(url: str, process: subprocess.Popen[str]) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("API exited before becoming healthy")
        try:
            with urlopen(url, timeout=0.2) as response:
                return json.load(response)
        except (OSError, URLError):
            time.sleep(0.05)
    raise AssertionError("API did not become reachable")


def test_api_process_starts_migrates_and_stops_cleanly(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    port = available_port()
    environment = {
        **os.environ,
        "DATABASE_PATH": str(database),
        "API_HOST": "127.0.0.1",
        "API_PORT": str(port),
        "API_AUTH_ENABLED": "false",
        "API_AC_CONTROL_ENABLED": "false",
        "EMAIL_TRIAGE_WORKSPACE_ENABLED": "false",
        "GMAIL_TRIAGE_REVIEW_ENABLED": "false",
        "API_DOCS_ENABLED": "true",
        "LOG_LEVEL": "INFO",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "personal_edge_lab.apps.api"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        health = wait_for_health(f"http://127.0.0.1:{port}/health", process)
        process.send_signal(signal.SIGTERM)
        _stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    assert process.returncode in {0, -signal.SIGTERM}
    assert "Finished server process" in stderr
    assert health["status"] == "degraded"
    assert health["telemetry"]["status"] == "no_data"
    with sqlite3.connect(database) as connection:
        versions = list(connection.execute("SELECT version FROM schema_migrations"))
    assert versions == [
        ("001_initial",),
        ("002_collector_runtime_status",),
        ("003_authenticated_control",),
        ("004_operational_alerts",),
        ("005_notification_outbox",),
        ("006_email_triage_runs",),
        ("007_email_triage_messages",),
        ("008_email_triage_taxonomy_v2",),
    ]
