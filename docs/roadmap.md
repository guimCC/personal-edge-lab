# Development roadmap and log

This is the living plan for growing `personal-edge-lab` one useful vertical slice at a time. It
records what exists, what comes next, the acceptance criteria for each stage, and the decisions
made while implementing it.

The roadmap is ordered, but it has no artificial dates. A stage starts only when the previous
stage is useful, tested, deployed, and understood on the real RUBIK Pi.

## Product direction

The platform sits between people or higher-level applications and independently operating edge
nodes:

```text
browser / integrations / operator
                 |
        RUBIK platform apps
                 |
      use cases and domain rules
           /             \
       SQLite         ESP32 HTTP API
```

The ESP32 continues to own hardware behavior, sampling, cached sensor values, and IR transmission.
The RUBIK owns validation, history, coordination, presentation, and eventually carefully bounded
automation.

## Working rules

- Deliver one end-to-end capability at a time; do not create empty packages for future ideas.
- Preserve existing environment variables, SQLite data, ESP32 contracts, and operational behavior
  unless a change is explicitly planned and migrated.
- Keep domain rules and use cases reusable by every app.
- Apps compose dependencies and own transport, presentation, configuration, and lifecycle.
- Infrastructure adapters own HTTP, SQLite, and other external-system details.
- AC commands always require a complete valid state, create an audit record, and make exactly one
  HTTP attempt. A timeout remains an unknown result and is never retried automatically.
- Start new control surfaces read-only. Add physical control only after authentication, safety,
  and audit behavior are explicit.
- Every deployed stage needs automated tests, a rollback path, and verification on the RUBIK.

## Status overview

| Stage | Status | Outcome |
| --- | --- | --- |
| 0. Modular foundation | Done | Telemetry and AC control share one modular package |
| 0A. Deployment housekeeping | Next | Capture the live unit and complete reboot acceptance |
| 1. Read-only local API | Planned | Safe programmatic access to platform data |
| 2. Dashboard and service health | Planned | Useful browser view of temperature and platform status |
| 3. Authenticated dashboard AC control | Planned | Safe physical control through the browser |
| 4. Stale telemetry and availability alerts | Planned | Actionable failure and recovery notifications |
| 5. External interfaces and automation | Later | Telegram, rules, speech, and local AI, in that order |

`Planned` does not mean committed scope. Before each stage starts, its open decisions are resolved
and its acceptance criteria become the implementation checklist.

## Stage 0 — Modular foundation

**Status:** Done

The two existing vertical slices were moved into `personal_edge_lab`:

- continuous telemetry collection;
- on-demand AC `set`, `off`, and `history`;
- pure domain models and application ports;
- reusable telemetry and home-control use cases;
- ESP32 HTTP and SQLite infrastructure adapters;
- transactional SQLite migrations;
- new application entrypoints;
- architecture, contract, unit, and integration tests.

Current entrypoints:

```bash
python -m personal_edge_lab.apps.telemetry_collector
python -m personal_edge_lab.apps.ac_cli
```

### Recorded verification

- 67 original behaviors were retained.
- The suite grew to 92 passing tests.
- The built wheel contains only `personal_edge_lab`.
- The old package entrypoints were removed.
- The new CLI and collector entrypoint were manually exercised on the RUBIK.

### Remaining deployment housekeeping

Before Stage 1, finish and record:

- capture the real base unit and active override under `deploy/systemd`;
- verify the service is enabled and starts automatically after a RUBIK reboot;
- verify several post-reboot readings approximately 15 seconds apart;
- record the installed commit and migration version;
- retain the pre-refactor unit backup until reboot acceptance passes.

## Stage 1 — Read-only local API

**Goal:** expose useful platform data over HTTP from the RUBIK without adding a new physical-control
surface.

This is different from the existing ESP32 API. The ESP32 exposes hardware contracts to the RUBIK.
The local platform API will expose validated platform data to browsers and future integrations.

### Initial HTTP surface

Candidate endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | API, database, collector freshness, and platform version |
| `GET /telemetry/latest` | Latest reading for a device |
| `GET /telemetry/history` | Bounded recent readings for charts or inspection |
| `GET /ac/history` | Bounded recent AC command audit entries |

The first version has no `POST`, `PUT`, `PATCH`, or `DELETE` routes.

