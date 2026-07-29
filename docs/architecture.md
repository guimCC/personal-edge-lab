# Platform architecture

## Dependency direction

The package is organized around inward-pointing dependencies:

```text
apps -> application/ports <- infrastructure
                |
             modules -> domain
```

- `domain` contains `TemperatureReading`, `AcState`, command results, audit entries, pure local-AI
  request/results, validation, and other pure rules. It uses only the standard library and does not
  know HTTP, SQLite, apps, or modules.
- `application/ports` contains the narrow protocols required by use cases: a temperature source,
  telemetry repository, AC controller, command-audit repository, distinct alert evaluation and
  alert query repositories, plus the narrow `LanguageModel.complete` contract.
- `modules/telemetry` collects one reading and provides bounded telemetry queries, aggregation,
  freshness, and collector/edge-node health evaluation.
- `modules/ac_control` validates channel policy, sends, and audits one AC command and provides
  audit-history queries.
- `modules/platform_status` combines telemetry, collector, ESP32, and durable-alert evidence for
  every delivery adapter without depending on FastAPI.
- `modules/authentication` owns owner login throttling, opaque sessions, expiry, and credential
  rotation semantics without importing FastAPI or SQLite.
- `modules/alerting` evaluates stored operational evidence into durable alert transitions and
  exposes bounded alert queries without importing FastAPI, systemd, or SQLite.
- `modules/notifications` owns durable delivery, retry, expiry, and owner pause semantics without
  importing Telegram or SQLite.
- `modules/email_triage` is the first AI feature module. It renders bounded email as canonical JSON,
  resolves a versioned prompt through a narrow port, invokes `LanguageModel`, strictly decodes
  `label` and `reason`, and returns versioned evidence. Its durable batch use case coordinates
  `EmailSource`, prepared prompt identity, transactional evaluation reservation, sequential
  inference, partial failures, reuse, and interruption without knowing Gmail, SQLite, llama.cpp,
  Pydantic, Langfuse, or OpenTelemetry. Its owner-feedback use case records append-only annotations
  through ports and treats external publication as best-effort.
- `infrastructure/esp32` implements the HTTP contracts. AC always uses a single attempt.
- `infrastructure/telegram` implements the narrow Bot API transport and never exposes the bot
  token through its public errors.
- `infrastructure/ai` implements concrete llama.cpp liveness/readiness and completion HTTP
  contracts. A standard-library decorator queues callers behind one process-local permit. The
  adapter translates failures into sanitized categories, performs one attempt, maps the
  provider-neutral structured-output contract to llama.cpp JSON schema, and does not expose the
  server's GGUF path as model identity. Pydantic is confined to the strict triage parsing boundary.
- `infrastructure/observability` implements Langfuse managed-prompt and trace ports. Langfuse and
  OpenTelemetry imports are confined there; a prompt outage selects the packaged fallback and a
  trace outage cannot invalidate inference. Synthetic traces carry authorized fixture content;
  Gmail traces accept a separate redacted payload containing only hashes, lengths, cleanup,
  label, version, usage, and timing evidence. The feedback publisher upserts similarly redacted
  dataset items and categorical trace scores without receiving private content.
- `infrastructure/gmail` implements the bounded `EmailSource` port. It owns Google OAuth refresh,
  Gmail IDs and pagination, GET-only wire structures, nested MIME decoding, and conservative
  HTML/text normalization. Raw Gmail payloads and OAuth objects never cross that boundary.
- `infrastructure/persistence/sqlite` owns migrations, applies one shared connection policy
  (`foreign_keys`, busy timeout, row mapping), and maps SQLite rows to domain objects.
- `apps/telemetry_collector` owns configuration, composition, signals, polling interval, and the
  consecutive-failure counter.
- `apps/ac_cli` owns parsing, output, configuration, composition, and exit codes.
- `apps/email_triage_cli` owns explicit personal-Gmail authorization, metadata-only retrieval,
  durable dry-run composition, signal handling, and evidence presentation. Live triage may print
  sender, subject, label, and reason on the trusted terminal; normalized bodies never appear and
  durable history remains content-free.
- `apps/api` has feature routers for authentication, operations, telemetry, AC, and the packaged
  dashboard. It protects typed HTTP queries, enforces origin/CSRF controls, and composes the
  existing command use case for authenticated writes.
- `apps/auth_cli` manages the owner Argon2id hash and session revocation locally.
- `apps/alert_evaluator` is the one-shot composition root scheduled by systemd every 30 seconds.
  It has no network adapter and records evaluator health independently from the collector and API.
