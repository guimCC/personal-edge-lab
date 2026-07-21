# Platform architecture

## Direction

The RUBIK Pi 3 is the local control and data plane between independently operating edge nodes and future higher-level services.

```text
sensors and actuators
        |
ESP32 and other edge nodes (hardware logic and cached samples)
        |
explicit HTTP contracts; MQTT only when justified
        |
RUBIK Pi platform (ingestion, history, coordination)
        |
future APIs, automation, dashboards, observability, management, AI agents
```

Firmware lives outside this repository. An edge node owns sampling schedules, raw hardware interaction, derived hardware values, connectivity, and actuator behavior. The platform owns contract consumption, validation, receipt timestamps, durable history, and eventually cross-device coordination.

## Current vertical slice

The telemetry collector polls one configurable HTTP endpoint and accepts the current temperature contract. Its layers are intentionally concrete:

- `config`: validated environment settings;
- `client`: HTTP behavior and transport-error normalization;
- `models`: contract validation and timestamp derivation;
- `storage`: SQLite schema and parameterized queries;
- `collector`: polling, failure reporting, and shutdown orchestration.

SQLite is appropriate for a single-host initial service and requires no separate operator-managed process. UTC ISO-8601 values preserve portability and sort correctly. The node-reported age is retained, while `estimated_sample_at_utc = received_at_utc - age_ms` makes the uncertainty explicit.

The service does not introduce a generic device framework. The base URL, device ID, and temperature path are configuration inputs, and the HTTP/domain boundary is narrow enough to add a new capability beside this one without coupling it to all firmware endpoints.

