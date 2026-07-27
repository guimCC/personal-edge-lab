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
| 0A. Deployment housekeeping | Done | Live configuration captured and reboot accepted |
| 1. Read-only local API | Done | Stored telemetry and audit data available on the trusted LAN |
| 2. Dashboard and service health | Done | Phone-first telemetry and operational health on RUBIK |
| 3. Authenticated dashboard AC control | Done | HTTPS owner access and intentional AC control accepted on RUBIK |
| 4. Stale telemetry and availability alerts | Done | Durable failure and recovery incidents accepted on RUBIK |
| 4.5. Platform consolidation | Implemented | Backend boundaries and automated quality gates ready for RUBIK acceptance |
| 4.6. Modular lab console | Done | Extensible frontend shell with Climate as its first module |
| 5A. Casadaqui operations | Done | Modular owner-only status and deliberate AC control |
| 5B. Proactive Telegram alerts | Implemented | Durable failure/recovery delivery with owner pause policy |
| 6A. Local-AI email triage | Next | Read-only, evaluated categorization before mailbox actions |

`Planned` does not mean committed scope. Before each stage starts, its open decisions are resolved
and its acceptance criteria become the implementation checklist.

## Stage 4.5 — Platform consolidation

**Status:** Implemented locally as `0.5.1`; pending the normal RUBIK deployment acceptance.

This maintenance release prepares multiple delivery adapters without adding a new runtime service:

- platform health and cool-only remote command policy are reusable application capabilities;
- AC use cases have an explicit `ac_control` module instead of a generic `home` namespace;
- alert evaluation and alert reading use separate ports, adapters, and services;
- SQLite repositories share foreign-key, timeout, and row settings;
- command audit timestamps are supplied by the application clock;
- FastAPI routes and schemas are separated by feature;
- active incidents cannot be displaced by recovered-history limits;
- environment parsing and process logging use small shared policies;
- CI, Pyright, coverage reporting, Ruff, ShellCheck, wheel inspection, and architecture guards form
  the automated quality gate;
- the 365-day telemetry-retention decision is recorded in `docs/data-retention.md`; deletion remains
  disabled until the bounded maintenance capability is implemented and accepted.

The frontend component refactor is deliberately outside this consolidation stage.

## Stage 4.6 — Modular lab console

**Status:** Done as `0.6.0`; accepted on RUBIK on 2026-07-26.

The dashboard is now the first workspace of Personal Edge Lab rather than a climate-specific
product shell:

- a neutral lab shell owns RUBIK identity, navigation, session actions, and global status;
- Climate is the first feature module and currently receives the primary workspace;
- current temperature and intentional AC control share the main operational surface;
- temperature history is the principal supporting view;
- command audit is presented as compact cross-lab activity, never as physical state;
- system health and recovered incident history stay collapsed while healthy;
- active and suspect incidents remain immediately visible above the current module;
- API contracts, authentication, climate, activity, operations, shared formatting, tests, and
  styles have explicit frontend boundaries;
- a development-only preview supplies representative data without entering the production build;
- phone and desktop behavior retain the existing accessibility and safety contracts.

Future modules can join the shell without changing Climate internals or turning the root component
back into a dashboard monolith.

RUBIK acceptance covered the authenticated desktop and phone layouts, control workflow, chart,
activity, operational disclosure, local HTTPS, and light/dark behavior.

## Stage 0 — Modular foundation

**Status:** Done

The two existing vertical slices were moved into `personal_edge_lab`:

- continuous telemetry collection;
- on-demand AC `set`, `off`, and `history`;
- pure domain models and application ports;
- reusable telemetry, AC-control, and platform-status use cases;
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

### Deployment acceptance

Stage 0A was completed on 2026-07-25:

- the real base unit and active override were captured under `deploy/systemd`;
- the service remained enabled and started automatically after a full RUBIK reboot;
- the process used `personal_edge_lab.apps.telemetry_collector`;
- readings `21579` through `21584` were stored successfully at approximately 15-second intervals;
- the installed application commit was `744dc795982b827392da7e217c126dd93e47a2ec`;
- migration `001_initial` was present, applied at `2026-07-25T14:39:01.556849+00:00`.

