#!/usr/bin/env bash
#
# Build, install, configure, and verify Personal Edge Lab on rubik-edge-01.
#
# Run as the normal ubuntu user from any directory:
#   ./scripts/deploy-rubik.sh
#   ./scripts/deploy-rubik.sh --skip-tests

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
RUNTIME_PYTHON="$PROJECT_ROOT/.venv/bin/python"
BUILD_VENV="$PROJECT_ROOT/.build-venv"
BUILD_PYTHON="$BUILD_VENV/bin/python"
STATE_DIR="$PROJECT_ROOT/.deploy-state"
EXPECTED_ROOT="/home/ubuntu/personal-edge-lab"
SKIP_TESTS=false
DEPLOY_BACKUP=""
WHEEL_DIR=""

usage() {
    cat <<'EOF'
Usage: ./scripts/deploy-rubik.sh [--skip-tests]

Build and deploy the current checkout on rubik-edge-01.

  --skip-tests  Skip frontend and Python quality checks.
  -h, --help    Show this help.
EOF
}

log() {
    printf '\n==> %s\n' "$*"
}

fail() {
    printf '\nERROR: %s\n' "$*" >&2
    if [[ -n "$DEPLOY_BACKUP" ]]; then
        printf 'Backup retained at: %s\n' "$DEPLOY_BACKUP" >&2
    fi
    exit 1
}

on_error() {
    local exit_code=$?
    printf '\nERROR: deployment stopped at line %s (exit %s).\n' "$1" "$exit_code" >&2
    if [[ -n "$DEPLOY_BACKUP" ]]; then
        printf 'Backup retained at: %s\n' "$DEPLOY_BACKUP" >&2
    fi
    exit "$exit_code"
}

cleanup() {
    if [[ -n "$WHEEL_DIR" && -d "$WHEEL_DIR" ]]; then
        rm -rf -- "$WHEEL_DIR"
    fi
}

trap 'on_error "$LINENO"' ERR
trap cleanup EXIT

