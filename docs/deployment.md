# Raspberry Pi controlled cutover

This runbook changes the package and telemetry service as one controlled operation. Run it from an
operator shell on the actual Raspberry/RUBIK host. Do not send a physical AC command automatically.

Set these shell variables only after discovering their real values:

```bash
SERVICE=telemetry-collector.service
REPO=/real/path/to/personal-edge-lab
VENV=/real/path/to/.venv
BACKUP_ROOT=/real/path/to/backups
```

Do not infer the service user, working directory, environment file, executable path, or restart
policy from this repository.

## 1. Capture the live baseline

```bash
cd "$REPO"
git rev-parse HEAD
systemctl cat "$SERVICE"
systemctl show "$SERVICE" \
  -p ActiveState -p SubState -p UnitFileState -p User -p WorkingDirectory \
  -p EnvironmentFiles -p ExecStart -p Restart -p RestartSec
systemctl status "$SERVICE" --no-pager
journalctl -u "$SERVICE" -n 100 --no-pager
sqlite3 data/telemetry.db \
  'SELECT id, device_id, received_at_utc, temperature_c FROM temperature_readings ORDER BY id DESC LIMIT 1;'
```

Save the unedited output with the deployment record. Copy the exact unit emitted by
`systemctl cat` into `deploy/systemd/` on the deployment branch. This repository intentionally
does not contain an invented unit; the checked-in file must be the one captured from the device.

## 2. Back up before stopping

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$BACKUP_ROOT/$STAMP"
install -d -m 0700 "$BACKUP"
cp --preserve=all "$REPO/data/telemetry.db" "$BACKUP/"
cp --preserve=all "$REPO/.env" "$BACKUP/"
systemctl cat "$SERVICE" >"$BACKUP/$SERVICE"
git -C "$REPO" rev-parse HEAD >"$BACKUP/installed-commit.txt"
sqlite3 "$BACKUP/telemetry.db" 'PRAGMA integrity_check;'
```

Record row counts for both tables. If the audit table does not yet exist, record zero rather than
creating it during this baseline step.

## 3. Check the ESP32 without changing AC state

Use the actual base URL from `.env`:

```bash
curl --fail --show-error --max-time 5 "$EDGE_NODE_BASE_URL/health"
curl --fail --show-error --max-time 5 "$EDGE_NODE_BASE_URL/temperature"
```

Validate that the temperature JSON matches the documented contract. Do not call `/ac/state` or
`/ac/off`.

## 4. Stop writes and install

```bash
sudo systemctl stop "$SERVICE"
systemctl is-active "$SERVICE"
cd "$REPO"
"$VENV/bin/python" -m pip install -e '.[dev]'
"$VENV/bin/python" -m pytest
"$VENV/bin/python" -m ruff check .
```

Apply migrations through either new composition root without sending AC:

```bash
set -a
source .env
set +a
"$VENV/bin/python" -m personal_edge_lab.apps.ac_cli history --limit 1
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
sqlite3 data/telemetry.db \
  'SELECT version, applied_at_utc FROM schema_migrations ORDER BY version;'
```

Compare both row counts with the baseline. The initial migration may add tables and indexes but
must not change existing rows.

## 5. Change only `ExecStart`

Start from the captured unit. Replace only its `ExecStart` command with:

```text
/real/path/to/.venv/bin/python -m personal_edge_lab.apps.telemetry_collector
```

Preserve the captured user, environment, working directory, restart policy, dependencies, and
installation target. Install that exact reviewed unit, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl start "$SERVICE"
systemctl status "$SERVICE" --no-pager
journalctl -u "$SERVICE" -n 100 --no-pager
```

Query several new rows. Their receipt timestamps should be approximately 15 seconds apart:

```bash
sqlite3 -header -column "$REPO/data/telemetry.db" \
  'SELECT id, received_at_utc, temperature_c FROM temperature_readings ORDER BY id DESC LIMIT 5;'
```

Temporarily restart or make the ESP32 unavailable only under operator control. Confirm a logged
failure, continued service activity, and a later stored reading with a recovery log.

## 6. Reboot acceptance

```bash
sudo reboot
```

After reconnecting:

```bash
systemctl is-enabled "$SERVICE"
systemctl is-active "$SERVICE"
journalctl -u "$SERVICE" -b --no-pager
sqlite3 -header -column "$REPO/data/telemetry.db" \
  'SELECT id, received_at_utc, temperature_c FROM temperature_readings ORDER BY id DESC LIMIT 5;'
"$VENV/bin/python" -m personal_edge_lab.apps.ac_cli history --limit 20
```

The final physical `set` or `off` test requires explicit operator confirmation because it changes
the air conditioner. Record the chosen command and observed physical result.

## Rollback

Rollback after any failed integrity, row-count, service, cadence, recovery, or reboot check:

```bash
sudo systemctl stop "$SERVICE"
```

Restore the previous commit/environment and the captured unit, reload `systemd`, and start the old
service. Restore `telemetry.db` only when integrity or row-count comparison proves it was altered;
otherwise retain readings written after the backup.

```bash
sudo systemctl daemon-reload
sudo systemctl start "$SERVICE"
systemctl status "$SERVICE" --no-pager
journalctl -u "$SERVICE" -n 100 --no-pager
```

Confirm that the old service produces a new reading before closing the rollback.

## Stage 3 authenticated-control rollout

Stage 3 is intentionally enabled in phases. Do not combine password creation, HTTPS cutover, and
the first physical command into one unattended operation.

### 1. Capture and build with both flags disabled

