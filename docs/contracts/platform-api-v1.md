# Personal Edge Lab read-only API v1

The RUBIK API exposes stored platform data to trusted-LAN clients. It never calls the ESP32 and
contains no endpoint that can change physical state.

Default RUBIK address:

```text
http://rubik-edge-01.local
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
  "version": "0.3.0",
  "checked_at_utc": "2026-07-25T14:00:00Z",
  "database": {"status": "healthy"},
  "telemetry": {
    "status": "fresh",
    "device_id": "ac-controller-01",
    "last_received_at_utc": "2026-07-25T13:59:45Z",
    "age_seconds": 15.0,
    "stale_after_seconds": 45.0
  },
  "collector": {
    "status": "running",
    "device_id": "ac-controller-01",
    "process_started_at_utc": "2026-07-25T13:00:00Z",
    "heartbeat_at_utc": "2026-07-25T13:59:58Z",
    "heartbeat_age_seconds": 2.0,
    "stale_after_seconds": 45.0,
    "stopped_at_utc": null,
    "last_attempt_at_utc": "2026-07-25T13:59:58Z",
    "last_success_at_utc": "2026-07-25T13:59:58Z",
    "consecutive_failures": 0
  },
  "edge_node": {
    "status": "reachable",
    "device_id": "ac-controller-01",
    "last_attempt_at_utc": "2026-07-25T13:59:58Z",
    "last_success_at_utc": "2026-07-25T13:59:58Z",
    "last_failure_at_utc": null,
    "last_failure_category": null,
    "last_failure_message": null
  }
}
```

`fresh` includes readings exactly 45 seconds old. A greater age is `stale`. Missing readings are
`no_data`. Collector heartbeat is likewise valid through 45 seconds. Collector status is
`running`, `stopped`, `stale`, or `no_data`; edge-node status is `reachable`, `unreachable`, or
`unknown`. Overall health is healthy only when telemetry is fresh, the collector is running, and
the latest collection attempt reached the ESP32. Operational degradation returns HTTP 200. Only a
database failure produces HTTP 503.

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

Each item has the same schema as the latest reading. This endpoint has no cursor or time-range
query.

## Temperature series

```http
GET /api/v1/telemetry/series
GET /api/v1/telemetry/series?device_id=ac-controller-01&window=24h
```

`window` is `1h`, `6h` (default), or `24h`. Results are chronological and contain 60-, 300-, or
900-second buckets respectively. Each bucket reports sample count and nullable minimum, average,
and maximum temperatures. Missing intervals are explicit zero-sample buckets with null
measurements, so chart clients do not join unrelated samples across an outage.

```json
{
  "device_id": "ac-controller-01",
  "window": "1h",
  "start_at_utc": "2026-07-25T13:00:00Z",
  "end_at_utc": "2026-07-25T14:00:00Z",
  "bucket_seconds": 60,
  "sample_count": 3,
  "items": [
    {
      "bucket_start_at_utc": "2026-07-25T13:00:00Z",
      "bucket_end_at_utc": "2026-07-25T13:01:00Z",
      "sample_count": 3,
      "temperature_minimum_c": 25.7,
      "temperature_average_c": 25.9,
      "temperature_maximum_c": 26.1
    }
  ]
}
```

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

There are no POST, PUT, PATCH, or DELETE operations. The dashboard at `/` uses the same origin and
does not add CORS. There is no authentication, TLS, alerting, or internet exposure. The API must
remain limited to the trusted home network.
