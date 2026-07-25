# Stage 4 — Durable telemetry and availability alerts

**Implementation status:** accepted on RUBIK as release `0.5.0` on 2026-07-26.

## Summary

Release `0.5.0` adds durable, low-noise alert evaluation for two operational conditions:

- stored telemetry has remained stale for a sustained period;
- the collector is running but repeated ESP32 collection attempts are failing.

Stage 4 will expose active and recently recovered incidents in the authenticated dashboard and
structured logs. It will not send Telegram, email, push, or SMS notifications. Establishing
trustworthy incident semantics before adding a delivery channel keeps later integrations small and
prevents noisy or duplicate messages.

The evaluator will be a framework-independent application use case invoked by a dedicated
systemd timer. It will read the existing telemetry and collector status, transition durable alert
state transactionally in SQLite, and never contact the ESP32 or interfere with collection.

Stage 4 explicitly excludes remote access, external notification delivery, acknowledgement
workflows, escalation policies, automatic remediation, AC commands, generic user-defined rules,
machine learning, and physical AC-state inference.

## Operator-visible behavior

### Alert types

`telemetry_stale`

- Signal: no reading for the configured device is fresh according to the existing 45-second health
  boundary.
- Suspect immediately when telemetry becomes stale.
- Alert only when the newest stored reading is more than 180 seconds old.
- Recover only after a new reading received after the incident began is fresh.

`edge_unavailable`

- Signal: the collector heartbeat is fresh and its latest collection attempt failed.
- Suspect on the first failed attempt.
- Alert after four consecutive failed attempts and at least 45 seconds since the first observed
  failure.
- Recover after a subsequent successful collection attempt.
- If the collector is stopped or stale, retain evidence but report the ESP32 condition as
  `unknown`; do not create or recover an ESP32 incident from missing collector evidence.

The initial thresholds are conservative defaults, configurable through validated environment
settings. They intentionally differ from the immediate health indicators: health describes the
current observation, while alerts describe sustained, actionable incidents.

### State machine

Each device and alert type owns one durable state:

```text
healthy -> suspect -> alerting -> recovered -> healthy
             |                         |
             +--------> healthy <------+
```

- A condition that clears while `suspect` returns to `healthy` without creating an incident.
- Entering `alerting` creates exactly one incident and one transition event.
- Repeated evaluations while the condition remains bad update observation metadata but create no
  duplicate incident or transition.
- Entering `recovered` completes the active incident and creates exactly one recovery event.
- `recovered` remains visible for five minutes, then returns to `healthy`.
- A new sustained failure during the recovery display period starts a new suspect cycle and, if it
  persists, a new incident.

All transitions use an injected UTC clock. Boundaries are exact and covered without real-time
sleeping in tests.

### Dashboard

Add an alert panel immediately below the platform health strip:

- prominent active-incident banner with alert type, device, start time, duration, and sanitized
  evidence;
- explicit `Suspect`, `Active`, and `Recovered` text labels in addition to color and icons;
- recent incident history, newest first, including recovery time and duration;
- empty state stating that no operational incidents have been recorded;
- retained last-good alert data plus a clear connection warning during API failures;
- local-time display with the browser timezone named, while API timestamps remain UTC.

The dashboard must distinguish current health from alert lifecycle. A stale health card can exist
briefly without an active alert, and a recovered incident can remain visible while current health
is healthy.

## Public API contract

All routes retain Stage 3 authentication, HTTPS, CSRF, origin, CORS, and documentation behavior.
No new write route is introduced.

### Expanded `GET /health`

Keep every existing field and add:

```json
{
  "alerts": {
    "status": "healthy",
    "active_count": 0,
    "suspect_count": 0,
    "latest_transition_at_utc": null,
    "evaluator_last_run_at_utc": "2026-07-25T21:00:00Z",
    "evaluator_age_seconds": 12.4
  }
}
```

`alerts.status` is `healthy`, `suspect`, `alerting`, `recovered`, or `unknown`. An overdue or
never-run evaluator produces `unknown` and degrades overall health but does not cause HTTP `503`.
SQLite unavailability remains the only health `503`.

### New `GET /api/v1/alerts`

Parameters:

- optional nonblank `device_id`, defaulting to configured `DEVICE_ID`;
- `status`: `active`, `recovered`, or `all`, default `all`;
- `limit`: default `20`, valid range `1..100`.

Response:

- current state for both alert types;
- bounded incident history, newest first;
- incident ID, device, type, status, suspect/alert/recovery UTC timestamps, duration, last observed
  time, and sanitized evidence;
