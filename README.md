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

## Diagnose local inference

The packaged diagnostic CLI proves the private RUBIK-to-UNO-Q path without introducing an email
worker or storing model content. Public node liveness works even when inference is disabled:

```bash
python -m personal_edge_lab.apps.ai_cli health
python -m personal_edge_lab.apps.ai_cli ready
```

`health` proves that the llama.cpp HTTP process is responding, including while the model reports
its documented loading state. `ready` succeeds only after the model is loaded. Neither command
reads the API key or feature gate.

Authenticated completion is deliberately feature-gated:

```bash
export LOCAL_LLM_ENABLED=true
python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
```

The completion key remains in the mode-`0600` file configured by
`LOCAL_LLM_API_KEY_FILE`; never place its value in `.env` or a command line. The CLI makes one
bounded request with no retry. It prints operation evidence, provider `llama_cpp`, logical model
`qwen3-1.7b-q4-k-m`, token usage when supplied, queue wait, provider time, and total elapsed time.
One process permits only one active completion; a second caller waits for at most
`LOCAL_LLM_QUEUE_TIMEOUT_SECONDS`. Prompt and completion content are excluded from logs; successful
completion text appears only on standard output after terminal control characters are removed.

Exit codes are `0` for success, `2` for disabled/configuration/input rejection, `3` for connection,
`4` for timeout, and `5` for readiness, concurrency, authenticated HTTP, provider, or protocol
failure.

## Exercise observable email triage

Release `0.11.0` adds one synthetic, read-only triage path above the existing local-model
foundation. It does not access Gmail, persist messages, schedule work, or mutate a mailbox:

```bash
python -m personal_edge_lab.apps.ai_cli triage --fixture synthetic-invoice
```

With `LANGFUSE_ENABLED=false`, the command uses the packaged versioned prompt and creates no trace.
With Langfuse enabled, it fetches the production-labelled
`personal-edge-lab/email-triage` chat prompt, falls back locally after any prompt-service failure,
and attempts one trace containing the checked-in synthetic message. Tracing failure never changes a
successful triage result.

Prompt changes are an explicit operator action and never happen during inference:

```bash
python -m personal_edge_lab.apps.ai_cli prompt-publish
```

The command is idempotent when the packaged prompt already matches production. Langfuse keys stay
in the owner-only mode-`0600` files configured by `LANGFUSE_PUBLIC_KEY_FILE` and
`LANGFUSE_SECRET_KEY_FILE`. Only synthetic fixture content is authorized for trace capture.

## Retrieve a bounded Gmail batch

Release `0.12.0` adds a separate read-only Gmail diagnostic path. It retrieves and normalizes a
small owner-selected batch without invoking the model, Langfuse, SQLite, or any mailbox mutation:

```bash
python -m personal_edge_lab.apps.email_triage_cli fetch \
  --query "in:inbox newer_than:7d" \
  --limit 10
```

The query is always explicit and the batch is limited to at most 25 messages. Output contains
receipt time, Gmail message/thread IDs, sender, subject, content source, sizes, and cleanup flags.
Normalized message bodies remain process-local and are never printed, logged, traced, or stored.

Initial personal-account authorization is an explicit operator action:

```bash
python -m personal_edge_lab.apps.email_triage_cli authorize
```

It requests only `gmail.readonly`, listens on the configured loopback port, and writes the OAuth
token directly to the owner-only mode-`0600` file configured by `GMAIL_TOKEN_FILE`. Existing tokens
are never overwritten without `--replace-token`. `authorize` works while `GMAIL_READ_ENABLED=false`
so credentials can be bootstrapped before enabling retrieval. See the deployment runbook for the
SSH loopback-tunnel workflow and Google Cloud setup.

## Run durable read-only mailbox triage

Release `0.13.0` connects the bounded Gmail source to the existing prompt, one-slot local model,
strict decoder, redacted Langfuse tracing, and evidence-only SQLite repository:

```bash
python -m personal_edge_lab.apps.email_triage_cli triage \
  --query "in:inbox newer_than:7d" \
  --limit 3
python -m personal_edge_lab.apps.email_triage_cli runs --limit 20
python -m personal_edge_lab.apps.email_triage_cli show --run-id <run-id>
```