### Implementation shape

- Add query use cases to the existing `telemetry` and `home` modules.
- Extend repository ports only with concrete query needs.
- Add a real API app as a new composition root.
- Reuse the existing SQLite repositories; do not let routes execute SQL directly.
- Define stable JSON response contracts, UTC timestamps, bounds, and error responses.
- Run migrations before opening repositories.
- Add a separate service only after its bind address, port, user, environment, restart policy, and
  network exposure are intentionally chosen.

### Open decisions

- API framework and dependency footprint.
- Bind only to localhost or expose it to the trusted LAN.
- Port and hostname.
- Maximum history window and whether cursor pagination is needed initially.
- How `/health` learns collector freshness without coupling to the collector process.
- Whether API documentation is available on the LAN or only locally.

### Acceptance criteria

- All endpoints are read-only and covered by contract tests.
- History limits are validated and cannot cause unbounded database reads.
- Repository results are domain objects, not SQLite rows.
- The API remains useful while the ESP32 is offline because stored history is local.
- `/health` distinguishes API health, database health, and stale telemetry.
- Existing telemetry and CLI tests remain green.
- The API starts and stops cleanly under `systemd`.
- A LAN client can query it only according to the chosen exposure policy.
- Reboot and rollback checks are documented and exercised.

## Stage 2 — Temperature dashboard and service-health view

**Goal:** make current conditions and platform health understandable from a browser.

### First useful screen

- latest temperature and reading age;
- clear fresh, stale, and unavailable states;
- recent temperature chart using the read-only API;
- ESP32/collector availability summary;
- last successful collection time;
- recent AC command history and unknown outcomes;
- platform/API version and health.

### Boundaries

- The dashboard calls the RUBIK API and never opens SQLite directly.
- The browser does not call the ESP32 directly.
- This stage remains read-only.
- The interface must work on a phone-sized screen on the local network.
- Charts must preserve UTC data and present time clearly in the viewer's local timezone.

### Open decisions

- Server-rendered HTML or a small client application.
- Chart library and asset strategy.
- Whether the dashboard is served by the API process or as a separate static app.
- Expected browsers and local-network naming.

### Acceptance criteria

- A user can tell within seconds whether the displayed temperature is fresh.
- Empty history, stale data, API errors, and ESP32 downtime have explicit states.
- The chart uses bounded API queries and remains responsive on the RUBIK.
- No control endpoint or misleading AC “current state” is presented.
- Mobile and desktop layouts receive visual verification.
- Dashboard deployment and rollback are documented.

## Stage 3 — Authenticated AC controls in the dashboard

**Goal:** allow intentional AC control from the dashboard without weakening existing safety
semantics.

### Scope

- sign in or provide a deliberately chosen local credential;
- display a complete AC state form;
- require explicit confirmation before sending;
- show normalized command payload before execution;
- submit exactly one command;
- display confirmed, rejected, unreachable, node-failed, and unknown outcomes distinctly;
- show the corresponding audit entry.

### Safety and security decisions required first

- LAN-only threat model and who is allowed to control the AC.
- Authentication mechanism and credential storage.
- Secure session handling and cross-site request forgery protection.
- Rate limits and accidental double-submission prevention.
- Whether TLS is terminated on the RUBIK or by another trusted local component.
- Audit data that can be shown to each user.

Authentication is not represented by hiding a button or relying only on an obscure URL.

### Preserved command semantics

- The API accepts only complete valid states.
- The home module remains the single reusable command orchestration path.
- Every attempt is audited before HTTP transmission.
- There is no automatic retry.
- A timeout or unexpected response stays visibly unknown.
- “Confirmed” means the ESP32 accepted and transmitted the command, not that the AC physically
  reached the requested state.

### Acceptance criteria

- Unauthenticated requests cannot read protected information or send commands.
- Invalid requests are audited as local rejections without contacting the ESP32.
- One user action produces at most one ESP32 request.
- Refresh, back navigation, and repeated form submission do not silently duplicate a command.
- All outcomes are visible and contract-tested.
- CLI behavior remains unchanged.
- Manual physical testing requires operator confirmation and is recorded separately.

## Stage 4 — Stale telemetry and ESP32 availability alerts

**Goal:** notify the operator about sustained problems without producing repetitive noise.

### Start with platform state, not a delivery channel