- evaluator last-run time and age.

No raw exception, URL, response body, filesystem path, session value, or credential data may enter
the response.

## Domain and application design

Add a framework-independent alerting module containing:

- `AlertType`, `AlertLifecycleState`, and `AlertIncidentStatus` enums;
- immutable signal, state, incident, transition, and evaluation-result models;
- an `EvaluateOperationalAlerts` use case with injected UTC clock and policy;
- an `AlertRepository` port with transactional compare-and-transition behavior;
- read-only `GetOperationalAlerts` and health-summary use cases.

The evaluator consumes existing telemetry and collector-runtime repository ports. It does not call
FastAPI models, systemd, Nginx, React, or ESP32 adapters.

An evaluation transaction must:

1. load the current state for both alert types;
2. derive signals from one consistent SQLite snapshot;
3. apply deterministic state transitions;
4. insert or complete incidents and append transition events;
5. update evaluator heartbeat;
6. commit all changes atomically.

Concurrent invocations are serialized by SQLite transaction locking. A second invocation evaluates
the state committed by the first and cannot create a duplicate active incident.

## Persistence

Add additive migration `004_operational_alerts`:

- `alert_runtime_status`: singleton evaluator start/finish/result heartbeat;
- `alert_states`: one row per device and alert type with current lifecycle, suspect timestamp,
  recovery display deadline, latest observation, and active incident reference;
- `alert_incidents`: durable alert and recovery history;
- `alert_transition_events`: append-only state-transition evidence.

Required constraints and indexes:

- unique `(device_id, alert_type)` alert state;
- at most one active incident per `(device_id, alert_type)` using a partial unique index;
- foreign keys between state, incident, and transition rows;
- checks for valid enum values and chronological timestamps;
- indexes for active incidents and newest-first device history.

Migration `004` must be idempotent, preserve all existing telemetry/auth/audit data, and remain
ignorable by `0.4.0` during rollback. No existing table or column is removed or reinterpreted.

## Evaluator application and service

Add:

```bash
python -m personal_edge_lab.apps.alert_evaluator
```

The app performs one evaluation and exits:

- `0` after a committed evaluation, including normal suspect/alert/recovery transitions;
- nonzero for configuration, migration, or database failures;
- structured logs only on transitions plus one sanitized error on failure.

Run it through:

- `personal-edge-lab-alert-evaluator.service` as `Type=oneshot`;
- `personal-edge-lab-alert-evaluator.timer` with `OnBootSec=30s`,
  `OnUnitActiveSec=30s`, `AccuracySec=1s`, and `RandomizedDelaySec=0`;
- the same unprivileged RUBIK user, environment file, data-directory write allowance, restrictive
  umask, and systemd hardening as the API where applicable;
- no dependency on restarting the collector or API.

If one evaluation fails, systemd records the failure and the next timer activation tries again.
Alert evaluation or logging failure must never stop telemetry collection and must never create a
temperature reading or AC audit row.

The timer intentionally does not use `Persistent=true`: persistence applies to calendar timers,
whereas this monotonic timer should simply evaluate 30 seconds after each boot using the durable
SQLite state.

## Settings

Add validated defaults:

```dotenv
ALERT_EVALUATION_INTERVAL_SECONDS=30
ALERT_TELEMETRY_SUSPECT_AFTER_SECONDS=45
ALERT_TELEMETRY_ALERT_AFTER_SECONDS=180
ALERT_EDGE_MIN_CONSECUTIVE_FAILURES=4
ALERT_EDGE_ALERT_AFTER_SECONDS=45
ALERT_RECOVERY_DISPLAY_SECONDS=300
ALERT_EVALUATOR_STALE_AFTER_SECONDS=90
```

Validation must ensure:

- every duration and count is positive;
- telemetry alert threshold is not below its suspect threshold;
- evaluator stale threshold is greater than one evaluation interval;
- values are parsed once in the composition root and passed as typed policy.

The systemd timer remains the production scheduler. The interval setting is used for validation,
health expectations, tests, and deployment consistency; the deployment test must reject a mismatch
between the environment and timer configuration.

## Security and failure semantics

- Existing authentication protects all alert reads.
- Alert evaluation has no network client and no command capability.
- Dashboard alert content is rendered as text, never injected HTML.
- Evidence uses existing structured collector categories and sanitized messages only.
- Database failure prevents a transition rather than inventing state.
- Evaluator staleness is reported independently from the telemetry and collector it observes.
- No external delivery means there are no tokens, webhooks, or third-party credentials in Stage 4.

