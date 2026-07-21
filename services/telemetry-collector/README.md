# Telemetry collector

The collector polls a cached temperature reading from an edge node, validates the HTTP/JSON contract, derives the approximate sensor sample time from the node-reported age, and appends successful readings to SQLite. It keeps running through node outages and shuts down on SIGINT or SIGTERM.

Configuration is supplied through environment variables. See the root [`.env.example`](../../.env.example) for all defaults. In particular, `EDGE_NODE_BASE_URL` and `TEMPERATURE_ENDPOINT` form the request URL, while `DEVICE_ID` identifies the reading independently of payload contents.

After installing the root project, run:

```bash
python -m telemetry_collector
```

Failures do not create rows. The first consecutive failure is logged at error level, periodic failures are summarized at warning level, and recovery is logged at info level.

