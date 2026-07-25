#!/usr/bin/env bash
#
# Generate or renew the leaf certificate on the trusted development workstation.
# The mkcert CA private key remains in mkcert's CAROOT and is never copied.

set -Eeuo pipefail

EXPECTED_MKCERT_VERSION="v1.4.4"
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIRECTORY="$PROJECT_ROOT/.local-tls"
RUBIK_TARGET=""

usage() {
    cat <<'EOF'
Usage: ./scripts/provision-local-tls.sh [--copy-to ubuntu@rubik-edge-01.local]

Generate a rubik-edge-01.local leaf certificate with mkcert v1.4.4.
With --copy-to, install only the leaf certificate and leaf key on RUBIK.
EOF
}

while (($#)); do
    case "$1" in
        --copy-to)
            [[ $# -ge 2 ]] || {
                usage >&2
                exit 2
            }
            RUBIK_TARGET="$2"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
    shift
done

command -v mkcert >/dev/null || {
    printf 'mkcert v1.4.4 is required on this trusted workstation.\n' >&2
    exit 1
}
INSTALLED_MKCERT_VERSION="$(mkcert -version)"
[[ "v${INSTALLED_MKCERT_VERSION#v}" == "$EXPECTED_MKCERT_VERSION" ]] || {
    printf 'Expected mkcert %s, found %s.\n' \
        "$EXPECTED_MKCERT_VERSION" "$INSTALLED_MKCERT_VERSION" >&2
    exit 1
}

install -d -m 0700 "$OUTPUT_DIRECTORY"
CERTIFICATE="$OUTPUT_DIRECTORY/rubik-edge-01.local.pem"
PRIVATE_KEY="$OUTPUT_DIRECTORY/rubik-edge-01.local-key.pem"

mkcert -install
mkcert \
    -cert-file "$CERTIFICATE" \
    -key-file "$PRIVATE_KEY" \
    rubik-edge-01.local
chmod 0600 "$PRIVATE_KEY"
chmod 0644 "$CERTIFICATE"

openssl x509 -in "$CERTIFICATE" -noout -subject -issuer -dates
CA_ROOT="$(mkcert -CAROOT)"
printf '\nTrust this CA certificate on the owner devices:\n%s/rootCA.pem\n' "$CA_ROOT"
printf 'Keep the CA private key in %s off RUBIK.\n' "$CA_ROOT"

if [[ -n "$RUBIK_TARGET" ]]; then
    REMOTE_CERTIFICATE="/tmp/pel-rubik-edge-01.local.pem"
    REMOTE_KEY="/tmp/pel-rubik-edge-01.local-key.pem"
    scp "$CERTIFICATE" "$RUBIK_TARGET:$REMOTE_CERTIFICATE"
    scp "$PRIVATE_KEY" "$RUBIK_TARGET:$REMOTE_KEY"
    # The fixed temporary paths are intentionally expanded into the remote command.
    # shellcheck disable=SC2029
    ssh "$RUBIK_TARGET" \
        "sudo install -d -m 0750 -o root -g www-data /etc/personal-edge-lab/tls \
        && sudo install -m 0644 -o root -g root '$REMOTE_CERTIFICATE' \
            /etc/personal-edge-lab/tls/rubik-edge-01.local.pem \
        && sudo install -m 0640 -o root -g www-data '$REMOTE_KEY' \
            /etc/personal-edge-lab/tls/rubik-edge-01.local-key.pem \
        && rm -f '$REMOTE_CERTIFICATE' '$REMOTE_KEY'"
    printf 'Installed the leaf certificate and key on %s.\n' "$RUBIK_TARGET"
fi
