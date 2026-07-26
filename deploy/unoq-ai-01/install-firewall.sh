#!/usr/bin/env bash

set -Eeuo pipefail

readonly SOURCE_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly HELPER_SOURCE="$SOURCE_DIRECTORY/uno-ai-firewall"
readonly UNIT_SOURCE="$SOURCE_DIRECTORY/uno-ai-firewall.service"
readonly HELPER_DIRECTORY="/usr/local/libexec/personal-edge-lab"
readonly HELPER_TARGET="$HELPER_DIRECTORY/uno-ai-firewall"
readonly UNIT_TARGET="/etc/systemd/system/uno-ai-firewall.service"
readonly IPTABLES="/usr/sbin/iptables-legacy"
readonly IPTABLES_SAVE="/usr/sbin/iptables-legacy-save"
readonly IPTABLES_RESTORE="/usr/sbin/iptables-legacy-restore"
readonly BACKUP_ROOT="/var/backups/personal-edge-lab"

if [[ "$(id -u)" -ne 0 ]]; then
    printf 'ERROR: run this installer through sudo on unoq-ai-01.\n' >&2
    exit 1
fi

if [[ ! -f "$HELPER_SOURCE" || ! -f "$UNIT_SOURCE" ]]; then
    printf 'ERROR: reviewed firewall helper or systemd unit is missing beside the installer.\n' >&2
    exit 1
fi

if [[ ! -x "$IPTABLES" ]]; then
    apt-get update
    apt-get install --yes iptables
fi

[[ -x "$IPTABLES" && -x "$IPTABLES_SAVE" && -x "$IPTABLES_RESTORE" ]] || {
    printf 'ERROR: the UNO Q legacy iptables tools are unavailable.\n' >&2
    exit 1
}

readonly BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly BACKUP_DIRECTORY="$BACKUP_ROOT/unoq-ai-wp0-$BACKUP_STAMP"
readonly PRIOR_HELPER_MARKER="$BACKUP_DIRECTORY/prior-helper-present"
readonly PRIOR_UNIT_MARKER="$BACKUP_DIRECTORY/prior-unit-present"
readonly PRIOR_ENABLED_MARKER="$BACKUP_DIRECTORY/prior-unit-enabled"

install -d -m 0700 "$BACKUP_ROOT" "$BACKUP_DIRECTORY"
"$IPTABLES_SAVE" >"$BACKUP_DIRECTORY/iptables.rules"
chmod 0600 "$BACKUP_DIRECTORY/iptables.rules"
if [[ -e "$HELPER_TARGET" ]]; then
    cp --preserve=all "$HELPER_TARGET" "$BACKUP_DIRECTORY/uno-ai-firewall"
    touch "$PRIOR_HELPER_MARKER"
fi
if [[ -e "$UNIT_TARGET" ]]; then
    cp --preserve=all "$UNIT_TARGET" "$BACKUP_DIRECTORY/uno-ai-firewall.service"
    touch "$PRIOR_UNIT_MARKER"
fi
if systemctl is-enabled --quiet uno-ai-firewall.service 2>/dev/null; then
    touch "$PRIOR_ENABLED_MARKER"
fi

rollback() {
    local failure_code=$?
    set +e
    systemctl disable --now uno-ai-firewall.service
    "$IPTABLES_RESTORE" <"$BACKUP_DIRECTORY/iptables.rules"
    if [[ -e "$PRIOR_HELPER_MARKER" ]]; then
        install -m 0755 "$BACKUP_DIRECTORY/uno-ai-firewall" "$HELPER_TARGET"
    elif [[ -e "$HELPER_TARGET" ]]; then
        mv "$HELPER_TARGET" "$BACKUP_DIRECTORY/uno-ai-firewall.failed"
    fi
    if [[ -e "$PRIOR_UNIT_MARKER" ]]; then
        install -m 0644 "$BACKUP_DIRECTORY/uno-ai-firewall.service" "$UNIT_TARGET"
    elif [[ -e "$UNIT_TARGET" ]]; then
        mv "$UNIT_TARGET" "$BACKUP_DIRECTORY/uno-ai-firewall.service.failed"
    fi
    systemctl daemon-reload
    if [[ -e "$PRIOR_ENABLED_MARKER" ]]; then
        systemctl enable --now uno-ai-firewall.service
    fi
    printf 'ERROR: firewall installation failed; prior configuration restored from %s.\n' \
        "$BACKUP_DIRECTORY" >&2
    exit "$failure_code"
}
trap rollback ERR

install -d -m 0755 "$HELPER_DIRECTORY"
install -m 0755 "$HELPER_SOURCE" "$HELPER_TARGET"
install -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl disable nftables.service 2>/dev/null || true
systemctl reset-failed nftables.service 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now uno-ai-firewall.service

"$IPTABLES" --wait 5 --check INPUT \
    --protocol tcp --dport 8080 --jump UNO_AI_INPUT
"$IPTABLES" --wait 5 --check UNO_AI_INPUT \
    --source 192.168.1.81/32 --protocol tcp --dport 8080 --jump ACCEPT
"$IPTABLES" --wait 5 --check UNO_AI_INPUT \
    --protocol tcp --dport 8080 --jump DROP
systemctl is-enabled uno-ai-firewall.service
systemctl is-active uno-ai-firewall.service

trap - ERR
printf 'Firewall installed. Backup: %s\n' "$BACKUP_DIRECTORY"
