# Personal Edge Lab API v1

Production origin:

```text
https://rubik-edge-01.local
```

The API is LAN-only, has no CORS policy, and requires the owner session for all platform data and
control endpoints. All timestamps are RFC 3339 UTC. Invalid request shapes and query parameters
return HTTP 422. SQLite failures return a sanitized HTTP 503.

## Authentication

`GET /api/v1/auth/session` is public and reports `authenticated`, feature flags, and—only for a
valid session—the actor, CSRF token, idle expiry, and absolute expiry. Invalid or expired cookies
are cleared.

`POST /api/v1/auth/login` accepts only `{"password":"..."}`. Bad credentials return the same
generic HTTP 401. Five failures in 15 minutes block login for 15 minutes; HTTP 429 includes
`Retry-After`. Success creates a server-side session and sets:

```text
__Host-pel_session; Secure; HttpOnly; SameSite=Strict; Path=/
```

`POST /api/v1/auth/logout` revokes the session, clears the cookie, and returns HTTP 204. It requires
the same CSRF/origin protections as a command.

Every authenticated state-changing request requires exact
`Origin: https://rubik-edge-01.local`, non-cross-site Fetch Metadata,
`Content-Type: application/json`, and `X-CSRF-Token` equal to the session token. CSRF values are
never placed in URLs or logs.

## Protected reads

These routes return HTTP 401 without a valid owner session:

| Route | Contract |
| --- | --- |
| `GET /health` | API/database, telemetry freshness, collector and ESP32 health |
| `GET /api/v1/alerts` | Current alert states and bounded incident history |
| `GET /api/v1/telemetry/latest` | Latest complete device reading; optional `device_id`; 404 if empty |
| `GET /api/v1/telemetry/history` | Newest-first readings; `limit` 1–1000, default 100 |
| `GET /api/v1/telemetry/series` | `1h`, `6h`, or `24h` aggregated buckets including explicit gaps |
| `GET /api/v1/ac/history` | Newest-first command audit; `limit` 1–100, default 20 |

Operational degradation still returns HTTP 200 from `/health`; only SQLite failure returns 503.
Audit items include nullable `actor_id`, `idempotency_key`, and `request_source` (`dashboard` or
`local_cli`). Audit history is never evidence of the AC's physical current state.

`/health` includes an `alerts` summary with status `healthy`, `suspect`, `alerting`, `recovered`,
or `unknown`, plus active/suspect counts and evaluator timing. The response is degraded while an
alert is suspect or active, or when the evaluator has never run or is older than 90 seconds.

`GET /api/v1/alerts` accepts:

- optional nonblank `device_id`, defaulting to the configured device;
- `status=active|recovered|all`, default `all`;
- `limit` from 1 to 100, default 20.

It returns current state for both alert types and newest-first incident history. With `status=all`,
all active incidents are always returned plus at most `limit` recovered incidents; `limit` can
therefore be exceeded only by the small, bounded set of active alert types. This prevents a
long-running active incident from being hidden by newer recovery history. Active incident duration
is measured through the API check time; recovered duration ends at recovery. Evidence contains only
stable categories and sanitized operator-facing text. The evaluator creates alert state from stored
telemetry and collector status; this read route never contacts the ESP32 or systemd.

## Authenticated AC command

```http
POST /api/v1/ac/commands
Idempotency-Key: 16-to-64 URL-safe characters
Content-Type: application/json
X-CSRF-Token: session-bound-value
```

Set State is deliberately cool-only:

```json
{
  "command_type": "set_state",
  "state": {
    "power": true,
    "temperature_c": 24,
    "mode": "cool",
    "fan": "auto",
    "vertical_vane": "middle"
  }
}
```

Power Off is separate:

```json
{"command_type":"power_off"}
```

A new well-formed attempt returns HTTP 201 with `{"audit":{...},"replayed":false}` regardless of
the physical result. A completed duplicate with the same owner, key, and normalized payload
returns the original result as HTTP 200 with `replayed:true`. Reusing a key for another payload,
duplicating an in-progress request, or colliding with the per-device command lease returns HTTP
409 and sends no ESP32 request. Six new attempts per rolling minute are allowed; HTTP 429 includes
`Retry-After`.

Well-formed domain-invalid requests are audited as `rejected_locally` without contacting the
ESP32. Malformed JSON, missing authentication/CSRF/idempotency, and schema failures are not command
attempts and do not create audit rows.

Outcomes retain their uncertainty:

- `confirmed_success`: ESP32 accepted and transmitted; physical AC state is not proven.
- `rejected_locally`: no ESP32 request.
- `node_unreachable` or `node_reported_failure`: no confirmation.
- `timeout_unknown` or `response_unknown`: transmission may have occurred; never retry
  automatically.

## Public operational surface

`GET /` and hashed assets are public so the login shell can load. `GET /health/live` is available
only from loopback for service supervision and is denied by Nginx. Production `/docs` and
`/openapi.json` are disabled. No other mutating route exists.