## Stage 1 — Read-only local API

**Status:** Done

**Goal:** expose useful platform data over HTTP from the RUBIK without adding a new physical-control
surface.

This is different from the existing ESP32 API. The ESP32 exposes hardware contracts to the RUBIK.
The local platform API will expose validated platform data to browsers and future integrations.

### Initial HTTP surface

Implemented endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | API, database, collector freshness, and platform version |
| `GET /api/v1/telemetry/latest` | Latest reading for a device |
| `GET /api/v1/telemetry/history` | Bounded recent readings for charts or inspection |
| `GET /api/v1/ac/history` | Bounded recent AC command audit entries |

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

### Decisions

- Use FastAPI, Pydantic, and one Uvicorn worker.
- Bind to `0.0.0.0:8000` on the trusted LAN.
- Use recent bounded lists: telemetry 1–1000 and AC history 1–100.
- Derive freshness from the latest stored reading; more than 45 seconds is stale.
- Return HTTP 200 with `degraded` for stale or absent telemetry and 503 only for SQLite failure.
- Expose `/docs` and `/openapi.json` on the trusted LAN.

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

**Status:** Done

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

### Recorded decisions

- React/TypeScript is compiled with Vite on RUBIK and packaged into the Python wheel.
- FastAPI serves the dashboard assets; no Node process runs in production.
- Nginx exposes the app at `http://rubik-edge-01.local/`, published through Avahi.
- The chart uses server-side 1-hour, 6-hour, and 24-hour aggregation.
- Collector heartbeat and attempt outcomes distinguish collector state from ESP32 reachability.

### Acceptance criteria

- A user can tell within seconds whether the displayed temperature is fresh.
- Empty history, stale data, API errors, and ESP32 downtime have explicit states.
- The chart uses bounded API queries and remains responsive on the RUBIK.
- No control endpoint or misleading AC “current state” is presented.
- Mobile and desktop layouts receive visual verification.
- Dashboard deployment and rollback are documented.

## Stage 3 — Authenticated AC controls in the dashboard

**Status:** Done

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

### Recorded decisions

- One `owner` identity with an Argon2id password hash and revocable SQLite sessions.
- Seven-day absolute and 24-hour idle session expiry; raw cookie tokens are never stored.
- Exact-origin, Fetch Metadata, JSON, and session-bound CSRF validation for writes.
- Nginx terminates HTTPS using a private workstation CA trusted explicitly on owner devices.
- Browser controls authorize cool mode only; the local CLI retains all existing modes.
- Idempotency, a rolling six-per-minute limit, and a leased per-device lock prevent duplicates.
- Production docs are disabled and all platform reads require authentication.

### Preserved command semantics

- The API accepts only complete valid states.
- The `ac_control` module remains the single reusable command orchestration path.
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

### Recorded RUBIK acceptance

Stage 3 was accepted on 2026-07-25 as release `0.4.0`:

- the private CA was trusted on the owner computer and iPhone, and both loaded
  `https://rubik-edge-01.local` without bypassing certificate validation;
- HTTP redirected to HTTPS, production docs were unavailable, protected reads required a valid
  session, and `/health/live` remained loopback-only;
- authentication and controls were enabled in separate guarded steps, with the command route
  unavailable before the control feature flag was enabled;
- the computer and iPhone each completed operator-confirmed Set State and Power Off actions; the
  resulting dashboard audit rows were attributed to `owner` and recorded `confirmed_success`;
- deployment probes created no command audit rows and did not contact the ESP32;
- after a full RUBIK reboot, collector, API, Nginx, and Avahi were enabled and active with no
  service errors;
- SQLite passed its integrity check, migrations `001` through `003` remained applied, server-side
  sessions survived the reboot, and telemetry resumed at approximately 15-second cadence;
- the local AC history CLI retained its output and showed the latest dashboard command without
  changing command behavior.

## Stage 4 — Stale telemetry and ESP32 availability alerts

**Status:** Done

**Goal:** notify the operator about sustained problems without producing repetitive noise.

