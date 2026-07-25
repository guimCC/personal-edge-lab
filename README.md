# personal-edge-lab

`personal-edge-lab` is the Python platform running on the RUBIK Pi 3 between independently
operating edge nodes and future local services. It currently contains two real modules:
continuous temperature telemetry and on-demand air-conditioner control.

```text
apps -> application/ports <- infrastructure
                |
             modules -> domain
```

ESP32 nodes own sampling, cached values, connectivity, actuator behavior, and IR transmission.
The platform consumes their explicit HTTP contracts, validates intent and readings, and preserves
telemetry and command audits in one SQLite database.

## Install

Python 3.12 or later is required. From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

The applications read the existing environment variable names directly and do not load `.env`
themselves:

```bash
set -a
source .env
set +a
```

## Run telemetry

```bash
python -m personal_edge_lab.apps.telemetry_collector
```

The default interval remains 15 seconds and the HTTP timeout remains five seconds. A failed
request creates no row. Polling continues, suppresses repetitive logs, and reports recovery when
the ESP32 is available again. SIGINT and SIGTERM stop the process cleanly.

## Control the air conditioner

Every `set` requires a complete state:

```bash
python -m personal_edge_lab.apps.ac_cli set \
  --power on \
  --temperature 24 \
  --mode cool \
  --fan auto \
  --vertical-vane middle

python -m personal_edge_lab.apps.ac_cli off
python -m personal_edge_lab.apps.ac_cli history --limit 20
```

Each accepted command makes exactly one HTTP attempt and is audited. There are no automatic
retries. A timeout is `timeout_unknown` because the ESP32 may already have transmitted IR. An
HTTP 200 confirms accepted transmission, not the physical state of the AC.

Exit codes remain:

| Code | Meaning |
| ---: | --- |
| 0 | confirmed success, or successful history query |
| 1 | local filesystem or SQLite failure |
| 2 | configuration, arguments, or local validation failure |
| 3 | node unreachable |
| 4 | timeout or unexpected success response; final state unknown |
| 5 | node-reported HTTP failure |

## Data and migrations

Both applications run the same standard-library migration runner before opening a repository.
It creates `schema_migrations` and recognizes the existing `temperature_readings` and
`ac_command_audit` tables and indexes with `IF NOT EXISTS`. Existing rows stay in place. SQLite
uses one `data/telemetry.db`; there is no ORM or second database process.

Useful diagnostics:

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
sqlite3 data/telemetry.db \
  'SELECT device_id, received_at_utc, temperature_c, age_ms FROM temperature_readings ORDER BY id DESC LIMIT 10;'
python -m personal_edge_lab.apps.ac_cli history --limit 20
```

See [the development roadmap and log](docs/roadmap.md), the
[architecture guide](docs/architecture.md), the
[ESP32 contract](docs/contracts/ac-controller-01.md), and the
[Raspberry cutover runbook](docs/deployment.md).

The old `python -m telemetry_collector` and `python -m ac_control` entrypoints have intentionally
been removed. Deployment must update the installed package and `systemd` unit together.
