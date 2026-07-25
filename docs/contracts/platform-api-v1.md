# Personal Edge Lab read-only API v1

The RUBIK API exposes stored platform data to trusted-LAN clients. It never calls the ESP32 and
contains no endpoint that can change physical state.

Default address:

```text
http://rubik-edge-01:8000
```

All timestamps are RFC 3339 UTC values. Invalid query parameters return HTTP 422. SQLite failures
return HTTP 503 with `{"detail":"database unavailable"}` and do not expose local exception text.

## Health

```http
GET /health
```

Example:

```json
{
  "status": "healthy",
  "version": "0.2.0",
  "checked_at_utc": "2026-07-25T14:00:00Z",
  "database": {"status": "healthy"},
  "telemetry": {
    "status": "fresh",
    "device_id": "ac-controller-01",
    "last_received_at_utc": "2026-07-25T13:59:45Z",
    "age_seconds": 15.0,
    "stale_after_seconds": 45.0
  }
}
```

`fresh` includes readings exactly 45 seconds old. A greater age is `stale`. Missing readings are
`no_data`. Both `stale` and `no_data` produce overall `degraded` with HTTP 200 because the API and
database are still available. Only a database failure produces HTTP 503.

## Latest telemetry

```http
GET /api/v1/telemetry/latest
GET /api/v1/telemetry/latest?device_id=ac-controller-01
```

Without `device_id`, the API uses `DEVICE_ID`. A device with no rows returns HTTP 404.

```json
{
  "device_id": "ac-controller-01",
  "sensor": "thermistor",
  "received_at_utc": "2026-07-25T13:59:45Z",
  "estimated_sample_at_utc": "2026-07-25T13:59:44.500000Z",
  "temperature_c": 25.9,
  "raw_adc": 1700,
  "age_ms": 500,
  "sample_interval_ms": 2000
}
```

## Telemetry history

```http
GET /api/v1/telemetry/history
GET /api/v1/telemetry/history?device_id=ac-controller-01&limit=100
```

`limit` defaults to 100 and must be from 1 through 1000. Items are newest first. An unknown device
returns an empty list.

```json
{"count": 0, "limit": 100, "items": []}
```

Each item has the same schema as the latest reading. Stage 1 has no cursor or time-range query.

## AC audit history

```http
GET /api/v1/ac/history
GET /api/v1/ac/history?limit=20
```

`limit` defaults to 20 and must be from 1 through 100. Entries are newest first. The command payload
is structured JSON; pending records retain null completion and result fields.

```json
{
  "count": 1,
  "limit": 20,
  "items": [
    {
      "id": 7,
      "device_id": "ac-controller-01",
      "command_type": "power_off",
      "command_payload": {"power": false},
      "requested_at_utc": "2026-07-25T14:00:00Z",
      "completed_at_utc": "2026-07-25T14:00:01Z",
      "outcome": "confirmed_success",
      "http_status": 200,
      "response_body": "{\"power\":false,\"status\":\"ok\"}",
      "error_category": null,
      "error_message": null
    }
  ]
}
```

## Discovery and non-goals

Interactive documentation is at `/docs` and the OpenAPI document at `/openapi.json` when
`API_DOCS_ENABLED=true`.

There are no POST, PUT, PATCH, or DELETE operations. Stage 1 has no authentication, CORS, TLS,
dashboard, alerts, or internet exposure. The API must remain limited to the trusted home network.