Back up `.env`, SQLite, both application units, Nginx, the installed commit/wheel, row counts, any
existing password hash, and `/etc/personal-edge-lab/tls`. Verify `PRAGMA integrity_check` before
installation. Build and test `0.4.0` normally, install it, and run migration
`003_authenticated_control` while retaining:

```dotenv
API_AUTH_ENABLED=false
API_AC_CONTROL_ENABLED=false
```

Stage 2 reads must remain usable and the collector must keep its normal cadence. Migration `003`
is additive; it does not rewrite telemetry or existing audit rows.

### 2. Provision and trust local HTTPS

On the trusted development workstation, with pinned mkcert v1.4.4:

```bash
./scripts/provision-local-tls.sh --copy-to ubuntu@rubik-edge-01.local
```

The helper prints the `rootCA.pem` path. Install that CA certificate manually as trusted on the
owner's phone and computer. Never copy `rootCA-key.pem` to RUBIK. Confirm the installed leaf key is
owned by `root:www-data` with mode `0640`, then install the checked-in Nginx configuration:

```bash
sudo install -m 0644 deploy/nginx/personal-edge-lab.conf \
  /etc/nginx/sites-available/personal-edge-lab
sudo ln -sfn /etc/nginx/sites-available/personal-edge-lab \
  /etc/nginx/sites-enabled/personal-edge-lab
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Verify port 80 redirects, the trusted browser loads `https://rubik-edge-01.local/`, an unknown
host is rejected, and `/health/live` cannot be proxied from the LAN.

### 3. Create the owner credential and enable authentication

With the environment loaded and authentication still disabled:

```bash
python -m personal_edge_lab.apps.auth_cli set-password
stat -c '%a %U %G %n' secrets/owner-password.hash
```

Use at least 14 characters. Configure the Stage 3 values from `.env.example`, set
`API_AUTH_ENABLED=true`, leave `API_AC_CONTROL_ENABLED=false`, and restart only the API. Verify:

- the login shell and assets load without a session;
- `/health` and all histories return 401 without a session;
- the owner can sign in over trusted HTTPS;
- login failures are generic and the durable throttle returns 429;
- logout clears access and cached protected values;
- `/docs` and `/openapi.json` are unavailable.

### 4. Enable controls without physical testing

Set `API_AC_CONTROL_ENABLED=true`, restart only the API, and exercise malformed, unauthenticated,
wrong-origin, missing-CSRF, missing-idempotency, duplicate, conflict, and rate-limit requests with
a mocked or non-physical adapter. Confirm those checks create no physical ESP32 request and that
well-formed domain-invalid commands produce a `rejected_locally` audit.

The checked deployment command validates TLS expiry and security prerequisites, backs up the
credential/TLS configuration, uses loopback liveness, and verifies unauthenticated reads:

```bash
./scripts/deploy-rubik.sh
```

### 5. Operator-controlled physical acceptance

From the dashboard review dialog, explicitly authorize exactly one cool Set State and one Power
Off action. For each, record:

- the normalized payload and idempotency key;
- one new audit ID attributed to `owner` and `dashboard`;
- the number of ESP32 requests (at most one);
- the displayed outcome and observed physical behavior.

Simulate or observe an unknown response and verify the UI warns that transmission may have
occurred and does not retry automatically. Reusing the same request key may only replay/recover
the recorded result.

Reboot and verify telemetry collector, API, Avahi, and Nginx start independently; HTTPS remains
trusted; sessions survive within their expiry bounds; telemetry cadence remains approximately 15
seconds; and the local AC CLI retains its output, modes, and exit codes.

### Stage 3 rollback

Disable `API_AC_CONTROL_ENABLED` first. Restore the retained `0.3.0` wheel, prior `.env`, API unit,
and Nginx HTTP configuration, then restart only API/Nginx. Migration `003` can remain because its
tables and nullable columns are ignored by `0.3.0`. Restore SQLite only when integrity evidence
shows actual corruption; otherwise preserve all telemetry and audit rows written since backup.

## Stage 1 read-only API rollout

The API is a second service and does not require stopping the collector. Capture the installed
commit, API unit state if it exists, SQLite integrity, row counts, and the latest telemetry row.
Back up `.env`, `telemetry.db`, and any existing API unit.

Add the API settings from `.env.example` to the real `.env`, then install and verify:

```bash
cd /home/ubuntu/personal-edge-lab
source .venv/bin/activate
set -a
source .env
set +a
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
```

Install the reviewed unit:

```bash
sudo cp deploy/systemd/personal-edge-lab-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now personal-edge-lab-api.service
systemctl status personal-edge-lab-api.service --no-pager
journalctl -u personal-edge-lab-api.service -n 100 --no-pager
```

Verify from the RUBIK and then another trusted-LAN device:

```bash
curl --fail --show-error http://127.0.0.1:8000/health
curl --fail --show-error http://192.168.1.81:8000/health
curl --fail --show-error http://192.168.1.81:8000/api/v1/telemetry/latest
curl --fail --show-error 'http://192.168.1.81:8000/api/v1/telemetry/history?limit=5'
curl --fail --show-error 'http://192.168.1.81:8000/api/v1/ac/history?limit=5'
```

Open `http://192.168.1.81:8000/docs` from the LAN. Confirm no mutating operations appear. While
querying the API, confirm the collector stays active and writes several new readings at its normal
cadence. The stored endpoints must continue working if the ESP32 is briefly unavailable.

Reboot the RUBIK and verify both services are enabled and active:

```bash
systemctl is-enabled telemetry-collector.service personal-edge-lab-api.service
systemctl is-active telemetry-collector.service personal-edge-lab-api.service
journalctl -u personal-edge-lab-api.service -b --no-pager
```

If acceptance fails, stop and disable only `personal-edge-lab-api.service`, restore the previous
package and API unit if necessary, reload systemd, and confirm telemetry continues. Stage 1 adds no
SQLite migration, so restore the database only if integrity or row-count evidence shows damage.

## Stage 2 dashboard and operational-health rollout

Stage 2 adds one SQLite table and updates both Python services. It does not add any physical
control route. Retain the installed `0.2.0` wheel or commit and capture the current environment,
database, service units, and any existing Nginx/Avahi configuration:

```bash
cd /home/ubuntu/personal-edge-lab
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="/home/ubuntu/backups/personal-edge-lab/$STAMP"
install -d -m 0700 "$BACKUP"
cp --preserve=all .env data/telemetry.db "$BACKUP/"
systemctl cat telemetry-collector.service >"$BACKUP/telemetry-collector.service"
systemctl cat personal-edge-lab-api.service >"$BACKUP/personal-edge-lab-api.service"
git rev-parse HEAD >"$BACKUP/installed-commit.txt"
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
```

Install the current Node.js 24 LTS official ARM64 build for the `ubuntu` build user if
`node --version` is not already version 24. Node is used only to compile assets. Then build and
test without stopping either running service:

```bash
source .venv/bin/activate
cd frontend
node --version
npm ci
npm run lint
npm test
npm run build
cd ..
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build --wheel
python -m zipfile -l dist/personal_edge_lab-0.3.0-py3-none-any.whl \
  | grep 'personal_edge_lab/apps/api/static/dashboard/index.html'
```

Install the built wheel, update only the Stage 2 API settings, and apply the additive migration:

```bash
python -m pip install --force-reinstall --no-deps \
  dist/personal_edge_lab-0.3.0-py3-none-any.whl
```

```dotenv
API_HOST=127.0.0.1
API_PORT=8000
API_TELEMETRY_STALE_AFTER_SECONDS=45
API_COLLECTOR_STALE_AFTER_SECONDS=45
API_DOCS_ENABLED=true
```

```bash
set -a
source .env
set +a
python -m personal_edge_lab.apps.ac_cli history --limit 1
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
sqlite3 data/telemetry.db \
  "SELECT version FROM schema_migrations ORDER BY version;"
```

Restart the collector first. Its first successful attempt creates the heartbeat and should store a
new reading within one normal interval:

```bash
sudo systemctl restart telemetry-collector.service
systemctl status telemetry-collector.service --no-pager
sqlite3 -header -column data/telemetry.db \
  'SELECT device_id, heartbeat_at_utc, last_attempt_outcome, last_success_at_utc,
          consecutive_failures FROM collector_runtime_status;'
```

Restart the API and verify its loopback interface:

```bash
sudo cp deploy/systemd/personal-edge-lab-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart personal-edge-lab-api.service
curl --fail --show-error http://127.0.0.1:8000/health
curl --fail --show-error \
  'http://127.0.0.1:8000/api/v1/telemetry/series?window=6h'
```

Install and enable the LAN name and proxy:

```bash
sudo apt-get update
sudo apt-get install -y avahi-daemon nginx
sudo cp deploy/nginx/personal-edge-lab.conf \
  /etc/nginx/sites-available/personal-edge-lab
sudo ln -sfn /etc/nginx/sites-available/personal-edge-lab \
  /etc/nginx/sites-enabled/personal-edge-lab
sudo nginx -t
sudo systemctl enable --now avahi-daemon nginx
sudo systemctl reload nginx
```

From the target phone and a desktop on the trusted LAN, open
`http://rubik-edge-01.local/` and `http://rubik-edge-01.local/docs`. Verify all three chart
windows, local timestamps, the read-only audit label, and mobile/desktop layout. Generate traffic
while confirming telemetry keeps its approximately 15-second cadence.

Under operator control, stop the collector and confirm `collector=stopped` and
`edge_node=unknown`; then restore it. If safe to make only the ESP32 unavailable, confirm
`collector=running` and `edge_node=unreachable`, followed by recovery. These tests must not invoke
an AC command.

Reboot and verify all four services and a new reading:

```bash
sudo reboot
systemctl is-active telemetry-collector.service personal-edge-lab-api.service \
  avahi-daemon.service nginx.service
curl --fail --show-error http://rubik-edge-01.local/health
```

### Stage 2 rollback

Reinstall the retained `0.2.0` artifact or commit, restore `.env` and the captured API unit, and
restart the collector/API. Disable the Stage 2 Nginx site if the old API must again be reached
directly on port 8000:

```bash
sudo unlink /etc/nginx/sites-enabled/personal-edge-lab
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl daemon-reload
sudo systemctl restart telemetry-collector.service personal-edge-lab-api.service
```

Migration `002_collector_runtime_status` is additive and `0.2.0` ignores it. Do not restore the
database unless integrity or row-count evidence proves corruption.

## Repeat accepted deployments

After the first accepted rollout, deploy later changes from the RUBIK checkout with:

```bash
cd /home/ubuntu/personal-edge-lab
./scripts/deploy-rubik.sh
```