The query and limit are mandatory, the limit is at most ten, and the command remains a dry run:
it never sends, marks read, labels, archives, trashes, or otherwise changes Gmail. Release `0.15.0`
stores the query, sender, subject, bounded normalized body, exact model input, label, and reason in
owner-only SQLite so the dashboard can present useful email records. Raw MIME, attachments,
credentials, provider bodies, and GGUF paths remain excluded.

An identical successful identity is reused without another model call or trace. Use
`--new-attempt` only when intentionally creating another auditable inference attempt. Real-Gmail
Langfuse traces contain only hashes, lengths, cleanup evidence, the proposed label, versions,
timing, and usage; full content remains restricted to checked-in synthetic fixtures.

`triage` requires `GMAIL_TRIAGE_ENABLED=true`, `GMAIL_READ_ENABLED=true`, and
`LOCAL_LLM_ENABLED=true`. Langfuse remains optional. The `runs` and `show` history commands require
only the local database.

## Use the message-centric triage workspace

Release `0.15.0` makes `#email-triage` email-first. The default view shows one row per triaged Gmail
message with sender, subject, receipt time, latest successful recommendation, reason, and any newer
processing issue. Reused and forced attempts never duplicate the email. Runs, hashes, prompts,
usage, timing, traces, and interruption evidence remain available under **Diagnostics**.

Opening an email reads its stored normalized body and exact model input from SQLite; it makes no
Gmail request. Content is rendered only as text, never prefetched, never written to browser storage,
and cleared from query/component memory when closed or when authentication/workspace state changes.
The workspace cannot start triage, record feedback, schedule work, or modify Gmail.

Set `API_AUTH_ENABLED=true` and `EMAIL_TRIAGE_WORKSPACE_ENABLED=true`. Gmail, the model, triage, and
Langfuse may all be disabled while viewing persisted messages. `GMAIL_TRIAGE_REVIEW_ENABLED` is a
deprecated compatibility fallback for release `0.15.0`.

The accepted development-only records can be removed once, explicitly and with a protected backup:

```bash
python -m personal_edge_lab.apps.email_triage_cli reset-development-data \
  --confirm DELETE-ALL-EMAIL-TRIAGE-DATA
```

## Personal taxonomy and private sender rules

Release `0.15.1` uses `mckinsey`, `education`, `job`, `personal`, `admin`, `notification`,
`newsletter`, `slop`, and `other`. That order is the explicit precedence: contextual McKinsey,
education, and job evidence wins over broader message types. Model recommendations retain a
concise English reason.

An optional owner-only rules file can classify known senders before the model:

```dotenv
EMAIL_TRIAGE_RULES_FILE=/home/ubuntu/personal-edge-lab/secrets/email-triage-rules.json
```

Copy [the synthetic example](docs/examples/email-triage-rules.example.json), replace its example
addresses/domains only on RUBIK, and set mode `0600`. Rules support exact addresses and
domain/subdomain matches with explicit priorities—no regex or arbitrary substring matching.

```bash
python -m personal_edge_lab.apps.email_triage_cli rules-check
python -m personal_edge_lab.apps.ai_cli evaluate --fixture-set taxonomy-v2-core
```

A rule match records its stable rule identity and label, but performs no prompt lookup, UNO Q call,
or Langfuse trace and has no fabricated reason. Non-matches use prompt/taxonomy v2. The checked-in
synthetic baseline reports differences without imposing a quality threshold.

## Data and migrations

All applications run the same standard-library migration runner before opening a repository.
It creates `schema_migrations` and recognizes the existing telemetry/audit schema. Migration
`002_collector_runtime_status` adds operational status. `003_authenticated_control` adds sessions,
durable login throttling, audit attribution/idempotency, and a leased web-command lock.
`004_operational_alerts` adds evaluator runtime, alert states, incidents, and transition events.
`005_notification_outbox` adds atomic outbound delivery, owner pause policy, retry leases, and
delivery runtime. `006_email_triage_runs` adds durable dry-run lifecycles, unique evaluation
identities, run items, and separately auditable inference attempts.
`007_email_triage_messages` adds deduplicated message projections, immutable normalized-content
snapshots, evaluation/content links, private query text, and retained recommendation reasons.
`008_email_triage_taxonomy_v2` adds model-versus-rule evidence, private rule identity, and the
taxonomy-v2 labels while preserving legacy `work` and `billing` rows as read-only history.
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
