# Platform architecture

## Dependency direction

The package is organized around inward-pointing dependencies:

```text
apps -> application/ports <- infrastructure
                |
             modules -> domain
```

- `domain` contains `TemperatureReading`, `AcState`, command results, audit entries, validation,
  and other pure rules. It uses only the standard library and does not know HTTP, SQLite, apps, or
  modules.
- `application/ports` contains the narrow protocols required by use cases: a temperature source,
  telemetry repository, AC controller, and command-audit repository.
- `modules/telemetry` collects one reading and provides bounded telemetry queries, aggregation,
  freshness, and collector/edge-node health evaluation.
- `modules/home` rejects, sends, and audits one AC command and provides audit-history queries.
- `infrastructure/esp32` implements the HTTP contracts. AC always uses a single attempt.
- `infrastructure/persistence/sqlite` owns migrations and maps SQLite rows to domain objects.
- `apps/telemetry_collector` owns configuration, composition, signals, polling interval, and the
  consecutive-failure counter.
- `apps/ac_cli` owns parsing, output, configuration, composition, and exit codes.
- `apps/api` exposes typed, read-only HTTP queries, serves the compiled React dashboard, and opens
  fresh SQLite repositories per request.

Architecture tests parse imports to keep domain isolated and prevent modules from importing HTTP
or SQLite implementations.

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

The local API is a separate process:

```text
trusted-LAN browser -> Nginx -> FastAPI + React assets -> query use cases -> SQLite repositories
```

It performs no ESP32 requests and has no physical-control route. Migrations run before the API
accepts requests. Each synchronous request owns its SQLite connection, so web worker threads never
share a connection. Telemetry freshness comes from stored readings; collector and ESP32 health
come from the collector status row. Vite is build-time only and no Node process serves production
traffic.

## Adding capability

### Add a domain model

Place pure data and rules under `personal_edge_lab.domain`. Keep I/O, environment access,
frameworks, SQLite, and HTTP out. Export the type from `domain/__init__.py` only when a convenient
public import is useful, and add unit boundary tests.

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

Future slices may introduce dashboard controls, Telegram, speech, email, a task worker, identity
and permissions, and worker registration. They should reuse domain models and use cases through
ports.
No empty placeholder packages exist for these ideas. A package is added only with its first
end-to-end behavior and tests.

Firmware, MQTT, PostgreSQL, an ORM, queues, Redis, containers, and a generic plugin framework
remain out of scope until a concrete slice requires them.
