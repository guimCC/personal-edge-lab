# personal-edge-lab

`personal-edge-lab` is the software platform for a RUBIK Pi 3 acting as a small local cloud for personal IoT, edge-computing, automation, observability, device-management, and local-AI experiments. It will grow through small vertical slices that work end to end and leave useful infrastructure behind.

## Architecture and responsibility boundary

Edge nodes such as ESP32s own hardware concerns: sampling sensors, caching current values, controlling actuators, maintaining connectivity, and exposing explicit HTTP contracts. The RUBIK Pi consumes those contracts; it validates and stores data and will later coordinate devices, automations, APIs, dashboards, and agents. Platform code does not reproduce firmware calculations or assume that reading an endpoint triggers a sensor sample.

The first slice is deliberately small:

```text
ESP32 cached /temperature response
              -> HTTP collector -> validation -> SQLite history
```

See [the architecture notes](docs/architecture.md) and [the current node contract](docs/contracts/ac-controller-01.md).

## Set up and run

Python 3.12 or later is required. From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

The application reads environment variables directly; it does not automatically load `.env`. Export the file before running it:

```bash
set -a
source .env
set +a
python -m telemetry_collector
```

Defaults match the current `ac-controller-01.local` node, poll every 15 seconds, use a five-second HTTP timeout, and write `./data/telemetry.db`. `TEMPERATURE_ENDPOINT` is also configurable so an endpoint can evolve independently of the collector.

Stop with Ctrl-C. Network, DNS, timeout, HTTP, and malformed-payload failures are logged; polling continues and resumes automatically when the node recovers. Repeated failures are summarized periodically to avoid noisy logs.

## Develop and inspect data

```bash
pytest
ruff check .
ruff format .
sqlite3 data/telemetry.db \
  'SELECT device_id, received_at_utc, temperature_c, age_ms FROM temperature_readings ORDER BY id DESC LIMIT 10;'
```

The database and tables are created on startup. Runtime databases, `.env`, virtual environments, and tool caches are ignored by Git.

## Deliberately deferred

This slice contains no edge firmware, actuator logic, MQTT, web API, dashboard, PostgreSQL/time-series database, ORM, Redis, containers, Kubernetes, systemd unit, CI workflow, or generic device/plugin framework. Those belong in later slices only when a concrete requirement warrants them.

