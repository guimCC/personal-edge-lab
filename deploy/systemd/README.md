# Captured systemd configuration

This directory records the configuration captured from `rubik-edge-01` on 2026-07-25:

- `telemetry-collector.service` is the original base unit.
- `telemetry-collector.service.d/override.conf` is the active drop-in that resets `ExecStart` and
  selects the modular collector.
- `personal-edge-lab-api.service` is the separate read-only API/dashboard unit. It intentionally
  mirrors the known RUBIK identity, paths, restart policy, and hardening without depending on the
  collector service.

Stage 2 binds Uvicorn to loopback. `deploy/nginx/personal-edge-lab.conf` is the reviewed LAN proxy
configuration for `http://rubik-edge-01.local/`; Avahi publishes the existing host name.

Together they preserve the discovered user, group, working directory, environment file, network
ordering, hardening, and restart policy while changing only the executable module.

The effective configuration was verified after a full RUBIK reboot. To compare the deployed
configuration with this capture:

```bash
systemctl cat telemetry-collector.service
systemctl show telemetry-collector.service \
  -p User -p Group -p WorkingDirectory -p EnvironmentFiles -p ExecStart -p Restart -p RestartSec
systemctl cat personal-edge-lab-api.service
```

See `docs/deployment.md` for backup, installation, verification, and rollback.