The script runs as `ubuntu` and requests `sudo` only for operating-system configuration and service
operations. It backs up the live configuration and database, reuses frontend and Python build
dependencies when their lock/configuration files are unchanged, builds and inspects the dashboard
wheel, applies idempotent migrations, updates systemd/Nginx configuration, runs one initial alert
evaluation, enables its 30-second timer, restarts the API without interrupting the collector, and
verifies HTTPS. Its quality gate includes Ruff, formatting, Pyright, ShellCheck, the complete
Python suite, and frontend lint/unit/build checks. It installs Nginx, Avahi, SQLite CLI, or curl
only when missing.

For a rapid iteration that has already passed the full checks:

```bash
./scripts/deploy-rubik.sh --skip-tests
```

This still builds and inspects the frontend and wheel, backs up SQLite, applies migrations, updates
configuration, restarts the API/Nginx, and performs runtime health checks. It skips only frontend
lint/unit tests and Python tests/lint. Run the default command before treating a revision as an
accepted release.

## Stage 4 alert evaluator rollout and acceptance

Before deploying `0.5.0`, add the `ALERT_*` values from `.env.example` to the live `.env`. The
deployment refuses an interval other than 30 seconds so configuration cannot silently disagree
with the systemd timer.

The regular deployment command backs up any previous evaluator units and alert row counts, applies
additive migration `004_operational_alerts`, installs the one-shot service and timer, performs one
evaluation, and verifies its durable runtime status. It does not restart the collector.

After deployment, inspect the scheduler and recent transitions:

```bash
systemctl status personal-edge-lab-alert-evaluator.timer --no-pager
systemctl list-timers personal-edge-lab-alert-evaluator.timer
journalctl -u personal-edge-lab-alert-evaluator.service -n 100 --no-pager
sqlite3 data/telemetry.db \
  'SELECT device_id, alert_type, lifecycle, last_observed_at_utc FROM alert_states;'
sqlite3 data/telemetry.db \
  'SELECT id, alert_type, status, alerting_at_utc, recovered_at_utc FROM alert_incidents ORDER BY id DESC LIMIT 20;'
```

Acceptance requires observing normal clear state, one sustained telemetry-stale incident, one
recovery from a genuinely newer reading, one repeated-failure ESP32 incident, and one recovery.
Repeated evaluations must retain one active incident. During those checks, telemetry cadence must
remain approximately 15 seconds and dashboard/API traffic must send no AC command.

Reboot RUBIK and verify the collector, API, Nginx, Avahi, and alert timer start independently. The
one-shot evaluator service is normally inactive between runs; its `Result` must be `success`, while
the timer itself must be active.

To roll back, stop the alert scheduler before reinstalling `0.4.0`:

```bash
sudo systemctl disable --now personal-edge-lab-alert-evaluator.timer
```

Restore the retained `0.4.0` wheel, previous `.env`, API unit, and any prior proxy configuration,
then restart only affected services. Migration `004` may remain because `0.4.0` ignores its
additive tables. Restore SQLite only if integrity evidence proves actual corruption.

## Stage 5A Casadaqui owner operations rollout

Deploy `0.7.2` once with Telegram disabled so the package and administration CLI exist:

```dotenv
TELEGRAM_BOT_ENABLED=false
TELEGRAM_BOT_TOKEN_FILE=/home/ubuntu/personal-edge-lab/secrets/telegram-bot.token
TELEGRAM_OWNER_USER_ID=0
TELEGRAM_AC_COMMAND_RATE_LIMIT_PER_MINUTE=6
TELEGRAM_POLL_TIMEOUT_SECONDS=25
```

```bash
./scripts/deploy-rubik.sh
set -a
source .env
set +a
python -m personal_edge_lab.apps.telegram_cli set-token
```

The token prompt is hidden. It validates the token against Telegram and writes it atomically with
mode `0600`; do not paste the token into `.env`, Git, shell history, or deployment logs.

Send `/start` to `Casadaqui_bot` while the service is stopped, then run:

```bash
python -m personal_edge_lab.apps.telegram_cli discover-owner
```

Copy the emitted positive numeric value into `TELEGRAM_OWNER_USER_ID`, set
`TELEGRAM_BOT_ENABLED=true`, and deploy again:

```bash
./scripts/deploy-rubik.sh
systemctl status personal-edge-lab-telegram-bot.service --no-pager
journalctl -u personal-edge-lab-telegram-bot.service -n 50 --no-pager
```

This enables an internet-mediated owner operations channel even though the dashboard remains
LAN-only.
Before enabling it, protect the owner Telegram account with 2-Step Verification and an app
passcode. Never send the bot token, dashboard password, or Telegram login code through the bot.

Open `/start` and confirm the Status and Air conditioning capability menu. Open `/ac` and exercise
temperature adjustments plus the fan and vane submenus first. These edits
must add no AC audit row. **Enviar ajuste** sends the normalized settings shown in the panel
directly; Power Off retains a separate confirmation. The first Set State send and Power Off
confirmation are physical acceptance actions and remain under explicit operator control. Inspect
their attribution without exposing the token:

```bash
sqlite3 -header -column data/telemetry.db \
  "SELECT id, actor_id, request_source, command_type, outcome
   FROM ac_command_audit ORDER BY id DESC LIMIT 10;"
```

Open `/status` and confirm the API, collector, ESP32, telemetry, alerts, and Telegram lines agree
with the authenticated dashboard. Press **Actualizar** and confirm the same Telegram message is
edited without creating an AC audit row or changing collector cadence.

Exercise one callback from a message created before `0.7.2` and confirm it remains valid. After
testing update replay/double taps and an unavailable controller, reboot and verify the bot starts
independently. Roll back the channel without touching telemetry or the API:

```bash
sudo systemctl disable --now personal-edge-lab-telegram-bot.service
```

Restore the `0.7.1` wheel and restart only the bot if the refactor must be rolled back. Stage 5A
adds no migration; existing Telegram audit rows are valid command history and should remain.

## Stage 5B proactive Telegram alert rollout

First deploy `0.8.1` with delivery disabled:

```dotenv
TELEGRAM_NOTIFICATION_DELIVERY_ENABLED=false
TELEGRAM_NOTIFICATION_BATCH_SIZE=20
TELEGRAM_NOTIFICATION_LEASE_SECONDS=60
TELEGRAM_NOTIFICATION_MAX_AGE_SECONDS=86400
TELEGRAM_NOTIFICATION_RUNTIME_STALE_AFTER_SECONDS=90
OWNER_TIMEZONE=Europe/Madrid
```

```bash
./scripts/deploy-rubik.sh
sqlite3 data/telemetry.db \
  'SELECT version FROM schema_migrations WHERE version = "005_notification_outbox";'
```

After confirming the additive migration, set
`TELEGRAM_NOTIFICATION_DELIVERY_ENABLED=true` and deploy again. Casadaqui performs the delivery
cycle before each long poll; no additional service is installed.

```bash
./scripts/deploy-rubik.sh
journalctl -u personal-edge-lab-telegram-bot.service -n 100 --no-pager
sqlite3 -header -column data/telemetry.db \
  'SELECT status, COUNT(*) FROM notification_outbox GROUP BY status;'
```

Open `/notifications`, test a one-hour pause, reactivate it, and confirm `/status` reports
notification delivery as operational. Under controlled conditions, create one sustained telemetry
incident and one recovery. Each notifiable transition must have one outbox row and one Telegram
message; no AC audit or physical request may appear.

During a temporary Telegram outage, confirm the row remains pending with a sanitized error and a
future `next_attempt_at_utc`. Restore connectivity and confirm eventual delivery while `/status`
and `/ac` remain responsive. Reboot RUBIK and confirm policy, pending rows, and delivery runtime
survive.

To roll back, set `TELEGRAM_NOTIFICATION_DELIVERY_ENABLED=false`, reinstall `0.7.2`, and restart
Casadaqui plus the evaluator if the package changed. Migration `005` is additive and may remain.

## Stage 6A WP1 local-inference connectivity rollout

Release `0.9.0` adds only a packaged RUBIK diagnostic CLI. It adds no service, timer, migration,
mailbox access, or dashboard surface. Add the `LOCAL_LLM_*` values from `.env.example` to the live
configuration and deploy first with inference disabled:

```dotenv
LOCAL_LLM_ENABLED=false
LOCAL_LLM_BASE_URL=http://unoq-ai-01.local:8080
LOCAL_LLM_API_KEY_FILE=/home/ubuntu/personal-edge-lab/secrets/unoq-ai-01.key
LOCAL_LLM_MODEL=qwen3-1.7b-q4-k-m
LOCAL_LLM_HEALTH_TIMEOUT_SECONDS=5
LOCAL_LLM_TIMEOUT_SECONDS=60
LOCAL_LLM_MAX_INPUT_CHARS=512
LOCAL_LLM_MAX_OUTPUT_TOKENS=32
```

```bash
./scripts/deploy-rubik.sh
set -a
source .env
set +a
python -m personal_edge_lab.apps.ai_cli health
python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
```

Health must succeed without reading a key. Completion must exit `2` while disabled and must not
contact UNO Q. Then set `LOCAL_LLM_ENABLED=true` and deploy again. The deployment guard verifies
that the configured key is an absolute, non-symlinked, readable regular file owned by `ubuntu`
with mode `0600`, and copies it into the private deployment backup.

Run the bounded live test and both packaged commands:

```bash
RUN_UNOQ_LIVE_TESTS=true python -m pytest -m unoq_live
python -m personal_edge_lab.apps.ai_cli health
python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
```

Any valid completion envelope is acceptance evidence; exact instruction-following is not a WP1
quality gate. Confirm a temporary wrong key is categorized without exposing either key:

```bash
temporary_key="$(mktemp)"
chmod 0600 "$temporary_key"
python -c 'from pathlib import Path; import sys; Path(sys.argv[1]).write_text("x" * 32 + "\\n")' \
  "$temporary_key"
LOCAL_LLM_API_KEY_FILE="$temporary_key" \
  python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
rm -f -- "$temporary_key"
```

That command must report `authentication` and exit `5`. Confirm connection categorization:

```bash
LOCAL_LLM_BASE_URL=http://127.0.0.1:9 LOCAL_LLM_TIMEOUT_SECONDS=1 \
  python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
```

It must report `connection` and exit `3`. Inspect the CLI output and application logs and confirm
the real key/header, prompt, GGUF path, and provider error body are absent. Finally verify the API,
collector, alert evaluator, Telegram, dashboard, AC behavior, and WP0 firewall remain healthy.

Rollback requires only setting `LOCAL_LLM_ENABLED=false`, reinstalling the retained `0.8.1` wheel,
and restarting whichever existing processes received the package. No schema or mailbox rollback
exists, and the WP0 UNO Q firewall remains installed.

## Stage 6A WP2 provider-semantics rollout

Release `0.10.0` adds no service, timer, migration, mailbox access, or dashboard surface. Make all
changes in the trusted development checkout, commit and push them, and only then pull the reviewed
commit on RUBIK. Do not copy an uncommitted worktree directly onto the node.

