# personal-edge-lab

`personal-edge-lab` is the Python platform running on the RUBIK Pi 3 between independently
operating edge nodes and local services. It contains telemetry, authenticated owner access, and
audited air-conditioner control, plus durable operational alerts.

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

The owner-only Casadaqui Telegram bot is the platform's concise operations interface:

```bash
python -m personal_edge_lab.apps.telegram_cli set-token
python -m personal_edge_lab.apps.telegram_cli discover-owner
python -m personal_edge_lab.apps.telegram_bot
```

`/start` and `/help` open a capability menu for platform status, air conditioning, and notification
policy. The bot
centralizes private-owner authorization and routes each interaction to an explicit capability;
future capabilities can reuse the same channel without inheriting AC-specific rules.

The AC capability's `/ac` command opens an inline Cool-mode control panel with separate fan and
vane submenus. Adjustments only
edit that Telegram message; the visible normalized settings are sent when the owner presses
**Enviar ajuste**. `/off` retains a separate confirmation because it is easier to trigger
accidentally. Telegram is authorized by the immutable numeric owner user ID in a private chat;
groups and other users are ignored. Transmissions use the same durable audit, rate limit,
per-device lease, idempotency, and unknown-outcome rules as the dashboard.

`/status` is read-only. It reuses the platform-health use case to show the API, collector, ESP32,
telemetry, alert evaluator, durable notification delivery, and Telegram connection in one message.
Its **Actualizar** button edits the message in place and never contacts the ESP32 or creates an AC
audit row.

Confirmed alert and recovery transitions are atomically placed in a SQLite outbox and delivered by
the existing Casadaqui process. `/notifications` can pause them for one hour, eight hours, until
08:00 the next day in the owner's timezone, or indefinitely. Pausing never stops evaluation and
never queues a backlog for later delivery. Repeated flapping is coalesced into a bounded instability
message. Telegram delivery may retry because it is informational; physical AC requests retain their
strict no-retry rule.

The token is stored separately in a mode-`0600` file and is suppressed from HTTP logs.
The dashboard remains LAN-only, while Casadaqui is internet-mediated and therefore requires 2-Step
Verification and an app passcode on the owner's Telegram account.

Exit codes remain:

| Code | Meaning |
| ---: | --- |
| 0 | confirmed success, or successful history query |
| 1 | local filesystem or SQLite failure |
| 2 | configuration, arguments, or local validation failure |
| 3 | node unreachable |
| 4 | timeout or unexpected success response; final state unknown |
| 5 | node-reported HTTP failure |

Create or rotate the dashboard owner credential locally on RUBIK:

```bash
python -m personal_edge_lab.apps.auth_cli set-password
python -m personal_edge_lab.apps.auth_cli revoke-sessions
```

The password is prompted twice and never printed or stored. Only an Argon2id hash is written, with
mode `0600`. A password change revokes every existing dashboard session.

## Use the local dashboard and API

The API runs independently from the collector:

```bash
python -m personal_edge_lab.apps.api
```

Uvicorn listens only on loopback. Nginx terminates local HTTPS and exposes the application at:

```bash
https://rubik-edge-01.local/
```

The phone-first Personal Edge Lab console treats Climate as its first feature module: current
temperature and intentional AC control are primary, temperature history provides context, recent
commands form a compact activity record, and healthy system diagnostics remain secondary. Every
action has a normalized review step, idempotency key, audit attribution, one in-flight device
lock, and no automatic physical retry. The HTTPS CA must be trusted manually on the owner's phone
and computer. There is no CORS or public-internet exposure. Production `/docs` is disabled. See
the [versioned API contract](docs/contracts/platform-api-v1.md).

An independent one-shot evaluator runs every 30 seconds on RUBIK:

```bash
python -m personal_edge_lab.apps.alert_evaluator
```

It reads only SQLite, never contacts the ESP32, and persists transitions for stale telemetry and
repeated ESP32 collection failures. The dashboard shows suspect, active, and recently recovered
states. Repeated evaluations update one durable incident instead of creating notification noise.

## Data and migrations

All applications run the same standard-library migration runner before opening a repository.
It creates `schema_migrations` and recognizes the existing telemetry/audit schema. Migration
`002_collector_runtime_status` adds operational status. `003_authenticated_control` adds sessions,
durable login throttling, audit attribution/idempotency, and a leased web-command lock.
`004_operational_alerts` adds evaluator runtime, alert states, incidents, and transition events.
`005_notification_outbox` adds atomic outbound delivery, owner pause policy, retry leases, and
delivery runtime.
Existing telemetry and audit rows stay in place. SQLite uses one `data/telemetry.db`; there is no
ORM or second database process.

Useful diagnostics:

```bash
python -m pytest
python -m pytest --cov=personal_edge_lab --cov-report=term-missing
python -m ruff check .
python -m ruff format --check .
.venv/bin/pyright --pythonpath .venv/bin/python
.venv/bin/shellcheck scripts/*.sh
(cd frontend && npm run lint && npm test && npm run build)
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
sqlite3 data/telemetry.db \
  'SELECT device_id, received_at_utc, temperature_c, age_ms FROM temperature_readings ORDER BY id DESC LIMIT 10;'
python -m personal_edge_lab.apps.ac_cli history --limit 20
```

See [the development roadmap and log](docs/roadmap.md), the
[architecture guide](docs/architecture.md), the
[telemetry retention policy](docs/data-retention.md), the
[ESP32 contract](docs/contracts/ac-controller-01.md), the
[platform API contract](docs/contracts/platform-api-v1.md), and the
[Raspberry cutover runbook](docs/deployment.md).

The old `python -m telemetry_collector` and `python -m ac_control` entrypoints have intentionally
been removed. Deployment must update the installed package and `systemd` unit together.

## Deploying later changes on RUBIK

After the initial Stage 3 rollout has been accepted, build, install, restart, and verify a new
checkout with one command:

```bash
./scripts/deploy-rubik.sh
```

Provision the local certificate first from a trusted workstation:

```bash
./scripts/provision-local-tls.sh --copy-to ubuntu@rubik-edge-01.local
```

The deployment script preserves a pre-deployment backup, validates the TLS/security prerequisites,
installs and verifies the independent alert-evaluator timer and optional Telegram service, and
skips dependency installation when lockfiles are unchanged. It does not restart the collector.
Use `--skip-tests` only for a quick iteration that will receive a full checked deployment later.