- `apps/telegram_bot` is an independent long-polling owner interface. `OwnerBot` centralizes
  authorization and routes to explicitly registered status, AC, notification-policy, and manual
  email-feedback capabilities. The same process drains proactive deliveries and pending redacted
  feedback publication before each long poll.
- `apps/telegram_cli` validates and stores the bot token and discovers the numeric owner identity
  without placing either operation in the dashboard.
- `apps/ai_cli` is a packaged RUBIK diagnostic composition root. Public `health` proves process
  liveness, public `ready` proves the model is loaded, and authenticated, feature-gated `complete`
  proves bounded inference connectivity. `triage --fixture synthetic-invoice` composes the first
  feature use case, while `prompt-publish` is the only prompt-writing path.

Architecture tests parse imports to keep domain isolated, application ports inward-facing,
feature modules independent from adapters, and infrastructure independent from apps and feature
modules.

The local-AI path now has one observable feature slice:

```text
synthetic fixture -> email_triage -> prompt source -> packaged fallback
                                  \-> one-slot LanguageModel -> llama.cpp
                                  \-> strict decoder
                                  \-> trace sink -> classify-email
                                                  \-> generate-triage-decision
```

The generic language-model port deliberately has no liveness or readiness method. Those states are
provider deployment evidence, while completion is the reusable capability contract. The limiter
is process-local; UNO Q's `--parallel 1` remains the final cross-process limit. Queue waiting and
the HTTP request use separate timeout budgets, and each completion still performs one HTTP attempt.
The trace is deliberately one root span plus one child generation, has no user or session identity,
and captures content only for checked-in synthetic fixtures.

## Runtime behavior

Telemetry is a continuous app invoking a one-reading use case:

```text
polling loop -> CollectTemperature -> TemperatureSource
                                  -> TelemetryRepository
             -> CollectorStatusMonitor -> CollectorStatusRepository
```

The ESP32 response is cached sensor state; fetching it does not trigger sampling. The platform
stores both receipt time and `estimated_sample_at = received_at - age_ms`. Network, DNS, timeout,
HTTP, malformed JSON, and invalid contract responses are categorized source failures. They never
create synthetic rows. A status heartbeat records process liveness, the latest attempt, the last
success/failure, and graceful shutdown without pretending that a stored reading proves the ESP32
is currently reachable.

AC is an on-demand app:

```text
operator -> validate complete state -> begin audit -> one HTTP request -> complete audit
                     |
                     +-> local rejection -> begin and complete audit, no HTTP request
```

Timeouts and malformed HTTP 200 responses remain unknown outcomes because IR transmission may
have happened. Even a confirmed response is not physical-state confirmation.

Dashboard commands reserve their audit and device lease atomically before transmission:

```text
session + CSRF + origin + idempotency key
                  |
                  v
SQLite reservation -> local policy -> exactly one ESP32 request -> audit completion
        |                  |
        |                  +-> rejected_locally, no ESP32 request
        +-> replay / conflict / rate limit / device busy
```

Only SHA-256 hashes of random session cookies are stored. A session owns a separate browser CSRF
token, seven-day absolute expiry, and 24-hour idle expiry. Password verification uses an Argon2id
hash stored outside SQLite. Expired device leases are recovered as an unknown physical outcome and
are never resent automatically.

Casadaqui separates channel authorization and navigation from capability behavior:

```text
private owner -> OwnerBot -> home/status capability -> GetPlatformHealth
                          \-> AC capability -> CommandService -> SQLite -> one ESP32 request
                          \-> notification policy -> SQLite
```

The capability registry is explicit in the composition root. It generates the native command
list and home menu, validates unique commands and callback namespaces, and does not dynamically
discover plugins. Telegram controls use the same reservation path without pretending that browser
cookies apply to another channel:

```text
private Telegram user -> normalized inline panel -> Enviar ajuste
                                      |                    |
                              fan/vane submenus             v
owner user ID -> stable panel key ----------------> CommandService
                                                      |
                                        SQLite reservation -> one ESP32 request
```

The panel itself is the normalized Cool request, so Set State does not add a redundant review
screen. Power Off retains a separate confirmation. Each callback carries a bounded request and an
opaque stable panel key, not a credential. Re-delivery or a double tap reuses that key and therefore
retrieves the stored result instead of transmitting again. The bot token remains in a mode-`0600`
file and HTTP client request logging is disabled in the bot process because Telegram places the
token in its API URL.