Before deployment, add the two new values to RUBIK's `.env`:

```dotenv
LOCAL_LLM_MAX_CONCURRENCY=1
LOCAL_LLM_QUEUE_TIMEOUT_SECONDS=60
```

The deployment guard requires exactly one process-local permit and a queue timeout greater than
zero and no more than 300 seconds when inference is enabled. The queue timeout covers only local
permit acquisition. `LOCAL_LLM_TIMEOUT_SECONDS` remains the separate HTTP connect/write/pool/read
phase timeout. A queued request can therefore wait and then use its own HTTP timeout budget.

Deploy through the normal reviewed workflow:

```bash
git pull --ff-only
./scripts/deploy-rubik.sh
set -a
source .env
set +a
RUN_UNOQ_LIVE_TESTS=true python -m pytest -m unoq_live
python -m personal_edge_lab.apps.ai_cli health
python -m personal_edge_lab.apps.ai_cli ready
python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
```

`health` must succeed for either the documented ready `200` or loading `503` response. `ready`
must succeed only for `200 {"status":"ok"}`. Contract tests cover loading behavior; do not restart
or disrupt UNO Q solely to force it. Completion must make one authenticated HTTP attempt, with no
automatic retry.

Inspect the operation evidence and confirm it contains only the operation ID, command,
outcome/category, logical identity, queue/provider/total timing, attempt count, retry metadata, and
normalized usage. The real key/header, prompts, completion text, provider error bodies, and GGUF
path must remain absent from errors and logs.

Confirm the API reports `0.10.0`, SQLite integrity is `ok`, and the collector, alert evaluator,
Casadaqui, dashboard, Nginx, UNO Q service, and WP0 firewall remain healthy.

To roll back, set `LOCAL_LLM_ENABLED=false`, reinstall the retained `0.9.0` wheel, and restart only
the existing processes that received the package. The new environment values may remain unused.
There is no schema or mailbox rollback.

## Stage 6A combined WP3/WP5 observable-triage rollout

Release `0.11.0` adds no service, timer, migration, Gmail access, scheduler, persistence, or
dashboard surface. It adds an operator-invoked synthetic triage command, a packaged prompt
fallback, explicit prompt publication, and isolated Langfuse tracing.

First deploy with Langfuse disabled:

```dotenv
LANGFUSE_ENABLED=false
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY_FILE=/home/ubuntu/personal-edge-lab/secrets/langfuse-public.key
LANGFUSE_SECRET_KEY_FILE=/home/ubuntu/personal-edge-lab/secrets/langfuse-secret.key
LANGFUSE_TIMEOUT_SECONDS=2
```

```bash
git pull --ff-only
./scripts/deploy-rubik.sh
set -a
source .env
set +a
python -m personal_edge_lab.apps.ai_cli triage --fixture synthetic-invoice
```

The first run must report `local_fallback`, `Trace: unavailable`, and a strict label/reason result.
No trace is created while disabled.

Create one Langfuse Cloud project, keep its environment name `personal-edge-lab`, and install its
public and secret keys without printing them:

```bash
install -d -m 0700 /home/ubuntu/personal-edge-lab/secrets
install -m 0600 /dev/stdin \
  /home/ubuntu/personal-edge-lab/secrets/langfuse-public.key
install -m 0600 /dev/stdin \
  /home/ubuntu/personal-edge-lab/secrets/langfuse-secret.key
```

Enter each value interactively into its command, then set `LANGFUSE_ENABLED=true` and deploy again.
The deployment guard requires both paths to be absolute, regular, non-symlinked, owned by `ubuntu`,
mode `0600`, and one whitespace-free line of 32–256 characters. It copies both files into the
private timestamped deployment backup.

Publish and verify the prompt, then create one synthetic trace:

```bash
export LANGFUSE_PUBLIC_KEY="$(<"$LANGFUSE_PUBLIC_KEY_FILE")"
export LANGFUSE_SECRET_KEY="$(<"$LANGFUSE_SECRET_KEY_FILE")"
export LANGFUSE_BASE_URL
python -m personal_edge_lab.apps.ai_cli prompt-publish
npx langfuse-cli api prompts get personal-edge-lab/email-triage \
  --label production --json
python -m personal_edge_lab.apps.ai_cli triage --fixture synthetic-invoice
npx langfuse-cli api traces get TRACE_ID --fields core,io,observations --json
npx langfuse-cli api observations list --trace-id TRACE_ID \
  --fields basic,io,metadata,model,usage,prompt,metrics,trace_context --json
unset LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
```

The shell history records only the file-reading expressions, not either key value. Do not use the
CLI's `--public-key` or `--secret-key` arguments.

Use the trace ID printed by `triage` with the official Langfuse CLI. Confirm one root span named
`classify-email` and exactly one child generation named `generate-triage-decision`; tags
`email-triage` and `synthetic`; the exact linked prompt version; logical model, usage, queue/provider
timing, profile/taxonomy/schema versions; and meaningful synthetic input/output. Confirm the
synthetic `example.test` content is present and the Langfuse keys, UNO Q key/header, provider error
bodies, and GGUF path are absent.

Temporarily set `LANGFUSE_BASE_URL` to an unavailable HTTPS origin and rerun synthetic triage. It
must retain successful local inference with prompt source `local_fallback`; tracing may report only
sanitized unavailability. Restore the Cloud origin afterward.

Finally rerun:

```bash
RUN_UNOQ_LIVE_TESTS=true python -m pytest -m unoq_live
python -m personal_edge_lab.apps.ai_cli health
python -m personal_edge_lab.apps.ai_cli ready
python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
```

