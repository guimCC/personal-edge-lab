# Captured systemd configuration

This directory records the configuration captured from `rubik-edge-01` on 2026-07-25:

- `telemetry-collector.service` is the original base unit.
- `telemetry-collector.service.d/override.conf` is the active drop-in that resets `ExecStart` and
  selects the modular collector.
- `personal-edge-lab-api.service` is the separate authenticated API/dashboard unit. It intentionally
  mirrors the known RUBIK identity, paths, restart policy, and hardening without depending on the
  collector service.
- `personal-edge-lab-alert-evaluator.service` is a hardened one-shot process that reads the stored
  telemetry and collector status, then persists deterministic alert transitions. It has no network
  access.
- `personal-edge-lab-alert-evaluator.timer` invokes that evaluator every 30 seconds, starting 30
  seconds after boot. Its interval must match `ALERT_EVALUATION_INTERVAL_SECONDS`.
- `personal-edge-lab-telegram-bot.service` runs the owner-only Casadaqui AC control conversation.
  It uses Telegram long polling, reads its mode-`0600` token file, and composes the same audited
  command use case as the dashboard without depending on the API or collector.

Stage 3 keeps Uvicorn on loopback. `deploy/nginx/personal-edge-lab.conf` terminates local TLS for
`https://rubik-edge-01.local/`, redirects HTTP, rejects unknown hosts, and prevents LAN access to
loopback liveness. Avahi publishes the existing host name.

Together they preserve the discovered user, group, working directory, environment file, network
ordering, hardening, and restart policy while changing only the executable module.

The effective configuration was verified after a full RUBIK reboot. To compare the deployed
configuration with this capture:

```bash
systemctl cat telemetry-collector.service
systemctl show telemetry-collector.service \
  -p User -p Group -p WorkingDirectory -p EnvironmentFiles -p ExecStart -p Restart -p RestartSec
systemctl cat personal-edge-lab-api.service
systemctl cat personal-edge-lab-alert-evaluator.service
systemctl cat personal-edge-lab-alert-evaluator.timer
systemctl list-timers personal-edge-lab-alert-evaluator.timer
systemctl cat personal-edge-lab-telegram-bot.service
```

See `docs/deployment.md` for backup, installation, verification, and rollback.
