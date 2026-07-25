from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time

import pytest


def wait_until_migrated(database, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("collector exited before initializing its database")
        try:
            with sqlite3.connect(database, timeout=0.05) as connection:
                row = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
            if row:
                return
        except sqlite3.Error:
            pass
        time.sleep(0.02)
    raise AssertionError("collector did not initialize its database")


@pytest.mark.parametrize("shutdown_signal", [signal.SIGINT, signal.SIGTERM])
def test_collector_process_stops_cleanly_on_signal(
    tmp_path, shutdown_signal: signal.Signals
) -> None:
    database = tmp_path / "telemetry.db"
    environment = {
        **os.environ,
        "DATABASE_PATH": str(database),
        "EDGE_NODE_BASE_URL": "http://127.0.0.1:9",
        "COLLECTION_INTERVAL_SECONDS": "0.05",
        "HTTP_TIMEOUT_SECONDS": "0.05",
        "LOG_LEVEL": "INFO",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "personal_edge_lab.apps.telemetry_collector"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        wait_until_migrated(database, process)
        process.send_signal(shutdown_signal)
        _stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    assert process.returncode == 0
    assert "Telemetry collector stopped" in stderr