The implementation proposal is maintained in
[the Stage 4 alerting plan](stage-4-alerting-plan.md).

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

### Recorded implementation decisions

- A hardened one-shot app is invoked by a 30-second systemd timer and never contacts the network.
- Telemetry becomes suspect above 45 seconds and alerting after sustained 180-second staleness.
- ESP32 availability becomes alerting only after at least four consecutive failures sustained for
  45 seconds while the collector heartbeat remains current.
- SQLite owns evaluator runtime, current state, incident deduplication, and transition history.
- Recovery requires evidence newer than the active incident and remains highlighted for five
  minutes.
- `/health` and a protected bounded `/api/v1/alerts` query expose evaluator and incident state.
- Initial delivery is structured transition logging plus the authenticated dashboard. External
  delivery, acknowledgement, reminders, and quiet hours remain Stage 5 concerns.

### Acceptance criteria

- Short ESP32 interruptions do not create noisy alerts.
- A sustained failure creates one actionable alert.
- Repeated evaluations do not resend the same alert indefinitely.
- Recovery creates one clear recovery event.
- Alert evaluation survives process restarts without losing essential state.
- Tests use controlled time and do not wait in real time.
- Telemetry collection continues independently if alert delivery fails.

### Local implementation verification

- Migration `004_operational_alerts` is additive and rollback-compatible with `0.4.0`.
- Deterministic tests cover threshold boundaries, deduplication, recovery, evaluator staleness,
  filtering, concurrency, and authenticated HTTP contracts.
- The React dashboard distinguishes clear, suspect, active, recovered, and retained-data states.

### Recorded RUBIK acceptance

Stage 4 was accepted on 2026-07-26 as release `0.5.0`:

- the hardened one-shot evaluator completed successfully and its 30-second systemd timer remained
  enabled and active independently from the collector and API;
- the normal dashboard state reported no active operational incidents;
- stopping only the collector produced stopped/unknown operational health, progressed stored
  telemetry through suspect to one active stale-telemetry incident, and created one recovery after
  the collector resumed and stored a genuinely newer reading;
- disconnecting only the ESP32 while leaving the collector running progressed repeated collection
  failures through suspect to one active edge-unavailable incident, then created one recovery
  after the ESP32 reconnected and the next collection succeeded;
- recovery history remained visible without being presented as current failure state;
- after a full RUBIK reboot, collector, API, Nginx, Avahi, and the evaluator timer were enabled and
  active, the evaluator result was successful, the authenticated dashboard loaded, and the owner
  session remained valid;
- SQLite passed its integrity check and telemetry returned to its approximately 15-second cadence.

## Stage 5 — External interfaces and automation

These are separate later slices, not one large project.

### 5A. Telegram

**Status:** AC control and status accepted on RUBIK; modular owner-interface refactor prepared as
`0.7.2`.

The initial Telegram slice deliberately focuses on AC control because the dashboard already owns
monitoring. In `0.7.2`, Casadaqui becomes an independent modular owner interface with:

- one immutable numeric owner user ID and private-chat-only authorization;
- a central `OwnerBot` router and explicit capability registry;
- a general `/start` and `/help` menu for Status and Air conditioning;
- `/ac` for a stateless Cool-mode temperature panel with fan and vane submenus;
- `/off` as a shortcut to a Power Off review;
- `/status` for the shared read-only API/collector/ESP32/telemetry/alerts snapshot;
- a direct **Enviar ajuste** action from the normalized panel and a separate Power Off confirmation;
- durable `telegram_bot` audit attribution and a stable `telegram:<user_id>` actor;
- the existing rate limit, device lease, cool-only policy, exactly-one ESP32 attempt, and
  idempotent result replay;
- explicit unknown-outcome language and no automatic physical retries;
- a token-safe local administration CLI and a mode-`0600` token file;
- an independently restartable, hardened systemd service.

New callbacks are namespaced by `home`, `status`, or `ac`; `0.7.2` also accepts the prior callback
forms so messages opened before deployment remain usable. Future capabilities are registered
explicitly and invoke their own use cases rather than inheriting AC command policy.