The read-only `/status` command composes the same framework-independent `GetPlatformHealth` use
case as the dashboard. It reads persisted heartbeats, telemetry, and alert-evaluator state through
fresh SQLite connections, and checks the API through its loopback-only liveness endpoint. It does
not inspect systemd or contact the ESP32 directly.

Operational alert transitions and outbound delivery use a transactional outbox:

```text
alert evaluator transaction -> transition + notification_outbox row
                                                |
Casadaqui delivery tick -> lease -> Telegram -> delivered / retry / expired
```

The evaluator retains no network access. Casadaqui retries informational delivery with bounded
backoff and honors Telegram rate limits, but never reuses that behavior for physical commands.
Owner pause policy suppresses pending and future operational notifications while evaluation and
incident history continue. Suppressed rows are not revived later.

The local API is a separate process:

```text
owner browser -> Nginx TLS -> FastAPI + React assets -> use cases -> SQLite repositories
```

The React frontend follows the same capability-first shape:

```text
App session gate -> lab shell -> feature workspaces
                              -> Climate
                              -> Activity
                              -> Operations

feature UI -> typed API client -> validated Zod contracts
```

`App` owns authentication loss and session cleanup. The lab shell owns identity, navigation, and
global workspace actions without containing device logic. Feature directories own their
interactions and presentation; shared formatting and status semantics remain independent of React.
Climate is the first module, not the product identity, so later energy, automation, integration, or
local-AI workspaces can join without expanding one root component. Styles are split into tokens,
base behavior, shell, feature surfaces, and responsive policy rather than one global stylesheet.

Read routes never contact the ESP32. The single authenticated command route composes the same AC
command service as the CLI and performs one adapter call only after its audit reservation is
durable. Migrations run before the API accepts requests. Each synchronous request owns its SQLite
connection, so web worker threads never share a connection. Nginx redirects HTTP to HTTPS and
Uvicorn remains loopback-only. Vite is build-time only and no Node process serves production
traffic.

Operational alert evaluation is a separate scheduled process:

```text
systemd timer -> alert evaluator -> telemetry + collector status in SQLite
                                -> alert state + incidents + transitions in SQLite

owner browser -> Nginx TLS -> protected alert query -> SQLite
```

The state machine is `healthy -> suspect -> alerting -> recovered -> healthy`. A database
transaction serializes evaluation, and a partial unique index permits only one active incident per
device and alert type. Evaluator failure cannot stop telemetry collection, and stale evaluator
runtime is visible as unknown alert health.

WP6 adds an independent operator-only retrieval path:

```text
explicit Gmail query -> read-only Gmail adapter -> bounded EmailDocument batch
                                                -> metadata-only CLI
```

The adapter requests only `gmail.readonly` and exposes no mutation operation. Bodies are normalized
in memory for a later approved consumer, but WP6 does not import the language-model, Langfuse,
email-triage feature, or persistence paths. A batch may contain valid documents plus explicit
per-message normalization failures; transport and authorization failures remain operation-level.

WP7 composes the accepted boundaries without weakening them:

```text
explicit Gmail query -> EmailSource -> TriageMailboxBatch -> prepared prompt identity
                                                        -> SQLite reservation
                                                        -> one-slot LanguageModel
                                                        -> strict decision
                                                        -> evidence-only SQLite
                                                        -> redacted Langfuse trace
```

Migration `006_email_triage_runs` separates runs, run items, unique evaluation identities, and
actual inference attempts. `BEGIN IMMEDIATE` serializes identity reservation; one partial unique
index prevents concurrent active attempts for the same identity. Reused successful attempts do not
contact UNO Q or create a trace. SQLite stores IDs, hashes, lengths, versions, label and operational
evidence. That evidence-only constraint was the accepted WP7 baseline.

WP8 adds a protected read-only presentation path without changing that durable boundary:

```text
authenticated dashboard -> bounded run/detail query -> migration 006 evidence
explicit item action     -> exact Gmail GET -> repeat normalization/input cap
                                           -> verify stored hashes
                                           -> transient text-only response
```

The review use case depends on a bounded evidence repository and an exact-message source port.
Only Gmail infrastructure sees the internal message ID. Public run/detail schemas expose
fingerprints, label, decision hash, reason length, versions, usage, timing, trace availability, and
failure evidence. The exact-content endpoint returns private content only after identity
verification, adds no-store headers, and makes one Gmail call. It cannot list mail, invoke the
model, contact Langfuse or Telegram, persist content, or mutate Gmail.

