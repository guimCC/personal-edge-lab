# UNO Q local-inference contract

## Status

**Node:** `unoq-ai-01`

**Stage:** 6A Work Package 0

**Status:** Accepted on RUBIK on 2026-07-26.

This document freezes the operational contract between RUBIK and the first UNO Q inference node.
It records only non-secret configuration and bounded acceptance evidence.

## Stable identities

| Role | Hostname | Observed/reserved IPv4 | Runtime user |
| --- | --- | --- | --- |
| Platform caller | `rubik-edge-01.local` | `192.168.1.81` | `ubuntu` |
| Inference node | `unoq-ai-01.local` | `192.168.1.159` | `arduino` |

RUBIK uses `http://unoq-ai-01.local:8080` as the canonical base URL. RUBIK resolved this name
correctly before and after an UNO Q reboot, so the application contract does not require a router
reservation for the observed UNO Q address. `192.168.1.159` is operational evidence, not
application configuration. If mDNS becomes unreliable, reserve an address before replacing the
canonical URL with an IP address. A changed RUBIK address requires updating and re-accepting the
firewall rule before inference is enabled.

On 2026-07-26, RUBIK resolved `unoq-ai-01.local` to `192.168.1.159`, routed to it from
`192.168.1.81`, received `200 {"status":"ok"}` from `GET /health`, and received `401` from an
unauthenticated `POST /v1/chat/completions`.

## Runtime contract

The node runs Debian 13 on AArch64 with Linux `6.16.7-g0dd6551ae96b`. User lingering is enabled for
`arduino`, so the user-level service starts without an interactive login.

| Property | Frozen value |
| --- | --- |
| Service | `uno-ai.service`, enabled user unit |
| Unit path | `/home/arduino/.config/systemd/user/uno-ai.service` |
| Executable | `/home/arduino/projects/llama.cpp/build/bin/llama-server` |
| llama.cpp commit | `ff067f76dd8e9e05f0528056f1274adf01a54d70` |
| Build version | `1 (ff067f7)`, GNU 14.2.0, Linux AArch64 |
| Model | `/home/arduino/models/Qwen3-1.7B-Q4_K_M.gguf` |
| Model size | `1,282,439,584` bytes |
| Model SHA-256 | `72c5c3cb38fa32d5256e2fe30d03e7a64c6c79e668ad84057e3bd66e250b24fb` |
| Context | 1024 tokens |
| Threads | 4 |
| Parallel slots | 1, explicitly configured |
| Bind | `0.0.0.0:8080`, restricted by a dedicated legacy-iptables chain |
| Restart | `on-failure`, five-second delay |
| Stop timeout | 20 seconds |
| API-key file | `/home/arduino/.config/uno-ai/api-keys` |

The API-key file contains one 64-character key and is owned by `arduino:arduino` with mode `0600`.
Its value and any digest of its value are excluded from Git, logs, screenshots, and acceptance
records.

The owner chose to remove the benchmark-only `Qwen_Qwen3-4B-Q4_K_M.gguf` after its poor latency and
swap behavior were recorded. Its exact 2,497,280,960-byte file was deleted on 2026-07-26 after
verifying the service referenced only the 1.7B model. The production model is now the only file in
`/home/arduino/models`.

## HTTP boundary

`GET /health` is intentionally unauthenticated and must return only minimal readiness information.
It must not disclose model paths, API keys, prompts, input, or email data.

From release `0.10.0`, the RUBIK client interprets the endpoint at two explicit operational levels:
a documented `200` or loading `503` proves that the HTTP process is live, while only
`200 {"status":"ok"}` proves that the model is ready. These concrete deployment probes remain
separate from the generic `LanguageModel` completion port.

`POST /v1/chat/completions` requires bearer authentication. Missing and invalid keys return `401`.
The Stage 6A production caller sends bounded requests and permits at most one in-flight inference.
The UNO Q never receives Gmail credentials and never initiates work.

The endpoint is local-network infrastructure, not a general LAN service. TCP 8080 is accepted only
from RUBIK at `192.168.1.81`; every other source is dropped at the UNO Q.

## Secret placement

The server key remains at:

```text
/home/arduino/.config/uno-ai/api-keys
```

The same key is installed for the RUBIK service account at:

```text
/home/ubuntu/personal-edge-lab/secrets/unoq-ai-01.key
```

The RUBIK directory is owned by `ubuntu:ubuntu` with mode `0700`; the key file is owned by
`ubuntu:ubuntu` with mode `0600`. The repository ignores `secrets/`. The key is never placed in
`.env`, SQLite, a command-line argument, logs, or test fixtures. `.env` contains only the key-file
path once Work Package 1 introduces the setting.

The first RUBIK copy was installed and permission-checked on 2026-07-26. The validation recorded
one 64-character line and 65 bytes including the trailing newline without printing the key.

## Installation

### Service

Back up the current unit, install the reviewed capture, reload the user manager, and restart only
the inference service:

```bash
install -d -m 0700 /home/arduino/.local/state/uno-ai/backups
cp --preserve=all /home/arduino/.config/systemd/user/uno-ai.service \
  /home/arduino/.local/state/uno-ai/backups/uno-ai.service.pre-wp0
install -m 0600 deploy/unoq-ai-01/uno-ai.service \
  /home/arduino/.config/systemd/user/uno-ai.service
systemctl --user daemon-reload
systemctl --user restart uno-ai.service
systemctl --user is-active uno-ai.service
```

The deployed copy must come from a reviewed checkout or secure transfer of the repository file.

### Firewall