Detailed monitoring/history queries, notification acknowledgement, groups, multiple Telegram
users, webhooks, and remote dashboard exposure remain later slices. See
[the Stage 5A implementation and acceptance plan](stage-5a-telegram-ac-plan.md).

### 5B. Proactive Telegram alerts

**Status:** Implemented as `0.8.1`; pending guarded RUBIK acceptance. `0.8.1` treats Telegram's
idempotent “message not modified” and expired-callback responses as successful no-ops so one stale
callback cannot block later owner commands.

Confirmed `alerting` and `recovered` transitions create an outbound Telegram delivery atomically
with the transition. The existing Casadaqui service drains the SQLite outbox; the evaluator keeps
its no-network hardening. Delivery uses leases, bounded backoff, Telegram `Retry-After`, a 24-hour
maximum age, and sanitized runtime status.

The owner can use `/notifications` to pause operational alerts for one hour, eight hours, until
08:00 the following day, or indefinitely. Pausing suppresses pending and future alerts without
stopping evaluation and without replaying old messages on resume. Rapid repeated transitions are
coalesced into a delayed instability message.

See [the Stage 5B implementation and acceptance plan](stage-5b-telegram-alerts-plan.md).

### 5C. Automation rules

Begin with one concrete rule and a dry-run/audit mode. Automation must account for the lack of
physical AC state feedback and must never interpret `timeout_unknown` as confirmed failure or
success. Add scheduling, cooldowns, conflict handling, and a kill switch before unattended control.

### 5D. Speech

Speech is another interface to existing use cases, not a new control implementation. Commands that
change physical state require spoken-back normalization and confirmation.

## Stage 6 — Local AI

### 6A. Read-only email triage

Start with a bounded mailbox batch and fixed, owner-defined categories. A local model may recommend
classification only: it cannot send, delete, archive, label, or otherwise mutate email. Validate
structured output, measure it against a small manually labelled set, and benchmark actual RUBIK
latency/memory before choosing a model. Email credentials and retrieval stay outside the model.

This work receives its own persistent task lifecycle; the notification outbox is not reused as a
generic AI queue. Casadaqui may later start a triage task and present its result through a separate
capability. See [the Stage 6A implementation roadmap](stage-6a-local-ai-email-triage-plan.md).

Work Package 0 was accepted on RUBIK on 2026-07-26. The UNO Q inference contract is frozen,
authenticated, restricted to RUBIK at the network layer, stable across service and full-node
restarts, and explicitly limited to Qwen3 1.7B with one parallel request.

Work Package 1 was accepted on RUBIK as release `0.9.0` on 2026-07-26. The packaged diagnostic CLI
proves public health and feature-gated authenticated completion with one bounded request, sanitized
failures, no content logging, and no email, prompt, persistence, retry, scheduler, or dashboard
scope.

Work Package 2 is implemented locally as release `0.10.0`; RUBIK acceptance is pending. It
separates liveness from readiness, adds bounded one-slot process-local coordination, preserves one
HTTP attempt, and finalizes logical identity plus queue/provider timing evidence.

Work Packages 3 and 5 are combined in release `0.11.0` as an observable synthetic email-triage
foundation. The first AI feature module resolves a production-labelled Langfuse prompt with a
packaged fallback, requests strict `label` and `reason` JSON through the existing queued model,
and emits one isolated root-plus-generation trace. This release does not connect Gmail or claim
classification quality. WP4 remains deferred; WP6 may add read-only Gmail retrieval, but real
Gmail-to-model execution remains blocked on privacy and minimum-quality decisions.

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
**Status:** Done

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

- No RUBIK-hosted API or browser interface exists.

**Next**

- Resolve Stage 1 API decisions and freeze its first read-only HTTP contract.

### 2026-07-25 — Reboot acceptance completed

**Stage:** 0A
**Status:** Done

**Delivered**

- Captured the real `telemetry-collector.service` and active `override.conf`.
- Preserved all operational settings and changed only the effective `ExecStart`.

**Decisions**

