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
cp .env.example .env
```

Build the dashboard with Node.js 24 before installing the Python package:

```bash
cd frontend
npm ci
npm run lint
npm test
npm run build
cd ..
python -m pip install -e '.[dev]'
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

## Query the local API

The read-only API runs independently from the collector and never contacts the ESP32:

```bash
python -m personal_edge_lab.apps.api
```

By default Uvicorn listens on loopback port 8000. On RUBIK, Nginx exposes the same application to
the trusted LAN:

```bash
curl http://rubik-edge-01.local/health
curl http://rubik-edge-01.local/api/v1/telemetry/latest
curl 'http://rubik-edge-01.local/api/v1/telemetry/series?window=6h'
curl 'http://rubik-edge-01.local/api/v1/ac/history?limit=20'
```

The phone-first dashboard is at `http://rubik-edge-01.local/`, with interactive documentation at
`/docs`. It separates API, collector, ESP32, and telemetry health using stored operational state.
It has no write routes, authentication, CORS, TLS, or public-internet exposure. See the [versioned
API contract](docs/contracts/platform-api-v1.md).

## Data and migrations

All applications run the same standard-library migration runner before opening a repository.
It creates `schema_migrations` and recognizes the existing telemetry/audit schema. Migration
`002_collector_runtime_status` adds one operational-status row per configured collector device;
existing telemetry and audit rows stay in place. SQLite uses one `data/telemetry.db`; there is no
ORM or second database process.

Useful diagnostics:

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
(cd frontend && npm run lint && npm test && npm run build)
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
sqlite3 data/telemetry.db \
  'SELECT device_id, received_at_utc, temperature_c, age_ms FROM temperature_readings ORDER BY id DESC LIMIT 10;'
python -m personal_edge_lab.apps.ac_cli history --limit 20
```

See [the development roadmap and log](docs/roadmap.md), the
[architecture guide](docs/architecture.md), the
[ESP32 contract](docs/contracts/ac-controller-01.md), the
[platform API contract](docs/contracts/platform-api-v1.md), and the
[Raspberry cutover runbook](docs/deployment.md).

The old `python -m telemetry_collector` and `python -m ac_control` entrypoints have intentionally
been removed. Deployment must update the installed package and `systemd` unit together.