The captured baseline had no active firewall manager. The first installation attempt established
that the custom UNO Q kernel has `CONFIG_NF_TABLES` disabled, so nftables cannot initialize its
Netlink protocol. That attempt restored the prior configuration automatically.

The kernel does provide working `ip_tables`, `iptable_filter`, `x_tables`, and `xt_tcpudp` modules.
The reviewed replacement therefore uses `/usr/sbin/iptables-legacy`, one additive
`UNO_AI_INPUT` chain, and a dedicated boot service. It backs up the complete existing legacy rules
without flushing or replacing unrelated chains and restores them automatically on installation
failure. Keep the administrative SSH session open until a second session succeeds.

From the repository checkout or a securely transferred copy, run:

```bash
sudo deploy/unoq-ai-01/install-firewall.sh
```

The installer prints its timestamped backup directory. If validation, SSH, or RUBIK access fails
after installation, restore `iptables.rules` and any prior helper/unit from that exact directory.

## Key rotation

Rotation is operator-controlled and never prints either key.

1. Back up the current UNO Q key to a mode-`0600` file in a mode-`0700` private directory.
2. Generate a new 32-byte random key into a new mode-`0600` file on the UNO Q.
3. Transfer that file directly to a temporary mode-`0600` path on RUBIK.
4. Validate ownership, mode, one-line shape, and length without printing the value.
5. Atomically replace the RUBIK client key, then the UNO Q server key.
6. Restart `uno-ai.service` and run one bounded authenticated completion from RUBIK.
7. On failure, restore both previous files and restart the service.
8. After acceptance, remove the superseded copies. Do not use flash-media `shred` as a guarantee of
   physical erasure.

The current `llama-server` reads the key file at process startup, so rotation requires a service
restart.

## Acceptance matrix

| Check | Before firewall | After firewall | After service restart | After UNO Q reboot |
| --- | --- | --- | --- | --- |
| RUBIK resolves canonical hostname | Required | Required | Required | Required |
| RUBIK `GET /health` returns minimal `200` | Required | Required | Required | Required |
| RUBIK unauthenticated completion returns `401` | Required | Required | Required | Required |
| RUBIK authenticated bounded completion succeeds | Required | Required | Required | Required |
| Non-RUBIK client reaches TCP 8080 | Baseline only | Must fail | Must fail | Must fail |
| Service is enabled and active | Required | Required | Required | Required |
| One parallel slot is configured | Required | Required | Required | Required |
| Swap remains unused during one bounded request | Record | Record | Record | Record |

Record elapsed time, prompt/completion token counts when available, process RSS, process swap, host
memory, and host swap for the authenticated request. Store no prompt or completion text beyond the
fixed synthetic diagnostic.

### Evidence recorded on 2026-07-26

- RUBIK resolved the canonical hostname, reached the minimal health response, and received `401`
  for an unauthenticated completion before and after the service change.
- The reviewed service with `--parallel 1` was installed with mode `0600`, reloaded, restarted, and
  observed as both enabled and active. The prior unit is retained with mode `0600` under
  `/home/arduino/.local/state/uno-ai/backups/`.
- A bounded authenticated request from RUBIK returned a valid HTTP/provider envelope in 8.329
  seconds with 15 prompt tokens, 16 completion tokens, and 31 total tokens.
- The model did not follow the diagnostic's exact-text instruction within the 16-token output
  bound. This is model-quality evidence for Work Packages 3 and 4, not an infrastructure failure.
- Across 30 one-second samples surrounding that request, process RSS ranged from 1,443,560 to
  1,450,140 KiB, process swap remained zero, the highest observed process CPU reading was 83.9%,
  minimum host available memory was 3,028,716 KiB, and host free swap remained 1,879,004 KiB.
- A non-RUBIK workstation still received the minimal `200` health response after the service
  restart. This was the expected pre-firewall baseline and proved source filtering was still
  pending at that point.
- The first nftables installation failed because the UNO Q kernel does not support its Netlink
  protocol. The installer restored the prior configuration and left inference and SSH healthy.
- The compatible `uno-ai-firewall.service` was then enabled and started with the prior legacy rules
  retained under `/var/backups/personal-edge-lab/unoq-ai-wp0-20260726T165938Z`.
- After source filtering, RUBIK received health `200`, unauthenticated completion `401`, and
  authenticated completion `200`; the bounded authenticated call completed in 2.464 seconds.
- In the same state, the non-RUBIK workstation timed out on TCP 8080 while SSH to the UNO Q
  remained available. The inference and firewall services were both enabled and active.
- The UNO Q then rebooted at 2026-07-26 17:01 UTC. User lingering remained enabled; the firewall
  and inference services started automatically with zero inference-service restarts.
- After reboot, the server retained Qwen3 1.7B, context 1024, four threads, and one parallel slot.
  Idle process RSS was 1,443,416 KiB and process swap was zero.
- After reboot, RUBIK received minimal health `200`, unauthenticated completion `401`, and
  authenticated completion `200` in 3.247 seconds. The non-RUBIK workstation still timed out while
  SSH remained available.

## Rollback

For a service regression, restore `uno-ai.service.pre-wp0`, reload the user manager, and restart the
service. For a firewall regression, remove only the `inet uno_ai` table and restore the previously
captured `nftables` configuration. A rollback is successful only when SSH still works and the
pre-change health/authentication behavior is restored.

Do not roll back by selecting the 4B model, disabling authentication, widening TCP 8080 to the LAN,
or copying a key into a command line.

## Acceptance result

Work Package 0 is accepted. RUBIK has a stable canonical URL and private key path; the production
model and single-request limit are unambiguous; authentication, resource behavior, restart, and
reboot were verified; and the inference port is source-restricted to RUBIK.