Model a small alert state machine:

```text
healthy -> suspect -> alerting -> recovered
```

Possible signals:

- no stored reading within a configured freshness threshold;
- repeated temperature-source failures;
- API can reach SQLite but telemetry is stale;
- recovery after an active alert.

The collector's in-memory failure counter is useful for logs but is not enough for a durable alert
system. Alert state and deduplication need explicit ownership.

### Initial delivery

Begin with structured logs and a visible dashboard alert. Add one external notification channel
only after thresholds and recovery behavior are trustworthy.

### Open decisions

- Freshness and sustained-failure thresholds.
- Whether alert evaluation belongs in the API, a timer-driven app, or a future worker.
- Durable alert state and acknowledgement needs.
- Quiet hours, reminder cadence, and recovery notification behavior.
- First external delivery channel.

### Acceptance criteria

- Short ESP32 interruptions do not create noisy alerts.
- A sustained failure creates one actionable alert.
- Repeated evaluations do not resend the same alert indefinitely.
- Recovery creates one clear recovery event.
- Alert evaluation survives process restarts without losing essential state.
- Tests use controlled time and do not wait in real time.
- Telemetry collection continues independently if alert delivery fails.

## Stage 5 — External interfaces and automation

These are separate later slices, not one large project.

### 5A. Telegram

Start with authenticated read-only queries and alerts. Add AC commands only after identity mapping,
authorization, explicit confirmation, and audit attribution are designed.

### 5B. Automation rules

Begin with one concrete rule and a dry-run/audit mode. Automation must account for the lack of
physical AC state feedback and must never interpret `timeout_unknown` as confirmed failure or
success. Add scheduling, cooldowns, conflict handling, and a kill switch before unattended control.

### 5C. Speech

Speech is another interface to existing use cases, not a new control implementation. Commands that
change physical state require spoken-back normalization and confirmation.

### 5D. Local AI

Use local AI first for explanations, summaries, anomaly exploration, or suggested actions. Keep
physical actions behind deterministic validation, authorization, confirmation, and audit. Model
output alone must not bypass a use case or directly call an ESP32 adapter.

## Definition of done for every stage

A stage is `Done` only when:

- scope and non-goals are written before implementation;
- domain and application boundaries remain clear;
- contracts and failure semantics are tested;
- migrations preserve existing data;
- `ruff` and the complete test suite pass;
- installation and operational commands are documented;
- deployment uses the actual RUBIK configuration, not invented service settings;
- health, logs, data integrity, restart, and reboot behavior are verified;
- rollback is possible and exercised proportionally to risk;
- the development log below records the outcome and remaining limitations.

## Development log

Add one entry after each meaningful implementation or deployment. Keep entries factual: what
changed, how it was verified, decisions made, and what remains.

### Entry template

```markdown
### YYYY-MM-DD — Short title

**Stage:** 1  
**Status:** Started | In progress | Blocked | Done

**Delivered**

- Concrete behavior added.

**Decisions**

- Decision and short reason.

**Verification**

- Automated tests and results.
- RUBIK/device checks and results.

**Known limitations**

- Explicitly deferred behavior or risk.

**Next**

- Smallest useful next implementation.
```

### 2026-07-25 — Modular foundation deployed

**Stage:** 0  
**Status:** Done; deployment housekeeping remains

**Delivered**

- Unified telemetry and AC control under `personal_edge_lab`.
- Added domain, ports, modules, ESP32 adapters, SQLite repositories, and migrations.
- Replaced the old collector and AC package entrypoints.
- Updated the RUBIK collector service to use the modular entrypoint.

**Decisions**

- Preserve one SQLite database and all existing tables and rows.
- Keep AC as an on-demand CLI.
- Keep exactly one HTTP attempt per AC command.
- Do not create placeholders for API, dashboard, messaging, automation, speech, or AI.

**Verification**

- 92 automated tests passed.
- `ruff` and packaging checks passed.
- AC CLI execution and continuous telemetry collection were confirmed on the RUBIK.

**Known limitations**

- Reboot acceptance and the checked-in capture of the live service configuration are not yet
  recorded.
- No RUBIK-hosted API or browser interface exists.

**Next**

- Complete deployment housekeeping, then resolve Stage 1 API decisions and freeze its first
  read-only HTTP contract.