WP8.1 replaces the transient presentation boundary with a durable product projection:

```text
decoded Gmail document -> immutable content snapshot -> evaluation/attempt history
                                              \-----> one current message projection
authenticated dashboard -> bounded message query -> stored text-only detail
```

Migration `007_email_triage_messages` stores one internal message per Gmail message ID plus
immutable normalized-content snapshots. Each new evaluation links to the exact snapshot it used.
The current projection points to the latest processing outcome and separately to the latest
successful attempt, so a later failure never destroys a prior recommendation. Runs and attempts
remain the execution ledger under Diagnostics.

The protected message API exposes only an opaque local record ID. It reads SQLite and has no Gmail,
model, Langfuse, Telegram, or Gmail-write dependency. Sender, subject, bounded normalized content,
exact model input, query text, label, and reason are authorized local data; raw MIME, attachments,
credentials, provider bodies, and GGUF paths remain excluded. Real-Gmail Langfuse traces remain
redacted even though owner-only SQLite and backups retain product content.

WP8.2 adds a pure deterministic routing layer before prompt resolution:

```text
normalized TriageEmail
        |
        +-- private exact sender/domain rule -> durable rule decision (no reason)
        |                                   -> no prompt, UNO Q, or Langfuse
        |
        +-- no rule -> prompt/taxonomy v2 -> queued model -> English reason
```

Private JSON parsing and file-permission validation remain in composition code. Rule parsing and
matching use only standard-library/domain types under `modules/email_triage`; SQLite stores only the
stable rule ID/version and never the private address/domain matcher. Migration
`008_email_triage_taxonomy_v2` expands label persistence and adds explicit `model`/`rule` source
evidence. Legacy taxonomy-v1 labels remain readable but are excluded from all new schemas.

WP8.3 adds one shared feedback use case above the message projection:

```text
dashboard or private Telegram
          -> confirm / correct / dismiss
          -> append-only SQLite feedback (authoritative, private)
          -> best-effort redacted Langfuse dataset item + trace scores
```

Migration `009_email_triage_feedback` versions feedback per message and ties every annotation to
the exact successful attempt being reviewed. `BEGIN IMMEDIATE` rejects stale dashboard or Telegram
views. The stable Langfuse dataset item is upserted per message: confirm/correct is active with an
expected label, while dismiss archives it. Langfuse receives hashes, lengths, normalization
evidence, labels, and source metadata only. Publication failure leaves local feedback intact and
retriable. Neither surface modifies Gmail or automatically changes prompts.

## Adding capability

### Add a domain model

Place pure data and rules under `personal_edge_lab.domain`. Keep I/O, environment access,
frameworks, SQLite, and HTTP out. Import concrete domain modules explicitly rather than growing a
package-level reexport surface, and add unit boundary tests.

### Add or extend a port

Define the smallest protocol under `application/ports` in domain terms. Repository methods return
domain objects, never `sqlite3.Row`. Avoid adding a generic device abstraction until multiple
concrete use cases prove the common behavior.

### Add a use case

Put the orchestration in an existing real module under `modules`. Depend on ports and domain types
through constructor injection. One execution should represent one business operation; recurring
scheduling and presentation belong to an app.

### Add a module

Create a new directory under `modules` only for a concrete capability with working use cases.
Add tests that show its domain language and verify that it does not import infrastructure or apps.

### Add an adapter

Implement an existing port under `infrastructure`, translate external errors and representations
at that boundary, and write contract or integration tests. SQLite schema changes are appended as
ordered migrations; never edit an already deployed migration.

### Add an app

Create a package under `apps` with `__main__.py`. It is the composition root: load and validate
configuration, apply migrations, instantiate adapters and repositories, build use cases, and own
process lifecycle or presentation. Business rules should remain reusable outside that app.

## Future architecture, not current packages

Future slices may introduce a persistent local-AI task worker, a broader operator review surface,
speech, multiple identities and permissions, and worker registration. Classification quality,
feedback retention, and any automated mailbox action remain separate explicit decisions.
Casadaqui is the first external operations adapter: it exposes concise status, AC control,
notification policy, and operational alert delivery, but deliberately does not expose detailed
histories.
No empty placeholder packages exist for these ideas. A package is added only with its first
end-to-end behavior and tests.

Firmware, MQTT, PostgreSQL, an ORM, queues, Redis, containers, and a generic plugin framework
remain out of scope until a concrete slice requires them.
