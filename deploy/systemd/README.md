# Captured systemd unit

Before device deployment, place the exact output-derived unit from
`systemctl cat telemetry-collector.service` in this directory. Preserve all discovered operational
settings and change only `ExecStart` to:

```text
/real/path/to/.venv/bin/python -m personal_edge_lab.apps.telemetry_collector
```

No service file is committed yet because the real Raspberry unit, user, paths, environment, and
restart policy are not available in this development workspace. See `docs/deployment.md`.
