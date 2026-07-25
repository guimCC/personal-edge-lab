# personal-edge-lab

`personal-edge-lab` is the software platform for a RUBIK Pi 3 acting as a small local cloud for personal IoT, edge-computing, automation, observability, device-management, and local-AI experiments. It will grow through small vertical slices that work end to end and leave useful infrastructure behind.

## Architecture and responsibility boundary

Edge nodes such as ESP32s own hardware concerns: sampling sensors, caching current values, controlling actuators, maintaining connectivity, and exposing explicit HTTP contracts. The RUBIK Pi consumes those contracts; it validates and stores data and will later coordinate devices, automations, APIs, dashboards, and agents. Platform code does not reproduce firmware calculations or assume that reading an endpoint triggers a sensor sample.

The platform currently has two deliberately small vertical slices:

```text
ESP32 cached /temperature response
              -> HTTP collector -> validation -> SQLite history

operator -> AC command CLI -> validation -> one ESP32 HTTP command
                              \-> SQLite command audit
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

Defaults match the current `ac-controller-01.local` node. Telemetry polls every 15 seconds with a five-second timeout. AC commands use a separate five-second timeout and never retry automatically. Both components use `./data/telemetry.db`; AC commands have a separate audit table.

Stop with Ctrl-C. Network, DNS, timeout, HTTP, and malformed-payload failures are logged; polling continues and resumes automatically when the node recovers. Repeated failures are summarized periodically to avoid noisy logs.

## Control the air conditioner

The AC command layer is an on-demand CLI, not a continuously running service. Every `set` command
requires a complete state so the platform never infers missing actuator settings:

```bash
python -m ac_control set \
  --power on \
  --temperature 24 \
  --mode cool \
  --fan auto \
  --vertical-vane middle

python -m ac_control off
python -m ac_control history --limit 20
```

An HTTP 200 confirms that the ESP32 accepted the state and transmitted IR. Infrared is one-way, so
it does not confirm the physical AC state. A timeout is reported as `timeout_unknown` and is never
retried automatically because the ESP32 may already have transmitted the command.

See the [AC control service documentation](services/ac-control/README.md) for outcomes, exit codes,
configuration, and RUBIK Pi commands.

## Develop and inspect data

```bash
python -m pytest
python -m ruff check .
python -m ruff format .
sqlite3 data/telemetry.db \
  'SELECT device_id, received_at_utc, temperature_c, age_ms FROM temperature_readings ORDER BY id DESC LIMIT 10;'
sqlite3 -header -column data/telemetry.db \
  'SELECT id, requested_at_utc, command_type, outcome, http_status FROM ac_command_audit ORDER BY id DESC LIMIT 20;'
```

Using `python -m` ensures these commands run with the currently selected Python interpreter. If
`pytest` by itself reports a different version than `python -m pytest`, the shell is resolving a
system executable, alias, or cached command path instead of the virtual environment executable.

The database and tables are created on startup. Runtime databases, `.env`, virtual environments, and tool caches are ignored by Git.

## Deliberately deferred

The repository contains no edge firmware or hardware-specific IR logic. It also contains no MQTT,
web API, dashboard, automation or scheduling engine, PostgreSQL/time-series database, ORM, Redis,
containers, Kubernetes, AC command systemd unit, CI workflow, or generic device/plugin framework.
Those belong in later slices only when a concrete requirement warrants them.
