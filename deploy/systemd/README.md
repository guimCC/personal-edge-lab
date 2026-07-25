# Captured systemd configuration

This directory records the configuration captured from `rubik-edge-01` on 2026-07-25:

- `telemetry-collector.service` is the original base unit.
- `telemetry-collector.service.d/override.conf` is the active drop-in that resets `ExecStart` and
  selects the modular collector.

Together they preserve the discovered user, group, working directory, environment file, network
ordering, hardening, and restart policy while changing only the executable module.

The effective configuration was verified after a full RUBIK reboot. To compare the deployed
configuration with this capture:

```bash
systemctl cat telemetry-collector.service
systemctl show telemetry-collector.service \
  -p User -p Group -p WorkingDirectory -p EnvironmentFiles -p ExecStart -p Restart -p RestartSec
```

See `docs/deployment.md` for backup, installation, verification, and rollback.