Confirm API version `0.11.0`, collector, alert evaluator, Casadaqui, dashboard, AC behavior, SQLite,
UNO Q, and the WP0 firewall remain healthy. Record actual output in the handoff; do not mark WP2 or
this release accepted from an unrecorded run.

Rollback sets `LANGFUSE_ENABLED=false`, reinstalls the retained `0.10.0` wheel, and restarts only
existing processes that received the package. The remote prompt may remain because it is inert
while disabled. No schema or mailbox rollback exists.

## Stage 6A WP6 read-only Gmail rollout

Release `0.12.0` adds no service, timer, migration, API route, dashboard surface, model call,
Langfuse trace, persistence, or mailbox mutation. It adds explicit personal-Gmail authorization
and a bounded metadata-only retrieval command.

### 1. Deploy disabled and prepare Google Cloud

Add the frozen values to `.env` before the first deployment:

```dotenv
GMAIL_READ_ENABLED=false
GMAIL_CLIENT_SECRET_FILE=/home/ubuntu/personal-edge-lab/secrets/gmail-client.json
GMAIL_TOKEN_FILE=/home/ubuntu/personal-edge-lab/secrets/gmail-token.json
GMAIL_TIMEOUT_SECONDS=10
GMAIL_DEFAULT_BATCH_SIZE=10
GMAIL_MAX_MESSAGE_BYTES=262144
GMAIL_MAX_NORMALIZED_CHARS=8000
GMAIL_OAUTH_CALLBACK_PORT=8765
```

In Google Cloud, enable the Gmail API, configure an External OAuth consent screen, add the personal
Gmail owner as a test user, and create Desktop app credentials. Download the client JSON on the
trusted workstation. The integration requests exactly:

```text
https://www.googleapis.com/auth/gmail.readonly
```

Do not add modify, compose, send, insert, label, or full-mail authority. External apps left in
Testing may receive refresh tokens that expire after seven days; reauthorization is expected in
WP6.

Deploy the package while retrieval remains disabled:

```bash
git pull --ff-only
./scripts/deploy-rubik.sh
```

### 2. Install the Desktop client privately

Copy the downloaded Desktop client JSON from the trusted workstation, then lock it down on RUBIK:

```bash
scp gmail-client.json \
  ubuntu@rubik-edge-01.local:/home/ubuntu/personal-edge-lab/secrets/gmail-client.json
ssh ubuntu@rubik-edge-01.local \
  'chmod 0600 /home/ubuntu/personal-edge-lab/secrets/gmail-client.json'
```

On RUBIK, verify metadata without printing the file:

```bash
stat -c '%a %U %G %n' "$GMAIL_CLIENT_SECRET_FILE"
```

The result must show mode `600` and owner `ubuntu`. Never display or paste the JSON into logs,
issues, commits, or chat.

### 3. Authorize through the SSH loopback tunnel

From the trusted workstation, open an interactive SSH connection that forwards the OAuth callback
port to RUBIK:

```bash
ssh -L 8765:127.0.0.1:8765 ubuntu@rubik-edge-01.local
```

In that same remote shell:

```bash
cd /home/ubuntu/personal-edge-lab
set -a
source .env
set +a
python -m personal_edge_lab.apps.email_triage_cli authorize
```

Open the printed Google authorization URL in a browser on the trusted workstation and approve only
read-only Gmail access. The browser callback to local port `8765` travels through the SSH tunnel to
the loopback-only listener on RUBIK.

Verify the token without printing it:

```bash
stat -c '%a %U %G %n' "$GMAIL_TOKEN_FILE"
python - "$GMAIL_TOKEN_FILE" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert value["scopes"] == ["https://www.googleapis.com/auth/gmail.readonly"]
print("Gmail token scope and JSON shape: valid")
PY
```

The token must be owned by `ubuntu` with mode `600`. If it already exists, authorization refuses
to overwrite it; use `authorize --replace-token` only after intentionally revoking or rotating the
credential.

### 4. Enable and accept bounded retrieval

Set `GMAIL_READ_ENABLED=true` and deploy again. The deployment guard now validates both credential
files, their exact ownership/mode, private JSON shape, and read-only token scope, then copies them
into the timestamped private deployment backup.

Run the smallest acceptance batch first:

```bash
python -m personal_edge_lab.apps.email_triage_cli fetch \
  --query "in:inbox newer_than:7d" \
  --limit 3
python -m personal_edge_lab.apps.email_triage_cli fetch \
  --query "in:inbox newer_than:7d" \
  --limit 10
```

Compare receipt time, message/thread IDs, sender, subject, content source, and normalized lengths
with Gmail. The command must not print the normalized body. Normal logs must not contain the raw
query, IDs, sender, subject, body, client secret, access/refresh token, authorization header, or
Gmail provider body.

Before and after both reads, confirm the same messages retain their read/unread state, labels,
archive state, and mailbox contents. The adapter exposes only list/get requests, so any mailbox
change fails acceptance.

### 5. Revocation and platform regression

Revoke the app from the Google Account connection/security settings and rerun the bounded fetch. It
must return sanitized category `authentication`, exit `5`, make no automatic Gmail API retry, and
show no provider response body. Restore access with:

```bash
python -m personal_edge_lab.apps.email_triage_cli authorize --replace-token
```

Then rerun:

```bash
RUN_UNOQ_LIVE_TESTS=true python -m pytest -m unoq_live
python -m personal_edge_lab.apps.ai_cli health
python -m personal_edge_lab.apps.ai_cli ready
python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
python -m personal_edge_lab.apps.ai_cli triage --fixture synthetic-invoice
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
```

Confirm API version `0.12.0`, collector, alert evaluator, Casadaqui, dashboard, AC behavior, SQLite,
Langfuse synthetic tracing, UNO Q, and the WP0 firewall remain healthy. Record owner-confirmed
evidence in `docs/stage-6a-wp6-handoff.md`; do not mark WP6 accepted from an unrecorded run.

### WP6 rollback

Set `GMAIL_READ_ENABLED=false`, reinstall the retained `0.11.0` wheel, and restart only existing
processes that received the package. The client and token files are inert while disabled; revoke
and remove them only as an explicit owner credential action. No database or mailbox rollback
exists.

## Stage 6A WP7 durable read-only triage rollout

Release `0.13.0` adds one manual Gmail-to-UNO-Q dry run and additive migration
`006_email_triage_runs`. It adds no service, timer, API route, dashboard, scheduler, retry,
confidence score, or Gmail write capability.

### 1. Deploy disabled

Add the new gate while preserving the accepted WP6 and local-model settings:

```dotenv
GMAIL_TRIAGE_ENABLED=false
```

Deploy:

```bash
git pull --ff-only
./scripts/deploy-rubik.sh
```

The deployment guard rejects `GMAIL_TRIAGE_ENABLED=true` unless both `GMAIL_READ_ENABLED=true` and
`LOCAL_LLM_ENABLED=true`. Existing Gmail, UNO Q, and optional Langfuse private files retain their
mode, ownership, validation, and private-backup requirements. The script backs up SQLite before
applying migration 006 and records row counts for all four triage tables when present.

Verify the disabled deployment:

```bash
sqlite3 data/telemetry.db \
  "SELECT version FROM schema_migrations WHERE version='006_email_triage_runs';"
sqlite3 data/telemetry.db 'PRAGMA integrity_check;'
python -m personal_edge_lab.apps.email_triage_cli triage \
  --query "in:inbox newer_than:7d" --limit 1
```

The migration must be present, integrity must report `ok`, and the triage command must exit `2`
without contacting Gmail or UNO Q.

### 2. Enable and run a bounded dry run

Set:

```dotenv
GMAIL_READ_ENABLED=true
LOCAL_LLM_ENABLED=true
GMAIL_TRIAGE_ENABLED=true
```

The accepted RUBIK mailbox runs required this host-specific inference budget:

```dotenv
LOCAL_LLM_TIMEOUT_SECONDS=180
```

The general diagnostic default remains 60 seconds. Real mailbox items took up to approximately
113 seconds during WP7 acceptance, so retaining the default on RUBIK would create false timeouts.

`LANGFUSE_ENABLED` remains independently optional. Deploy again, then run:

```bash
python -m personal_edge_lab.apps.email_triage_cli triage \
  --query "in:inbox newer_than:7d" \
  --limit 3
```

The command prints a run ID, explicit dry-run status, message fingerprints, trusted sender/subject,
proposed label/reason for new evaluations, prompt/model evidence, trace availability, and timing.
It must also print `Gmail changes: none`.

Inspect durable evidence:

```bash
python -m personal_edge_lab.apps.email_triage_cli runs --limit 20
python -m personal_edge_lab.apps.email_triage_cli show --run-id <run-id>
```

History intentionally omits raw queries, sender, subject, body, reason, compiled prompt, and raw
model output.

### 3. Verify reuse, forced attempts, and interruption

Repeat the same query and limit. Previously successful exact identities must show `reused`, with
the reason reported as intentionally not retained. The repeat must create no new UNO Q inference
or Langfuse trace.

Create one deliberate new evaluation:

```bash
python -m personal_edge_lab.apps.email_triage_cli triage \
  --query "in:inbox newer_than:7d" \
  --limit 3 \
  --new-attempt
```

This creates a new attempt for each matching successful identity and, when Langfuse is enabled, one
new redacted trace per actual inference.

For interruption acceptance, start a small bounded run and send `SIGINT` or `SIGTERM` only between
items. Completed items must remain successful; remaining retrieved items and the run must show
`interrupted`. Hard-crash leftovers remain non-successful and are recovered as interrupted after
the fixed 300-second stale boundary.

### 4. Privacy and platform acceptance

Audit logs, the four SQLite tables, and the accepted Langfuse traces. Real Gmail traces must contain
only hashes, lengths, source/cleanup flags, label, versions, model, usage, timing, and categorized
failure evidence. They retain the exact managed-prompt link but never the compiled email variables.
Normal logs and SQLite must contain none of the raw query, sender, subject, body, reason, compiled
prompt, raw output, Gmail/UNO Q/Langfuse credentials, provider error body, or GGUF path.

Confirm Gmail read state, labels, archive state, and mailbox contents are unchanged. Then rerun the
WP6 fetch, local-model health/readiness/completion, synthetic triage, opt-in UNO Q test, SQLite
integrity, API `0.13.0`, collector, alert evaluator, Telegram, Casadaqui/dashboard, AC, UNO Q, and
WP0 firewall checks. Record only observed evidence in `docs/stage-6a-wp7-handoff.md`.

### WP7 rollback

Set `GMAIL_TRIAGE_ENABLED=false`, reinstall the retained `0.12.0` wheel, and restart only existing
processes that received the package. Migration 006 remains as an inert additive schema; do not
drop its tables. No mailbox, prompt, trace, or OAuth rollback exists.