- Keep the original base unit and version the modular entrypoint as a systemd drop-in.
- Treat the live base unit and override together as the deployable configuration.

**Verification**

- `telemetry-collector.service` was enabled and active after a full RUBIK reboot.
- The service started at `2026-07-25 16:52:29 CEST` using the modular entrypoint.
- Readings `21579` through `21584` were stored without errors at the expected cadence.
- Deployed commit `744dc795982b827392da7e217c126dd93e47a2ec` was recorded.
- SQLite migration `001_initial` was confirmed.

**Known limitations**

- The deployment uses fixed `/home/ubuntu/personal-edge-lab` paths and is specific to the current
  RUBIK host.

**Next**

- Begin Stage 1 by deciding API exposure, framework, port, health semantics, and bounded query
  contracts.

### 2026-07-25 — Read-only API implemented

**Stage:** 1
**Status:** Implemented locally; RUBIK acceptance pending

**Delivered**

- Added reusable telemetry and AC audit query use cases.
- Added versioned read-only HTTP endpoints, health semantics, OpenAPI, and interactive docs.
- Added a separate `personal-edge-lab-api.service` with no dependency on the collector.
- Published the API contract and controlled rollout/rollback procedure.

**Decisions**

- Trust the home LAN for Stage 1 and expose port 8000 without authentication or CORS.
- Keep the API read-only and independent from ESP32 connectivity.
- Use one SQLite connection per request and one Uvicorn worker.
- Defer pagination, time ranges, dashboard UI, alerts, TLS, and control routes.

**Verification**

- Unit, integration, HTTP contract, architecture, configuration, and real-process tests pass in
  development.
- Mutating HTTP methods cannot create AC audit records or reach command use cases.
- Existing collector and AC CLI behaviors remain covered by the full regression suite.

**Known limitations**

- The API has not yet completed service, trusted-LAN, concurrent-load, ESP32-offline, and reboot
  acceptance on the RUBIK.
- The API must not be forwarded to the public internet.

**Next**

- Deploy Stage 1 to the RUBIK using `docs/deployment.md` and record the acceptance evidence before
  marking the stage done.

### 2026-07-25 — Dashboard and operational health accepted on RUBIK

**Stage:** 2
**Status:** Done

**Delivered**

- Deployed the React temperature dashboard and expanded operational-health API as version `0.3.0`.
- Added collector heartbeat, last-attempt outcome, ESP32 reachability, and bounded temperature
  series.
- Served the packaged dashboard through FastAPI, loopback Uvicorn, Nginx, and the
  `rubik-edge-01.local` Avahi name.
- Added a repeatable RUBIK deployment script for subsequent releases.

**Decisions**

- Keep Node.js as a build-time tool; no Node process runs in production.
- Keep the dashboard read-only and preserve AC command history as audit data, not current AC state.
- Keep API, collector, Nginx, and Avahi as independently managed services.
- Require authenticated, HTTPS-protected command handling before adding dashboard controls.

**Verification**

- The frontend was compiled on RUBIK and packaged inside the `0.3.0` wheel.
- Migration `002_collector_runtime_status` was applied without replacing existing telemetry or
  audit data.
- Collector runtime status and telemetry collection were confirmed after the collector restart.
- The dashboard and API documentation were reachable through `rubik-edge-01.local`.
- The local regression suite has 161 passing tests; Ruff lint and formatting checks pass.

**Known limitations**

- The LAN interface remains HTTP and intentionally read-only.
- There is no authentication, browser AC control, alert delivery, TLS, or public-internet exposure.
- The deployment script must be committed and deployed to RUBIK before it becomes the standard
  release path.

**Next**

- Define the Stage 3 LAN threat model, HTTPS approach, authentication/session design, CSRF
  protection, rate limiting, and command idempotency contract before adding a write route.

### 2026-07-25 — Authenticated AC control accepted on RUBIK

**Stage:** 3
**Status:** Done

**Delivered**

- Added the owner Argon2id credential CLI, opaque SQLite sessions, durable concurrent login
  throttling, exact expiry behavior, CSRF/origin validation, and session revocation.
