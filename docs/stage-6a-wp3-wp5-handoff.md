# Stage 6A combined WP3/WP5 handoff

**Release:** `0.11.0`
**Status:** Accepted on RUBIK and Langfuse Cloud on 2026-07-27

## Delivered

- Added the first real AI feature module with bounded `TriageEmail`, a closed six-label taxonomy,
  strict `label`/`reason` decisions, and versioned profile, taxonomy, schema, prompt, provider, and
  timing evidence.
- Added provider-neutral JSON-schema output and disabled-reasoning contracts. The llama.cpp adapter
  maps them to `response_format` and `reasoning_effort="none"` while preserving temperature zero,
  seed zero, one queue permit, one HTTP attempt, and the existing diagnostic commands.
- Added a permanent packaged chat prompt. Email data is one canonical JSON prompt variable and is
  never interpolated into static instructions.
- Added Langfuse Cloud prompt resolution with a two-second bounded fetch, zero retries, 300-second
  SDK cache, compatibility validation, and local fallback.
- Added explicit idempotent `prompt-publish`; ordinary inference cannot create or promote prompts.
- Added one trace per synthetic triage item: root `classify-email`, child generation
  `generate-triage-decision`, deterministic trace ID, stable tags, exact remote prompt link, logical
  model, normalized usage, and queue/provider/total timing.
- Added `triage --fixture synthetic-invoice`. The fixture uses only `example.test` data. No Gmail,
  persistence, scheduler, service, migration, dashboard, retry, session, user identity, or mailbox
  action was added.

## Security and failure semantics

- Langfuse SDK and OpenTelemetry imports remain under infrastructure; feature and domain code use
  narrow ports.
- Langfuse uses two owner-only mode-`0600` key files. Configuration, logs, and exceptions never
  expose their contents.
- Prompt fetch failure selects the packaged prompt. Trace failure is reduced to
  `trace_unavailable` evidence and cannot replace or invalidate inference.
- Normal application logs contain operation and timing evidence only. Full email and generated
  content capture is authorized only for the checked-in synthetic fixture.
- Strict decoding rejects empty output, unknown labels, missing or extra fields, Markdown fences,
  prose, malformed JSON, blank reasons, and overlong reasons without repair.

## Local verification

- The full Python suite passed 441 tests with the one opt-in UNO Q live test skipped.
- Focused tests cover domain bounds, canonical prompt variables, Unicode and injection-shaped
  inputs, strict decoding, exact llama.cpp structured requests, managed-prompt fallback and
  idempotent publication, deterministic traces, exact two-observation shape, flush/shutdown, and
  trace-failure isolation.
- Ruff lint/format, Pyright with the Python 3.12 interpreter, ShellCheck, frontend lint, 10 frontend
  tests, and the production frontend build passed.
- Isolated source and `0.11.0` wheel builds passed. Wheel inspection confirmed the CLI, fixture,
  triage module, prompt manifest, strict decoder, observability adapter, exact
  `langfuse==4.14.1` dependency, and release metadata. A clean virtual environment installed and
  imported the acceptance wheel successfully.
- Live UNO Q and Langfuse acceptance was completed on RUBIK on 2026-07-27 as recorded below.

## RUBIK acceptance

The owner confirmed:

- deployment with the packaged fallback succeeded;
- Langfuse Cloud keys were installed through the private file configuration;
- `prompt-publish` succeeded and the production prompt resolved during synthetic triage;
- the fetched trace contained one `classify-email` root and one
  `generate-triage-decision` generation with the expected prompt link, logical model, usage/timing
  evidence, tags, and authorized synthetic input/output;
- the inspected trace contained no Langfuse key, UNO Q key/header, provider error body, or GGUF
  path;
- an unavailable HTTPS Langfuse origin selected `local_fallback`, reported trace unavailability,
  and did not invalidate successful inference;
- `health`, `ready`, `complete`, the opt-in UNO Q test, SQLite integrity, API `0.11.0`, existing
  platform behavior, UNO Q, and the WP0 firewall remained healthy.

No trace ID, token count, timing value, or raw service output is recorded because those exact values
were not supplied to the repository. WP2 is accepted from the same rerun confirmation.

## Rollback

Set `LANGFUSE_ENABLED=false`, reinstall `0.10.0`, and restart only existing processes that received
the package. The remote prompt may remain inert. There is no database or mailbox rollback.