while (($#)); do
    case "$1" in
        --skip-tests)
            SKIP_TESTS=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "unknown argument: $1"
            ;;
    esac
    shift
done

[[ "$(id -u)" -ne 0 ]] || fail "run this script as ubuntu, not root"
[[ "$(id -un)" == "ubuntu" ]] || fail "this deployment is locked to the ubuntu user"
[[ "$PROJECT_ROOT" == "$EXPECTED_ROOT" ]] || {
    fail "expected checkout at $EXPECTED_ROOT, found $PROJECT_ROOT"
}
[[ -x "$RUNTIME_PYTHON" ]] || fail "runtime virtual environment is missing: $RUNTIME_PYTHON"
[[ -f "$PROJECT_ROOT/.env" ]] || fail "configuration is missing: $PROJECT_ROOT/.env"
[[ -f "$PROJECT_ROOT/frontend/package-lock.json" ]] || fail "frontend lockfile is missing"

for command in flock git node npm openssl python3 sha256sum; do
    command -v "$command" >/dev/null || fail "required command is missing: $command"
done

NODE_MAJOR="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
[[ "$NODE_MAJOR" == "24" ]] || fail "Node.js 24 is required; found $(node --version)"

cd "$PROJECT_ROOT"
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/deploy.lock"
flock -n 9 || fail "another deployment is already running"

set -a
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.env"
set +a

[[ "${API_HOST:-}" == "127.0.0.1" ]] || fail "API_HOST must be 127.0.0.1"
[[ "${API_PORT:-}" == "8000" ]] || fail "API_PORT must be 8000"
[[ "${API_COLLECTOR_STALE_AFTER_SECONDS:-}" == "45" ]] || {
    fail "API_COLLECTOR_STALE_AFTER_SECONDS must be 45"
}
[[ "${ALERT_EVALUATION_INTERVAL_SECONDS:-}" == "30" ]] || {
    fail "ALERT_EVALUATION_INTERVAL_SECONDS must match the 30-second systemd timer"
}
[[ "${ALERT_TELEMETRY_SUSPECT_AFTER_SECONDS:-}" == "45" ]] || {
    fail "ALERT_TELEMETRY_SUSPECT_AFTER_SECONDS must be 45"
}
[[ "${ALERT_TELEMETRY_ALERT_AFTER_SECONDS:-}" == "180" ]] || {
    fail "ALERT_TELEMETRY_ALERT_AFTER_SECONDS must be 180"
}
[[ "${ALERT_EDGE_MIN_CONSECUTIVE_FAILURES:-}" == "4" ]] || {
    fail "ALERT_EDGE_MIN_CONSECUTIVE_FAILURES must be 4"
}
[[ "${ALERT_EDGE_ALERT_AFTER_SECONDS:-}" == "45" ]] || {
    fail "ALERT_EDGE_ALERT_AFTER_SECONDS must be 45"
}
[[ "${ALERT_RECOVERY_DISPLAY_SECONDS:-}" == "300" ]] || {
    fail "ALERT_RECOVERY_DISPLAY_SECONDS must be 300"
}
[[ "${ALERT_EVALUATOR_STALE_AFTER_SECONDS:-}" == "90" ]] || {
    fail "ALERT_EVALUATOR_STALE_AFTER_SECONDS must be 90"
}
[[ -n "${DATABASE_PATH:-}" ]] || fail "DATABASE_PATH is missing from .env"

log "Checking administrator access"
if ! sudo -n true 2>/dev/null; then
    sudo -v
fi

TLS_DIRECTORY="/etc/personal-edge-lab/tls"
TLS_CERTIFICATE="$TLS_DIRECTORY/rubik-edge-01.local.pem"
TLS_PRIVATE_KEY="$TLS_DIRECTORY/rubik-edge-01.local-key.pem"
sudo test -f "$TLS_CERTIFICATE" || fail "TLS leaf certificate is missing: $TLS_CERTIFICATE"
sudo test -f "$TLS_PRIVATE_KEY" || fail "TLS leaf key is missing: $TLS_PRIVATE_KEY"
[[ "$(sudo stat -c '%a' "$TLS_PRIVATE_KEY")" == "640" ]] || {
    fail "TLS leaf key must have mode 640"
}
sudo openssl x509 -checkend 1209600 -noout -in "$TLS_CERTIFICATE" || {
    fail "TLS certificate expires in less than 14 days"
}

AUTH_ENABLED="${API_AUTH_ENABLED:-false}"
CONTROL_ENABLED="${API_AC_CONTROL_ENABLED:-false}"
TELEGRAM_ENABLED="${TELEGRAM_BOT_ENABLED:-false}"
TELEGRAM_NOTIFICATIONS_ENABLED="${TELEGRAM_NOTIFICATION_DELIVERY_ENABLED:-false}"
LOCAL_LLM_ENABLED_VALUE="${LOCAL_LLM_ENABLED:-false}"
LANGFUSE_ENABLED_VALUE="${LANGFUSE_ENABLED:-false}"
if [[ "$AUTH_ENABLED" == "true" ]]; then
    [[ "${PUBLIC_ORIGIN:-}" == "https://rubik-edge-01.local" ]] || {
        fail "authenticated deployment requires PUBLIC_ORIGIN=https://rubik-edge-01.local"
    }
    [[ -n "${AUTH_PASSWORD_HASH_FILE:-}" ]] || {
        fail "AUTH_PASSWORD_HASH_FILE is required when authentication is enabled"
    }
    [[ -r "$AUTH_PASSWORD_HASH_FILE" ]] || {
        fail "owner password hash is not readable: $AUTH_PASSWORD_HASH_FILE"
    }
    [[ "$(stat -c '%a' "$AUTH_PASSWORD_HASH_FILE")" == "600" ]] || {
        fail "owner password hash must have mode 600"
    }
    [[ "${API_DOCS_ENABLED:-}" == "false" ]] || {
        fail "authenticated production deployment requires API_DOCS_ENABLED=false"
    }
fi
if [[ "$CONTROL_ENABLED" == "true" ]]; then
    [[ "$AUTH_ENABLED" == "true" ]] || fail "controls require API_AUTH_ENABLED=true"
    [[ "${API_DOCS_ENABLED:-}" == "false" ]] || {
        fail "controls require API_DOCS_ENABLED=false"
    }
fi
if [[ "$TELEGRAM_ENABLED" == "true" ]]; then
    [[ -n "${TELEGRAM_BOT_TOKEN_FILE:-}" ]] || {
        fail "TELEGRAM_BOT_TOKEN_FILE is required when the Telegram bot is enabled"
    }
    [[ -r "$TELEGRAM_BOT_TOKEN_FILE" ]] || {
        fail "Telegram bot token is not readable: $TELEGRAM_BOT_TOKEN_FILE"
    }
    [[ "$(stat -c '%a' "$TELEGRAM_BOT_TOKEN_FILE")" == "600" ]] || {
        fail "Telegram bot token must have mode 600"
    }
    [[ "${TELEGRAM_OWNER_USER_ID:-0}" =~ ^[1-9][0-9]*$ ]] || {
        fail "TELEGRAM_OWNER_USER_ID must be a positive integer"
    }
fi
if [[ "$TELEGRAM_NOTIFICATIONS_ENABLED" == "true" ]]; then
    [[ "$TELEGRAM_ENABLED" == "true" ]] || {
        fail "Telegram notification delivery requires TELEGRAM_BOT_ENABLED=true"
    }
    [[ "${OWNER_TIMEZONE:-Europe/Madrid}" == "Europe/Madrid" ]] || {
        fail "Stage 5B deployment requires OWNER_TIMEZONE=Europe/Madrid"
    }
fi
if [[ "$LOCAL_LLM_ENABLED_VALUE" == "true" ]]; then
    [[ "${LOCAL_LLM_MAX_CONCURRENCY:-}" == "1" ]] || {
        fail "LOCAL_LLM_MAX_CONCURRENCY must be exactly 1"
    }
    [[ "${LOCAL_LLM_QUEUE_TIMEOUT_SECONDS:-}" =~ ^([0-9]+)(\.[0-9]+)?$ ]] || {
        fail "LOCAL_LLM_QUEUE_TIMEOUT_SECONDS must be a positive number"
    }
    awk -v value="$LOCAL_LLM_QUEUE_TIMEOUT_SECONDS" \
        'BEGIN { exit !(value > 0 && value <= 300) }' || {
        fail "LOCAL_LLM_QUEUE_TIMEOUT_SECONDS must be from greater than 0 through 300"
    }
    [[ -n "${LOCAL_LLM_API_KEY_FILE:-}" ]] || {
        fail "LOCAL_LLM_API_KEY_FILE is required when local inference is enabled"
    }
    [[ "$LOCAL_LLM_API_KEY_FILE" = /* ]] || {
        fail "LOCAL_LLM_API_KEY_FILE must be absolute"
    }
    [[ ! -L "$LOCAL_LLM_API_KEY_FILE" ]] || {
        fail "local inference key must not be a symbolic link"
    }
    [[ -f "$LOCAL_LLM_API_KEY_FILE" && -r "$LOCAL_LLM_API_KEY_FILE" ]] || {
        fail "local inference key must be a readable regular file"
    }
    [[ "$(stat -c '%a' "$LOCAL_LLM_API_KEY_FILE")" == "600" ]] || {
        fail "local inference key must have mode 600"
    }
    [[ "$(stat -c '%U' "$LOCAL_LLM_API_KEY_FILE")" == "$(id -un)" ]] || {
        fail "local inference key must be owned by the deployment user"
    }
    mapfile -t LOCAL_LLM_KEY_LINES <"$LOCAL_LLM_API_KEY_FILE"
    [[ "${#LOCAL_LLM_KEY_LINES[@]}" -eq 1 ]] || {
        fail "local inference key must contain exactly one line"
    }
    [[ "${#LOCAL_LLM_KEY_LINES[0]}" -ge 32 && "${#LOCAL_LLM_KEY_LINES[0]}" -le 256 ]] || {
        fail "local inference key must contain between 32 and 256 characters"
    }
    [[ ! "${LOCAL_LLM_KEY_LINES[0]}" =~ [[:space:]] ]] || {
        fail "local inference key must not contain whitespace"
    }
    unset LOCAL_LLM_KEY_LINES
fi
if [[ "$LANGFUSE_ENABLED_VALUE" == "true" ]]; then
    [[ "${LANGFUSE_BASE_URL:-}" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$ ]] || {
        fail "LANGFUSE_BASE_URL must be an origin-only HTTPS URL"
    }
    [[ "${LANGFUSE_TIMEOUT_SECONDS:-}" =~ ^([0-9]+)(\.[0-9]+)?$ ]] || {
        fail "LANGFUSE_TIMEOUT_SECONDS must be a positive number"
    }
    awk -v value="$LANGFUSE_TIMEOUT_SECONDS" \
        'BEGIN { exit !(value > 0 && value <= 30) }' || {
        fail "LANGFUSE_TIMEOUT_SECONDS must be from greater than 0 through 30"
    }
    for LANGFUSE_KEY_SETTING in LANGFUSE_PUBLIC_KEY_FILE LANGFUSE_SECRET_KEY_FILE; do
        LANGFUSE_KEY_PATH="${!LANGFUSE_KEY_SETTING:-}"
        [[ -n "$LANGFUSE_KEY_PATH" ]] || {
            fail "$LANGFUSE_KEY_SETTING is required when Langfuse is enabled"
        }
        [[ "$LANGFUSE_KEY_PATH" = /* ]] || fail "$LANGFUSE_KEY_SETTING must be absolute"
        [[ ! -L "$LANGFUSE_KEY_PATH" ]] || {
            fail "$LANGFUSE_KEY_SETTING must not be a symbolic link"
        }
        [[ -f "$LANGFUSE_KEY_PATH" && -r "$LANGFUSE_KEY_PATH" ]] || {
            fail "$LANGFUSE_KEY_SETTING must be a readable regular file"
        }
        [[ "$(stat -c '%a' "$LANGFUSE_KEY_PATH")" == "600" ]] || {
            fail "$LANGFUSE_KEY_SETTING must have mode 600"
        }
        [[ "$(stat -c '%U' "$LANGFUSE_KEY_PATH")" == "$(id -un)" ]] || {
            fail "$LANGFUSE_KEY_SETTING must be owned by the deployment user"
        }
        mapfile -t LANGFUSE_KEY_LINES <"$LANGFUSE_KEY_PATH"
        [[ "${#LANGFUSE_KEY_LINES[@]}" -eq 1 ]] || {
            fail "$LANGFUSE_KEY_SETTING must contain exactly one line"
        }
        [[ "${#LANGFUSE_KEY_LINES[0]}" -ge 32 \
            && "${#LANGFUSE_KEY_LINES[0]}" -le 256 ]] || {
            fail "$LANGFUSE_KEY_SETTING must contain between 32 and 256 characters"
        }
        [[ ! "${LANGFUSE_KEY_LINES[0]}" =~ [[:space:]] ]] || {
            fail "$LANGFUSE_KEY_SETTING must not contain whitespace"
        }
        unset LANGFUSE_KEY_LINES LANGFUSE_KEY_PATH
    done
    unset LANGFUSE_KEY_SETTING
fi

if [[ "$DATABASE_PATH" = /* ]]; then
    DATABASE_FILE="$DATABASE_PATH"
else
    DATABASE_FILE="$PROJECT_ROOT/$DATABASE_PATH"
fi

SYSTEM_PACKAGES=()
command -v curl >/dev/null || SYSTEM_PACKAGES+=(curl)
command -v sqlite3 >/dev/null || SYSTEM_PACKAGES+=(sqlite3)
command -v nginx >/dev/null || SYSTEM_PACKAGES+=(nginx)
systemctl list-unit-files avahi-daemon.service --no-legend 2>/dev/null \
    | grep -q '^avahi-daemon\.service' || SYSTEM_PACKAGES+=(avahi-daemon)

if ((${#SYSTEM_PACKAGES[@]})); then
    log "Installing missing system packages: ${SYSTEM_PACKAGES[*]}"
    sudo apt-get update
    sudo apt-get install -y "${SYSTEM_PACKAGES[@]}"
fi

sqlite_live() {
    # Collector and alert-evaluator writes are brief; wait for them instead of failing deployment.
    sqlite3 -cmd ".timeout 15000" "$DATABASE_FILE" "$@"
}

log "Backing up configuration, database, and deployed units"
DEPLOY_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEPLOY_BACKUP="/home/ubuntu/backups/personal-edge-lab/$DEPLOY_STAMP"
install -d -m 0700 "$DEPLOY_BACKUP"
cp --preserve=all "$PROJECT_ROOT/.env" "$DEPLOY_BACKUP/.env"
git rev-parse HEAD >"$DEPLOY_BACKUP/installed-commit.txt"
git status --short >"$DEPLOY_BACKUP/working-tree.txt"

if [[ -f "$DATABASE_FILE" ]]; then
    sqlite_live ".backup '$DEPLOY_BACKUP/telemetry.db'"
    sqlite_live 'PRAGMA integrity_check;' | grep -qx 'ok'
    sqlite_live \
        'SELECT "temperature_readings", COUNT(*) FROM temperature_readings
         UNION ALL SELECT "ac_command_audit", COUNT(*) FROM ac_command_audit;' \
        >"$DEPLOY_BACKUP/row-counts.txt"
    if sqlite_live \
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alert_incidents';" \
        | grep -qx '1'; then
        sqlite_live \
            'SELECT "alert_incidents", COUNT(*) FROM alert_incidents
             UNION ALL SELECT "alert_states", COUNT(*) FROM alert_states
             UNION ALL SELECT "alert_transition_events", COUNT(*)
             FROM alert_transition_events;' \
            >>"$DEPLOY_BACKUP/row-counts.txt"
    fi
fi

if [[ -n "${AUTH_PASSWORD_HASH_FILE:-}" && -f "$AUTH_PASSWORD_HASH_FILE" ]]; then
    cp --preserve=all "$AUTH_PASSWORD_HASH_FILE" \
        "$DEPLOY_BACKUP/owner-password.hash"
fi
if [[ -n "${TELEGRAM_BOT_TOKEN_FILE:-}" && -f "$TELEGRAM_BOT_TOKEN_FILE" ]]; then
    cp --preserve=all "$TELEGRAM_BOT_TOKEN_FILE" \
        "$DEPLOY_BACKUP/telegram-bot.token"
fi
if [[ "$LOCAL_LLM_ENABLED_VALUE" == "true" ]]; then
    cp --preserve=all "$LOCAL_LLM_API_KEY_FILE" \
        "$DEPLOY_BACKUP/unoq-ai-01.key"
fi
if [[ "$LANGFUSE_ENABLED_VALUE" == "true" ]]; then
    cp --preserve=all "$LANGFUSE_PUBLIC_KEY_FILE" \
        "$DEPLOY_BACKUP/langfuse-public.key"
    cp --preserve=all "$LANGFUSE_SECRET_KEY_FILE" \
        "$DEPLOY_BACKUP/langfuse-secret.key"
fi
sudo cp -a "$TLS_DIRECTORY" "$DEPLOY_BACKUP/tls"

for unit in \
    telemetry-collector.service \
    personal-edge-lab-api.service \
    personal-edge-lab-alert-evaluator.service \
    personal-edge-lab-alert-evaluator.timer \
    personal-edge-lab-telegram-bot.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
        systemctl cat "$unit" >"$DEPLOY_BACKUP/$unit"
    fi
done

if [[ -f /etc/nginx/sites-available/personal-edge-lab ]]; then
    sudo cp --preserve=all /etc/nginx/sites-available/personal-edge-lab \
        "$DEPLOY_BACKUP/nginx-personal-edge-lab.conf"
fi

log "Preparing frontend dependencies"
LOCK_HASH="$(sha256sum frontend/package-lock.json | awk '{print $1}')"
LOCK_STAMP="$STATE_DIR/frontend-lock.sha256"
NEED_NPM_CI=true

if [[ -d frontend/node_modules ]] \
    && (cd frontend && npm ls --depth=0 >/dev/null 2>&1); then
    if [[ ! -f "$LOCK_STAMP" ]] || grep -qx "$LOCK_HASH" "$LOCK_STAMP"; then
        NEED_NPM_CI=false
        printf '%s\n' "$LOCK_HASH" >"$LOCK_STAMP"
    fi
fi

export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--dns-result-order=ipv4first"

if [[ "$NEED_NPM_CI" == true ]]; then
    (
        cd frontend
        npm ci --prefer-offline --no-audit --no-fund
    )
    printf '%s\n' "$LOCK_HASH" >"$LOCK_STAMP"
else
    printf 'Frontend dependencies are unchanged; skipping npm ci.\n'
fi

if [[ "$SKIP_TESTS" == false ]]; then
    log "Checking frontend"
    (
        cd frontend
        npm run lint
        npm test
    )
fi

log "Building frontend"
(
    cd frontend
    npm run build
)

[[ -f src/personal_edge_lab/apps/api/static/dashboard/index.html ]] || {
    fail "frontend build did not produce dashboard/index.html"
}
[[ -f src/personal_edge_lab/apps/api/static/dashboard/.vite/manifest.json ]] || {
    fail "frontend build did not produce dashboard/.vite/manifest.json"
}

log "Preparing isolated development tools"
PYPROJECT_HASH="$(sha256sum pyproject.toml | awk '{print $1}')"
PYPROJECT_STAMP="$STATE_DIR/pyproject.sha256"

if [[ ! -x "$BUILD_PYTHON" ]]; then
    python3 -m venv "$BUILD_VENV"
fi

if [[ ! -f "$PYPROJECT_STAMP" ]] \
    || ! grep -qx "$PYPROJECT_HASH" "$PYPROJECT_STAMP" \
    || ! "$BUILD_PYTHON" -c 'import build, pytest' >/dev/null 2>&1 \
    || ! "$BUILD_PYTHON" -m ruff --version >/dev/null 2>&1 \
    || ! "$BUILD_VENV/bin/pyright" --version >/dev/null 2>&1 \
    || ! "$BUILD_VENV/bin/shellcheck" --version >/dev/null 2>&1; then
    "$BUILD_PYTHON" -m pip install --upgrade pip
    "$BUILD_PYTHON" -m pip install -e "${PROJECT_ROOT}[dev]"
    printf '%s\n' "$PYPROJECT_HASH" >"$PYPROJECT_STAMP"
else
    printf 'Python development dependencies are unchanged; reusing .build-venv.\n'
fi

if [[ "$SKIP_TESTS" == false ]]; then
    log "Checking Python"
    "$BUILD_PYTHON" -m pytest
    "$BUILD_PYTHON" -m ruff check src tests hatch_build.py scripts/inspect_wheel.py
    "$BUILD_PYTHON" -m ruff format --check src tests hatch_build.py scripts/inspect_wheel.py
    "$BUILD_VENV/bin/pyright" --pythonpath "$BUILD_PYTHON"
    "$BUILD_VENV/bin/shellcheck" scripts/*.sh
fi

log "Building and inspecting wheel"
WHEEL_DIR="$(mktemp -d)"
"$BUILD_PYTHON" -m build --wheel --outdir "$WHEEL_DIR"

mapfile -t WHEELS < <(find "$WHEEL_DIR" -maxdepth 1 -type f -name '*.whl' -print)
[[ "${#WHEELS[@]}" -eq 1 ]] || fail "expected exactly one wheel, found ${#WHEELS[@]}"
WHEEL="${WHEELS[0]}"

"$BUILD_PYTHON" scripts/inspect_wheel.py "$WHEEL"

install -d -m 0755 "$PROJECT_ROOT/dist"
cp "$WHEEL" "$PROJECT_ROOT/dist/$(basename -- "$WHEEL")"

log "Installing wheel into runtime environment"
"$RUNTIME_PYTHON" -m pip install --upgrade "$WHEEL"
"$RUNTIME_PYTHON" -m pip install --force-reinstall --no-deps "$WHEEL"

log "Applying migrations and checking SQLite"
"$RUNTIME_PYTHON" - <<'PY'
import os
from pathlib import Path

from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

run_migrations(Path(os.environ["DATABASE_PATH"]))
PY
sqlite_live 'PRAGMA integrity_check;' | grep -qx 'ok'

log "Updating systemd and Nginx configuration"
sudo install -d -m 0755 /etc/systemd/system/telemetry-collector.service.d
sudo install -m 0644 \
    deploy/systemd/telemetry-collector.service.d/override.conf \
    /etc/systemd/system/telemetry-collector.service.d/override.conf
sudo install -m 0644 \
    deploy/systemd/personal-edge-lab-api.service \
    /etc/systemd/system/personal-edge-lab-api.service
sudo install -m 0644 \
    deploy/systemd/personal-edge-lab-alert-evaluator.service \
    /etc/systemd/system/personal-edge-lab-alert-evaluator.service
sudo install -m 0644 \
    deploy/systemd/personal-edge-lab-alert-evaluator.timer \
    /etc/systemd/system/personal-edge-lab-alert-evaluator.timer
sudo install -m 0644 \
    deploy/systemd/personal-edge-lab-telegram-bot.service \
    /etc/systemd/system/personal-edge-lab-telegram-bot.service
sudo install -m 0644 \
    deploy/nginx/personal-edge-lab.conf \
    /etc/nginx/sites-available/personal-edge-lab
sudo ln -sfn /etc/nginx/sites-available/personal-edge-lab \
    /etc/nginx/sites-enabled/personal-edge-lab
sudo rm -f /etc/nginx/sites-enabled/default

sudo systemctl daemon-reload
sudo nginx -t

log "Restarting application services"
sudo systemctl enable telemetry-collector.service personal-edge-lab-api.service >/dev/null
sudo systemctl restart personal-edge-lab-api.service
sudo systemctl start personal-edge-lab-alert-evaluator.service
sudo systemctl enable --now personal-edge-lab-alert-evaluator.timer >/dev/null
if [[ "$TELEGRAM_ENABLED" == "true" ]]; then
    sudo systemctl enable personal-edge-lab-telegram-bot.service >/dev/null
    sudo systemctl restart personal-edge-lab-telegram-bot.service
else
    sudo systemctl disable --now personal-edge-lab-telegram-bot.service >/dev/null 2>&1 || true
fi
if [[ "$TELEGRAM_NOTIFICATIONS_ENABLED" == "true" ]]; then
    NOTIFICATION_RUNTIME_OK=false
    for _attempt in {1..10}; do
        if sqlite_live \
            "SELECT COUNT(*) FROM notification_delivery_runtime
             WHERE singleton_id = 1
               AND last_outcome = 'success'
               AND last_finished_at_utc IS NOT NULL;" \
            | grep -qx '1'; then
            NOTIFICATION_RUNTIME_OK=true
            break
        fi
        sleep 1
    done
    [[ "$NOTIFICATION_RUNTIME_OK" == "true" ]] || {
        fail "Casadaqui notification delivery runtime did not become healthy"
    }
fi
sudo systemctl enable --now avahi-daemon.service nginx.service >/dev/null
sudo systemctl reload nginx.service

log "Verifying services and HTTPS endpoints"
for service in \
    telemetry-collector.service \
    personal-edge-lab-api.service \
    personal-edge-lab-alert-evaluator.timer \
    avahi-daemon.service \
    nginx.service; do
    systemctl is-active --quiet "$service" || fail "$service is not active"
done
if [[ "$TELEGRAM_ENABLED" == "true" ]]; then
    systemctl is-active --quiet personal-edge-lab-telegram-bot.service || {
        fail "personal-edge-lab-telegram-bot.service is not active"
    }
fi

EVALUATOR_RESULT="$(
    systemctl show personal-edge-lab-alert-evaluator.service --property=Result --value
)"
[[ "$EVALUATOR_RESULT" == "success" ]] || {
    fail "initial operational alert evaluation failed (result: $EVALUATOR_RESULT)"
}
sqlite_live \
    "SELECT COUNT(*) FROM alert_runtime_status
     WHERE singleton_id = 1
       AND last_outcome = 'success'
       AND last_finished_at_utc IS NOT NULL;" \
    | grep -qx '1' || fail "alert evaluator did not persist a successful runtime status"

HEALTH_OK=false
for _attempt in {1..15}; do
    if curl --fail --silent --show-error \
        http://127.0.0.1:8000/health/live >"$WHEEL_DIR/health-live.json"; then
        HEALTH_OK=true
        break
    fi
    sleep 1
done
[[ "$HEALTH_OK" == true ]] || fail "API liveness endpoint did not become available"

HTTP_REDIRECT=""
for _attempt in {1..15}; do
    HTTP_REDIRECT="$(
        curl --silent --output /dev/null --write-out '%{http_code}' \
            -H 'Host: rubik-edge-01.local' http://127.0.0.1/
    )"
    [[ "$HTTP_REDIRECT" == "308" ]] && break
    sleep 1
done
[[ "$HTTP_REDIRECT" == "308" ]] || {
    fail "HTTP did not redirect to HTTPS (last status: $HTTP_REDIRECT)"
}

curl --insecure --fail --silent --show-error \
    --resolve rubik-edge-01.local:443:127.0.0.1 \
    https://rubik-edge-01.local/ | grep -q '<div id="root"></div>'

PROTECTED_STATUS="$(
    curl --insecure --silent --output /dev/null --write-out '%{http_code}' \
        --resolve rubik-edge-01.local:443:127.0.0.1 \
        https://rubik-edge-01.local/health
)"
if [[ "$AUTH_ENABLED" == "true" ]]; then
    [[ "$PROTECTED_STATUS" == "401" ]] || {
        fail "unauthenticated /health did not return 401"
    }
else
    [[ "$PROTECTED_STATUS" == "200" ]] || {
        fail "Stage 2-compatible /health did not return 200"
    }
fi

INSTALLED_VERSION="$(
    "$RUNTIME_PYTHON" -c \
        "import importlib.metadata as m; print(m.version('personal-edge-lab'))"
)"

printf '\nDeployment successful.\n'
printf 'Version: %s\n' "$INSTALLED_VERSION"
printf 'Backup: %s\n' "$DEPLOY_BACKUP"
printf 'Dashboard: https://rubik-edge-01.local/\n'
if [[ "$TELEGRAM_ENABLED" == "true" ]]; then
    printf 'Casadaqui operations bot: enabled\n'
else
    printf 'Casadaqui operations bot: disabled\n'
fi
if [[ "$TELEGRAM_NOTIFICATIONS_ENABLED" == "true" ]]; then
    printf 'Proactive Telegram notifications: enabled\n'
else
    printf 'Proactive Telegram notifications: disabled\n'
fi
if [[ "${API_DOCS_ENABLED:-false}" == "true" ]]; then
    printf 'API docs: https://rubik-edge-01.local/docs\n'
else
    printf 'API docs: disabled\n'
fi