- Added cool-only Set State and separate Power Off through the existing one-attempt command use
  case, with audit attribution, idempotent replay, rolling rate limits, and leased device locks.
- Added the authenticated dashboard login, cache clearing, normalized review dialog, explicit
  confirmation, distinct outcomes, and safe same-key result checks after a lost response.
- Added local-CA provisioning, HTTPS Nginx, hardened API systemd settings, guarded deployment,
  rollback documentation, and additive migration `003_authenticated_control`.

**Verification**

- 184 Python unit, integration, contract, architecture, CLI, collector, and real-process tests pass.
- Frontend lint, TypeScript checks, six component tests, production build, and four phone/desktop
  Playwright checks pass.
- The `0.4.0` wheel contains the authentication app/module and hashed dashboard assets.
- Concurrent reservation and throttle tests prove one command winner and durable lockout state.
- The guarded disabled → HTTPS → authentication → controls rollout completed on RUBIK.
- The owner computer and iPhone trusted the private CA and successfully used the authenticated
  dashboard.
- Operator-confirmed Set State and Power Off actions from both clients were attributed to `owner`,
  audited once per accepted action, and returned `confirmed_success`.
- Unauthenticated command probes returned `401`, disabled-route probes returned `404`, and neither
  kind created audit records.
- After reboot, all four services were enabled and active, SQLite returned `ok`, migrations
  `001`–`003` remained applied, telemetry resumed at approximately 15-second cadence, and the AC
  history CLI remained compatible.

**Known limitations**

- Access remains owner-only and LAN-only; each owner device must explicitly trust the private CA.
- The platform still has no independent physical AC-state feedback.
- Remote access, MFA, multiple identities, alerts, Telegram, and automation remain deferred.

**Next**

- Implement Stage 4 durable alert evaluation and dashboard-visible incident/recovery history
  without adding an external notification channel yet.

### 2026-07-26 — UNO Q inference contract accepted

**Stage:** 6A Work Package 0
**Status:** Done

**Delivered**

- Captured the real UNO Q service, llama.cpp revision, production model, API-key placement,
  restart policy, user lingering, network bind, and resource baseline.
- Installed the private key copy on RUBIK and made one inference slot explicit.
- Added a persistent legacy-iptables service restricting TCP 8080 to RUBIK at `192.168.1.81`.
- Removed the unused 4B benchmark model after explicit owner approval.
- Fixed source-distribution selection so the ignored generated dashboard is present when the
  isolated wheel-from-source build runs.

**Decisions**

- Use `http://unoq-ai-01.local:8080` as the canonical URL because RUBIK resolved it reliably before
  and after reboot.
- Use Qwen3 1.7B Q4_K_M with context 1024, four threads, and one parallel slot.
- Keep unauthenticated health minimal; require the private bearer key for generation.

**Verification**

- RUBIK received health `200`, unauthenticated completion `401`, and authenticated completion
  `200`; a non-RUBIK LAN source timed out while SSH remained available.
- The inference and firewall services remained enabled and active after a full UNO Q reboot.
- The production process used no swap during the recorded idle and bounded-request checks.
- The final local gate passed 265 tests, Ruff lint/format, Pyright with the CI interpreter,
  isolated source/wheel builds, wheel inspection, shell syntax checks, and Git diff checks.

**Known limitations**

- A bounded exact-text diagnostic produced a valid provider response but did not follow its output
  instruction. Prompt quality remains deferred to the versioned prompt and evaluation packages.

**Next**

- Implement the Work Package 1 packaged `ai_cli` connectivity slice on RUBIK.

### 2026-07-26 — RUBIK-to-UNO-Q connectivity accepted

**Stage:** 6A Work Package 1
**Status:** Done

**Delivered**

- Released the packaged `personal_edge_lab.apps.ai_cli` health and completion diagnostics as
  `0.9.0`.
- Added pure inference types, the narrow language-model port, a one-attempt llama.cpp adapter,
  sanitized error categories, bounded configuration, and strict mode-`0600` key validation.
- Extended the guarded deployment to validate and privately back up the inference key when enabled.
- Kept prompts, email, persistence, retries, schedulers, services, migrations, and dashboard changes
  out of the slice.

