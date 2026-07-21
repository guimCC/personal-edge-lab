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

