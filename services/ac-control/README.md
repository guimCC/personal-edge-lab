# AC control

`ac_control` sends validated, high-level air-conditioner commands from the RUBIK Pi to the ESP32.
It does not generate IR, infer missing state, retry commands, or claim knowledge of the physical
AC state.

## Configuration

The CLI reads:

```text
AC_NODE_BASE_URL=http://ac-controller-01.local
AC_COMMAND_TIMEOUT_SECONDS=5
AC_DEVICE_ID=ac-controller-01
DATABASE_PATH=./data/telemetry.db
LOG_LEVEL=INFO
```

It does not automatically load `.env`; export that file in the shell before use.

## Commands

Send one complete state:

```bash
python -m ac_control set \
  --power on \
  --temperature 24 \
  --mode cool \
  --fan auto \
  --vertical-vane middle
```

`--power` accepts `on` or `off`. Temperatures are integer values from 16 through 31. Modes are
`auto`, `cool`, `heat`, `dry`, and `fan`; fan values are `auto`, `low`, `medium`, `high`, and
`max`; vertical vane values are `auto`, `highest`, `high`, `middle`, `low`, `lowest`, and `swing`.

Use the dedicated off endpoint or inspect the audit:

```bash
python -m ac_control off
python -m ac_control history --limit 20
```

`off` can receive HTTP 503 after an ESP32 restart because the firmware does not persist the last
complete AC state.

## Outcomes and exit codes

| Outcome | Meaning | Exit |
| --- | --- | --- |
| `confirmed_success` | ESP32 returned the exact command success response | 0 |
| `rejected_locally` | Local validation prevented transmission | 2 |
| `node_unreachable` | DNS, connection, or transport failure | 3 |
| `timeout_unknown` | Request timed out; transmission may have occurred | 4 |
| `response_unknown` | HTTP 200 response did not match the contract | 4 |
| `node_reported_failure` | ESP32 returned a non-200 response | 5 |

Unexpected local or SQLite failures exit with code 1. Every recognized command attempt is stored
in `ac_command_audit`, initially as `pending` and then with its final outcome.

## RUBIK Pi installation and use

```bash
cd ~/personal-edge-lab
git pull
source .venv/bin/activate
python -m pip install -e '.[dev]'

set -a
source .env
set +a

python -m ac_control set \
  --power on \
  --temperature 24 \
  --mode cool \
  --fan auto \
  --vertical-vane middle
python -m ac_control history --limit 20
```

The telemetry collector remains the only long-running systemd service. Do not create an AC command
service; commands are intentionally issued on demand.