**Verification**

- Local and RUBIK gates each passed 341 tests plus frontend lint, 10 tests, production build, Ruff,
  Pyright, ShellCheck, isolated packaging, and wheel inspection.
- The opt-in live test and packaged health/completion commands succeeded on RUBIK.
- Disabled completion exited `2`, a temporary wrong key returned sanitized `authentication` with
  exit `5`, and an unavailable local origin returned `connection` with exit `3`.
- The API reported `0.9.0`; existing platform services, SQLite integrity, the UNO Q service, and the
  WP0 firewall remained healthy. A non-RUBIK source remained blocked.

**Known limitations**

- The valid diagnostic completion had empty visible message content; instruction quality is not a
  WP1 gate and remains deferred to prompt/evaluation work.
- Completion remains one synchronous attempt with no concurrency guard or retry.

**Next**

- Define WP2 concurrency, readiness, retry-policy, and operational evidence boundaries before
  implementation.

### 2026-07-26 — Provider operational contract implemented locally

**Stage:** 6A Work Package 2
**Status:** Implemented locally; RUBIK acceptance pending

**Delivered**

- Finalized validated logical identity and queue/provider timing on completion results.
- Added a one-permit process-local limiter with bounded waiting and a sanitized local-capacity
  failure that performs no provider call.
- Split public process liveness (`health`) from loaded-model readiness (`ready`).
- Added explicit one-slot and queue-timeout configuration and retained one HTTP attempt with no
  automatic retry.
- Prepared package, API, frontend, and wheel metadata for release `0.10.0`.

**Verification**

- The full local Python suite passed 370 tests with one opt-in live test skipped.
- Threaded concurrency tests prove bounded waiting, one active delegate, zero provider calls after
  queue expiry, and permit release across failure paths.
- Ruff, formatting, Pyright, ShellCheck, Git diff checks, frontend lint, 10 frontend tests, and the
  production frontend build passed.
- Isolated source/wheel builds and inspection passed for `0.10.0`.

**Known limitations**

- The limiter is process-local; server-side `--parallel 1` remains the cross-process boundary.
- Queue and HTTP transport are separate timeout budgets.
- RUBIK live commands and platform service verification remain pending.

**Next**

- Commit and push locally, then pull and deploy through the documented RUBIK workflow and record
  acceptance before WP3.

### 2026-07-27 — Observable synthetic email triage implemented locally

**Stage:** 6A combined Work Packages 3 and 5
**Status:** Implemented locally; RUBIK and Langfuse acceptance pending

**Delivered**

- Added the first AI feature module with bounded email input, a closed provisional label taxonomy,
  strict label/reason decoding, and versioned evidence.
- Added provider-neutral JSON-schema output and disabled reasoning to the existing queued llama.cpp
  path.
- Added a production-labelled Langfuse prompt with a permanent packaged fallback and explicit,
  idempotent publication.
- Added one deterministic synthetic trace with one root span and one child generation. Trace and
  prompt failures cannot invalidate inference.
- Prepared package, API, frontend, wheel, configuration, deployment, rollback, and handoff material
  for release `0.11.0`.

**Verification**

- The full local Python suite passed 441 tests with one opt-in UNO Q live test skipped.
- Ruff lint/format, Pyright, ShellCheck, frontend lint, 10 frontend tests, and the production build
  passed.
- Isolated source/wheel builds, expanded wheel inspection, exact dependency metadata, and clean
  acceptance-wheel installation passed.

**Known limitations**

- No live Langfuse prompt or trace is claimed until Cloud credentials are installed and the
  resulting trace is fetched and audited.
- The slice uses synthetic data only. Gmail, persistence, scheduling, mailbox actions, and
  classification-quality claims remain absent.
- WP2 acceptance remains pending because no rerun or recorded RUBIK evidence was added to the
  repository.

**Next**

- Commit and push `0.11.0`, then perform the documented owner-controlled RUBIK and Langfuse
  acceptance. Keep WP4 quality work deferred and revisit privacy before any real Gmail-to-model
  execution.
