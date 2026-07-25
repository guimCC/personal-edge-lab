# `ac-controller-01` HTTP contract

Default base URL: `http://ac-controller-01.local`

This document records the platform-facing firmware contract. The firmware is implemented and versioned separately.

## `GET /health`

Example response:

```json
{
  "status": "ok",
  "device": "ac-controller-01",
  "uptime_ms": 24187,
  "wifi_connected": true,
  "wifi_rssi_dbm": -25,
  "ip": "192.168.1.148"
}
```

The initial collector does not poll this endpoint.

## `GET /temperature`

Example successful response:

```json
{
  "sensor": "thermistor",
  "temperature_c": 24.31,
  "raw_adc": 1830,
  "age_ms": 420,
  "sample_interval_ms": 2000
}
```

Required fields and accepted values:

| Field | Type | Constraint |
| --- | --- | --- |
| `sensor` | string | non-empty |
| `temperature_c` | JSON number | finite, -100 through 200 °C |
| `raw_adc` | integer | non-negative |
| `age_ms` | integer | non-negative |
| `sample_interval_ms` | integer | greater than zero |

Extra fields are tolerated for forward compatibility. A request returns the node's cached sample; it does not trigger a measurement. The node currently samples independently every two seconds. HTTP non-success status, invalid JSON, or a payload violating this table is a failed collection and must not become a measurement.

## `GET /ac/state`

Returns the last state successfully transmitted by the ESP32:

```json
{
  "power": true,
  "mode": "cool",
  "temperature_c": 24,
  "fan": "auto",
  "vertical_vane": "middle",
  "state_source": "last_command"
}
```

Before the first successful command after boot, it returns HTTP 503:

```json
{"error": "ac_state_unavailable"}
```

The command CLI does not use this endpoint to infer or complete commands.

## `PUT /ac/state`

Content type: `application/json`. The request must contain a complete state:

```json
{
  "power": true,
  "mode": "cool",
  "temperature_c": 24,
  "fan": "auto",
  "vertical_vane": "middle"
}
```

Supported values:

| Field | Values |
| --- | --- |
| `power` | JSON boolean |
| `temperature_c` | integer from 16 through 31 |
| `mode` | `auto`, `cool`, `heat`, `dry`, `fan` |
| `fan` | `auto`, `low`, `medium`, `high`, `max` |
| `vertical_vane` | `auto`, `highest`, `high`, `middle`, `low`, `lowest`, `swing` |

After successful IR transmission, HTTP 200 returns the complete state with
`"state_source": "last_command"`. The response means IR was transmitted, not that the physical AC
received it or reached the requested state.

Defined failures are:

| Status | Error |
| --- | --- |
| 400 | `invalid_request_body` |
| 400 | `invalid_json` |
| 400 | `missing_or_invalid_fields` |
| 400 | `invalid_field_value` |
| 400 | `invalid_ac_state` |
| 415 | `content_type_must_be_application_json` |
| 503 | `ac_controller_could_not_apply_state` |

## `POST /ac/off`

This endpoint has no request body. It transmits the last successful complete state with power set
to false. Success is HTTP 200:

```json
{"status": "ok", "power": false}
```

If no complete state exists after ESP32 boot, or transmission fails, it returns:

```json
{"error": "ac_controller_could_not_power_off"}
```

with HTTP 503. The platform does not fall back to another command.

## Validation and uncertainty

The RUBIK Pi validates complete high-level intent before making a request. The ESP32 repeats
contract validation, applies protocol-specific limits, and owns all IR generation. Although the
firmware accepts every value listed above, physical validation is currently incomplete for modes
other than `cool` and for much of the temperature range.

The platform makes one HTTP attempt with retries disabled. A timeout is `timeout_unknown`: the
ESP32 may have transmitted IR before the response was lost. A connection or DNS failure is
`node_unreachable`; a non-200 response is `node_reported_failure`; an unexpected HTTP 200 body is
`response_unknown`. None of these outcomes is treated as physical AC state.
