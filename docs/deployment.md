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

## Repeat Stage 2 deployments

After the first accepted rollout, deploy later changes from the RUBIK checkout with:

```bash
cd /home/ubuntu/personal-edge-lab
./scripts/deploy-rubik.sh
```

The script runs as `ubuntu` and requests `sudo` only for operating-system configuration and service
operations. It backs up the live configuration and database, reuses frontend and Python build
dependencies when their lock/configuration files are unchanged, builds and inspects the dashboard
wheel, applies idempotent migrations, updates systemd/Nginx configuration, restarts the two
application services, and verifies the LAN proxy. It installs Nginx, Avahi, SQLite CLI, or curl only
when missing.

For a rapid iteration that has already passed the full checks:

```bash
./scripts/deploy-rubik.sh --skip-tests
```

This still builds and inspects the frontend and wheel, backs up SQLite, applies migrations, updates
configuration, restarts services, and performs runtime health checks. It skips only frontend
lint/unit tests and Python tests/lint. Run the default command before treating a revision as an
accepted release.