## Test plan

### Unit tests

- exact suspect, alert, recovery, and recovery-display boundaries;
- short telemetry gaps return to healthy without an incident;
- repeated bad evaluations create one incident and one alert transition;
- a fresh reading older than the active incident does not falsely recover it;
- ESP32 failure count and sustained-time conditions must both be satisfied;
- stopped/stale collector produces unknown ESP32 evidence without false transition;
- evaluator-stale health behavior;
- injected clocks and policies; no real sleeping.

### SQLite integration tests

- migration idempotency and preservation of migrations `001`–`003` data;
- state upserts, incident completion, transition ordering, and foreign-key constraints;
- partial unique index prevents two active incidents;
- two concurrent connections produce one winning transition;
- transaction rollback leaves no partial incident/event;
- newest-first device filtering and bounded history;
- rollback compatibility with `0.4.0`.

### HTTP contract tests

- exact expanded health and alerts response schemas;
- authentication required for alert data;
- healthy, suspect, alerting, recovered, unknown, and empty-history responses;
- device filtering and standard `422` invalid-query behavior;
- database `503` remains sanitized;
- production docs remain disabled and no mutating route is added.

### Frontend tests

- no-alert, suspect, active, recovered, evaluator-down, disconnected, and recovery states;
- current health and durable alert state are visibly distinct;
- retained data is labelled during transient API failure;
- timestamps use and name the browser timezone;
- keyboard and screen-reader semantics;
- phone and desktop Playwright layouts.

### Regression checks

- complete existing Python and frontend suites;
- Ruff lint/format, TypeScript, production build, wheel inspection, and Playwright;
- collector cadence, API/auth/session behavior, AC command safety, CLI output, and Stage 3 HTTPS;
- wheel contains the alert evaluator and updated dashboard assets.

## RUBIK rollout and acceptance

1. Record installed commit/wheel, service state, row counts, telemetry cadence, current health, and
   active sessions; back up `.env`, SQLite, systemd units/timers, Nginx, and the current wheel.
2. Install `0.5.0` with the alert timer disabled; apply migration `004` and verify Stage 3 remains
   unchanged.
3. Run one evaluator invocation manually against healthy stored data and inspect the transaction,
   structured log, and API response.
4. Install and enable the evaluator timer without restarting collector or API; confirm 30-second
   evaluator heartbeat and unchanged 15-second telemetry cadence.
5. Validate dashboard healthy/empty-history behavior from computer and iPhone.
6. Under operator control, stop the collector long enough to test telemetry suspect then alerting;
   confirm exactly one incident and no repeated transition.
7. Restart the collector and verify one recovery event, current health recovery, and resumed chart
   data without invented samples.
8. Under operator control, make the ESP32 unavailable while the collector remains running; verify
   suspect, one alert after the threshold, unknown behavior if the collector itself becomes stale,
   and one recovery after ESP32 collection succeeds.
9. Confirm alert evaluation failures do not stop the collector, API, dashboard, CLI, or AC command
   path.
10. Reboot RUBIK and verify collector, API, Nginx, Avahi, and the evaluator timer start
    independently; verify sessions, telemetry cadence, alert history, evaluator heartbeat, HTTPS,
    and CLI compatibility.

Stage 4 is complete only after the real sustained-failure and recovery exercises are accepted on
RUBIK. Tests may use controlled adapters, but the rollout must not send an AC command.

## Rollback

Disable the evaluator timer first, reinstall the retained `0.4.0` wheel, restore the previous
systemd/environment files, and restart only the API if its response code changed:

```bash
sudo systemctl disable --now personal-edge-lab-alert-evaluator.timer
```

Migration `004` remains because it is additive and `0.4.0` ignores its tables. Restore SQLite only
if integrity evidence shows actual corruption. Rolling back alerts must not restart the collector
or alter AC audit/session data.

## Locked assumptions

- Stage 4 remains owner-only, HTTPS, and trusted-LAN-only.
- Dashboard and structured logs are the only delivery surfaces.
- Telegram begins in Stage 5A after alert thresholds and deduplication are accepted.
- The evaluator reads SQLite only and never contacts systemd, the ESP32, or an external service.
- One-shot systemd timer execution is sufficient for the RUBIK workload.
- Existing 45-second health freshness remains unchanged; alerts intentionally require sustained
  evidence.
- There is no alert acknowledgement, manual resolution, or automatic remediation in this stage.
