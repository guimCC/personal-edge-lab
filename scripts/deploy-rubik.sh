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

  --skip-tests  Skip frontend lint/unit tests and Python tests/lint.
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

for command in flock git node npm python3 sha256sum; do
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
[[ -n "${DATABASE_PATH:-}" ]] || fail "DATABASE_PATH is missing from .env"

if [[ "$DATABASE_PATH" = /* ]]; then
    DATABASE_FILE="$DATABASE_PATH"
else
    DATABASE_FILE="$PROJECT_ROOT/$DATABASE_PATH"
fi

log "Checking administrator access"
sudo -v

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

log "Backing up configuration, database, and deployed units"
DEPLOY_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEPLOY_BACKUP="/home/ubuntu/backups/personal-edge-lab/$DEPLOY_STAMP"
install -d -m 0700 "$DEPLOY_BACKUP"
cp --preserve=all "$PROJECT_ROOT/.env" "$DEPLOY_BACKUP/.env"
git rev-parse HEAD >"$DEPLOY_BACKUP/installed-commit.txt"
git status --short >"$DEPLOY_BACKUP/working-tree.txt"

if [[ -f "$DATABASE_FILE" ]]; then
    sqlite3 "$DATABASE_FILE" ".backup '$DEPLOY_BACKUP/telemetry.db'"
    sqlite3 "$DATABASE_FILE" 'PRAGMA integrity_check;' | grep -qx 'ok'
fi

for unit in telemetry-collector.service personal-edge-lab-api.service; do
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
    || ! "$BUILD_PYTHON" -m ruff --version >/dev/null 2>&1; then
    "$BUILD_PYTHON" -m pip install --upgrade pip
    "$BUILD_PYTHON" -m pip install -e "$PROJECT_ROOT[dev]"
    printf '%s\n' "$PYPROJECT_HASH" >"$PYPROJECT_STAMP"
else
    printf 'Python development dependencies are unchanged; reusing .build-venv.\n'
fi

if [[ "$SKIP_TESTS" == false ]]; then
    log "Checking Python"
    "$BUILD_PYTHON" -m pytest
    "$BUILD_PYTHON" -m ruff check .
    "$BUILD_PYTHON" -m ruff format --check .
fi

log "Building and inspecting wheel"
WHEEL_DIR="$(mktemp -d)"
"$BUILD_PYTHON" -m build --wheel --outdir "$WHEEL_DIR"

mapfile -t WHEELS < <(find "$WHEEL_DIR" -maxdepth 1 -type f -name '*.whl' -print)
[[ "${#WHEELS[@]}" -eq 1 ]] || fail "expected exactly one wheel, found ${#WHEELS[@]}"
WHEEL="${WHEELS[0]}"

"$BUILD_PYTHON" - "$WHEEL" <<'PY'
from pathlib import Path
from sys import argv
from zipfile import ZipFile

wheel = Path(argv[1])
required_suffixes = (
    "personal_edge_lab/apps/api/static/dashboard/index.html",
    "personal_edge_lab/apps/api/static/dashboard/.vite/manifest.json",
)
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
missing = [name for name in required_suffixes if name not in names]
if missing:
    raise SystemExit(f"wheel is missing dashboard files: {', '.join(missing)}")
PY

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
sqlite3 "$DATABASE_FILE" 'PRAGMA integrity_check;' | grep -qx 'ok'

log "Updating systemd and Nginx configuration"
sudo install -d -m 0755 /etc/systemd/system/telemetry-collector.service.d
sudo install -m 0644 \
    deploy/systemd/telemetry-collector.service.d/override.conf \
    /etc/systemd/system/telemetry-collector.service.d/override.conf
sudo install -m 0644 \
    deploy/systemd/personal-edge-lab-api.service \
    /etc/systemd/system/personal-edge-lab-api.service
sudo install -m 0644 \
    deploy/nginx/personal-edge-lab.conf \
    /etc/nginx/sites-available/personal-edge-lab
sudo ln -sfn /etc/nginx/sites-available/personal-edge-lab \
    /etc/nginx/sites-enabled/personal-edge-lab

sudo systemctl daemon-reload
sudo nginx -t

log "Restarting application services"
sudo systemctl enable telemetry-collector.service personal-edge-lab-api.service >/dev/null
sudo systemctl restart telemetry-collector.service
sudo systemctl restart personal-edge-lab-api.service
sudo systemctl enable --now avahi-daemon.service nginx.service >/dev/null
sudo systemctl reload nginx.service

log "Verifying services and HTTP endpoints"
for service in \
    telemetry-collector.service \
    personal-edge-lab-api.service \
    avahi-daemon.service \
    nginx.service; do
    systemctl is-active --quiet "$service" || fail "$service is not active"
done

HEALTH_OK=false
for _attempt in {1..15}; do
    if curl --fail --silent --show-error \
        http://127.0.0.1:8000/health >"$WHEEL_DIR/health.json"; then
        HEALTH_OK=true
        break
    fi
    sleep 1
done
[[ "$HEALTH_OK" == true ]] || fail "API health endpoint did not become available"

curl --fail --silent --show-error \
    -H 'Host: rubik-edge-01.local' \
    http://127.0.0.1/health >/dev/null
curl --fail --silent --show-error \
    -H 'Host: rubik-edge-01.local' \
    http://127.0.0.1/ | grep -q '<div id="root"></div>'

INSTALLED_VERSION="$(
    "$RUNTIME_PYTHON" -c \
        "import importlib.metadata as m; print(m.version('personal-edge-lab'))"
)"

printf '\nDeployment successful.\n'
printf 'Version: %s\n' "$INSTALLED_VERSION"
printf 'Backup: %s\n' "$DEPLOY_BACKUP"
printf 'Dashboard: http://rubik-edge-01.local/\n'
printf 'API docs: http://rubik-edge-01.local/docs\n'
