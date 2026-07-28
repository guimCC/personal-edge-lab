# Stage 6A — Local-AI email triage implementation roadmap

## Document status

**Stage:** 6A

**Status:** Planned

**Primary outcome:** RUBIK can retrieve a bounded set of Gmail messages, ask a local model on an
UNO Q to classify them, validate and persist the recommendations, and present an auditable dry-run
result without changing the mailbox.

This document is the implementation and handoff plan for Stage 6A. It expands the short Stage 6A
entry in [the main roadmap](roadmap.md) and follows the dependency rules in
[the platform architecture](architecture.md).

The plan is intentionally incremental. Every work package must leave a useful, tested capability
that can be exercised independently. Agents should not implement later packages merely to make an
earlier package appear complete.

## 1. Product intent

Email triage is the first concrete local-AI capability in Personal Edge Lab. It is a suitable first
case because:

- classification benefits from natural-language interpretation more than rigid rules;
- a recommendation can be evaluated without immediately granting write authority;
- the work is asynchronous, so the UNO Q's modest generation speed is acceptable;
- the platform can retain responsibility for credentials, validation, policy, observability, and
  audit while delegating only inference;
- a manually labelled fixture set can measure whether the model is useful before any mailbox
  mutation is introduced.

The local model is not an agent and does not own the workflow. It receives bounded input and returns
a recommendation. RUBIK owns every decision around that recommendation.

## 2. Current baseline

### 2.1 RUBIK

The current package is `personal-edge-lab` 0.8.1 and uses an inward-pointing modular architecture:

```text
apps -> application/ports <- infrastructure
                |
             modules -> domain
```

Relevant existing properties:

- Python 3.12, `httpx`, Pydantic, FastAPI, SQLite, and systemd are already established;
- configuration roots validate environment values before composing adapters;
- secrets such as Telegram tokens and owner credentials are stored outside Git with restrictive
  permissions;
- infrastructure HTTP clients translate transport and protocol failures into sanitized errors;
- architecture tests prevent modules from importing infrastructure or HTTP libraries;
- no generic task queue, plugin framework, AI package, email package, or background worker exists;
- the notification outbox is specifically an operational-notification delivery mechanism and must
  not become a generic AI queue.

### 2.2 UNO Q inference node

The first UNO Q is configured as `unoq-ai-01` and currently provides:

- Debian on the Linux side of the board;
- native `llama.cpp` built for AArch64;
- Qwen3 1.7B Q4_K_M stored locally;
- `llama-server` managed by the user-level `uno-ai.service`;
- user lingering enabled so the service starts without an interactive login;
- automatic restart on failure;
- an OpenAI-compatible HTTP API on port 8080;
- a 256-bit API key stored in a mode-`0600` file on the board;
- public `GET /health` and authenticated generation endpoints;
- LAN address observed during setup as `192.168.1.159`;
- mDNS hostname intended to be `unoq-ai-01.local`.

The service currently listens on the UNO Q's network interfaces so RUBIK can reach it. The
generation endpoint rejects missing or invalid API keys. A source-address firewall rule has not yet
been installed, so network hardening remains part of Work Package 0.

Observed Qwen3 1.7B behavior:

- exact JSON output was produced in the initial local test;
- prompt processing was approximately 4.7–4.8 tokens/second;
- generation was approximately 3.1–3.2 tokens/second;
- a short classification took roughly 18 seconds;
- the loaded process used roughly 1.4 GB resident memory during the manual benchmark;
- the node retained sufficient memory headroom for bounded, single-request inference.

Qwen3 4B Q4_K_M was also downloaded and tested. It loaded, but used roughly 2.65 GB resident memory,
touched swap, saturated all four CPU cores, and did not complete the same small classification in a
useful time. It remains a benchmark artifact, not the Stage 6A production model.

## 3. Stage boundaries

### 3.1 In scope

- secure RUBIK-to-UNO-Q connectivity;
- one concrete local language-model port;
- one `llama.cpp`/OpenAI-compatible HTTP adapter;
- explicit model, timeout, and concurrency configuration;
- versioned email-triage prompts;
- schema-constrained and validated triage output;
- a sanitized evaluation fixture set;
- repeatable quality and performance evaluation;
- optional Langfuse tracing that never becomes a runtime dependency;
- Gmail OAuth and bounded read-only retrieval;
- email normalization;
- an auditable, persistent dry-run triage lifecycle;
- a CLI or similarly narrow operator surface for running and inspecting dry runs;
- deployment, health, rollback, and reboot verification on RUBIK.

### 3.2 Explicitly out of scope

- applying, creating, or removing Gmail labels;
- archiving, deleting, marking read/unread, forwarding, or replying to email;
- sending email;
- allowing the model to call Gmail or hold Gmail credentials;
- allowing the UNO Q to initiate work;
- automatic cloud fallback;
- multiple provider routing, load balancing, or model sharding;
- splitting one model across the two UNO Q boards;
- a generic agent framework;
- a generic plugin framework;
- a generic distributed task queue;
- reusing the notification outbox as an inference queue;
- exposing prompts or raw email bodies through platform logs;
- storing Gmail refresh tokens in SQLite;
- placing Langfuse on the UNO Q;
- unattended continuous triage before bounded manual runs are accepted.

Mailbox mutation belongs to a separate Stage 6B and requires a new approval and safety plan.

## 4. Design principles

### 4.1 RUBIK owns the workflow

RUBIK owns:

- Gmail credentials and retrieval;
- input normalization and size limits;
- prompt selection and versioning;
- the allowed label taxonomy;
- model configuration;
- output parsing and validation;
- retries and failure policy;
- persistence and idempotency;
- observability;
- operator presentation;
- any future mailbox action.

The UNO Q owns:

- loading the selected model;
- tokenization and inference;
- its local inference runtime;
- returning the HTTP response.

### 4.2 Start concrete

The first adapter is for the actual `llama-server` node. Do not create a provider registry, dynamic
plugin discovery, multi-model scheduler, or generic agent protocol. Extract only the abstractions
required by the email-triage use case and the diagnostic CLI.

### 4.3 Read-only before write authority

Stage 6A can read Gmail and persist local recommendations. It cannot mutate Gmail. Successful
classification is not authorization to apply a label.

### 4.4 Typed failure is a valid outcome

Every invocation must finish as either:

- a validated completion/triage result; or
- a categorized, sanitized failure.

Malformed JSON, an unknown label, a timeout, and an unavailable UNO Q are expected operational
states, not reasons to bypass validation.

### 4.5 Local-first is a policy

No cloud model fallback occurs implicitly. If the UNO Q is unavailable, the run remains pending,
fails, or is retried according to an explicit bounded policy. A future cloud provider would require
its own opt-in configuration and privacy review.

### 4.6 Observability is non-blocking

Langfuse or any trace sink may enrich evidence, but a trace outage cannot make a valid inference
fail. Trace errors are logged in sanitized form and counted independently.

### 4.7 Minimize email disclosure

Raw email bodies, sender addresses, OAuth tokens, model API keys, and attachment contents must not
appear in normal logs or default Langfuse traces. Evaluation fixtures should be synthetic or
irreversibly sanitized.

## 5. Target runtime shape

```text
operator / later scheduler
          |
          v
email_triage app (composition and lifecycle)
          |
          v
TriageMailboxBatch use case
     |               |                    |
     v               v                    v
EmailSource     LanguageModel       TriageRepository
     |               |                    |
     v               v                    v
Gmail adapter   observed provider      SQLite
                     |
                LlamaCpp adapter
                     |
              authenticated HTTP
                     |
              UNO Q llama-server

Observed provider -> TraceSink -> Langfuse
```

The model never receives a Gmail client, repository, callback, credential, or action tool.

## 6. Proposed domain language

Names may change during implementation, but agents should preserve these concepts rather than
passing unstructured dictionaries across boundaries.

### 6.1 Inference concepts

- `ModelMessage`: role and bounded text content.
- `CompletionRequest`: messages, logical model name, maximum output tokens, temperature, and
  optional structured-output contract identifier.
- `CompletionResult`: text, provider/model identity, token counts when available, and timing.
- `CompletionFailure`: a sanitized category and whether the operation is eligible for retry.

Provider-specific request fields such as `/v1/chat/completions`, `choices`, GGUF paths, and
`system_fingerprint` stay inside infrastructure.

### 6.2 Email concepts

- `EmailMessageId`: stable Gmail message identifier.
- `EmailThreadId`: stable Gmail thread identifier.
- `EmailDocument`: normalized sender display, subject, received time, plain text, and bounded
  metadata required by triage.
- `EmailRetrievalCursor`: enough information to continue a bounded read without loading the whole
  mailbox.

Raw Gmail API payloads and HTML stay inside the Gmail adapter/normalizer boundary.

### 6.3 Triage concepts

- `TriageLabel`: one value from an owner-defined closed taxonomy.
- `TriageDecision`: label, model-reported confidence, short reason, and validation evidence.
- `TriageProfile`: taxonomy version, prompt version, model alias, parameters, and input limits.
- `TriageRun`: one bounded operator-requested batch.
- `TriageItem`: one message's pending, completed, or failed result inside a run.
- `TriageFailure`: categorized retrieval, normalization, inference, or validation failure.

Model-reported confidence is evidence, not a calibrated probability and not sufficient by itself
for future automation.

## 7. Proposed package ownership

Packages are created only when their first real behavior is implemented.

```text
src/personal_edge_lab/
├── domain/
│   ├── ai.py                    # only when inference value types are first used
│   └── email_triage.py          # when the first triage behavior exists
├── application/ports/
│   ├── ai.py                    # LanguageModel
│   ├── email.py                 # EmailSource, added with Gmail read work
│   ├── email_triage.py          # persistence ports, added with durable runs
│   └── observability.py         # only if a real trace sink abstraction is required
├── infrastructure/
│   ├── ai/
│   │   ├── llama_cpp.py         # authenticated llama-server adapter
│   │   └── langfuse.py          # optional observed-provider/trace sink
│   ├── gmail/
│   │   ├── client.py            # Gmail transport and response translation
│   │   └── normalization.py     # MIME/HTML-to-bounded-text conversion
│   └── persistence/sqlite/
│       └── email_triage.py      # only after durable run semantics are fixed
├── modules/
│   └── email_triage/
│       ├── prompts.py           # packaged prompt/profile implementation
│       ├── evaluation.py        # fixture evaluation and metrics
│       └── service.py           # batch triage orchestration
└── apps/
    ├── ai_cli/                  # first connectivity and provider diagnostic
    └── email_triage_cli/        # bounded Gmail/dry-run composition root
```

This is a target shape, not permission to create all directories in the first pull request.
`tests/architecture/test_dependency_direction.py` must be extended only as real modules appear.

## 8. Configuration and secret policy

Provisional environment names:

```dotenv
LOCAL_LLM_BASE_URL=http://unoq-ai-01.local:8080
LOCAL_LLM_API_KEY_FILE=/absolute/private/path/unoq-ai-01.key
LOCAL_LLM_MODEL=qwen3-1.7b-q4-k-m
LOCAL_LLM_TIMEOUT_SECONDS=60
LOCAL_LLM_MAX_CONCURRENCY=1
LOCAL_LLM_QUEUE_TIMEOUT_SECONDS=60
LOCAL_LLM_ENABLED=false
```

Later Gmail values should refer to private files rather than embedding tokens:

```dotenv
GMAIL_CLIENT_SECRET_FILE=/absolute/private/path/gmail-client.json
GMAIL_TOKEN_FILE=/absolute/private/path/gmail-token.json
GMAIL_TRIAGE_ENABLED=false
GMAIL_TRIAGE_BATCH_SIZE=10
```

Langfuse configuration remains optional:

```dotenv
LANGFUSE_ENABLED=false
LANGFUSE_BASE_URL=https://chosen-private-or-hosted-endpoint
LANGFUSE_PUBLIC_KEY_FILE=/absolute/private/path/langfuse-public-key
LANGFUSE_SECRET_KEY_FILE=/absolute/private/path/langfuse-secret-key
LANGFUSE_CAPTURE_EMAIL_CONTENT=false
```

Exact names become contractual only when implemented and documented in `.env.example`.

Requirements:

- secret files are owned by the service account and mode `0600`;
- configuration errors fail before starting a run;
- errors never include secret values;
- HTTP client debug logging is disabled when it could expose authorization headers;
- the API key is never accepted as a command-line argument on RUBIK;
- Gmail OAuth refresh tokens never enter Git, SQLite, traces, or test fixtures;
- configuration tests cover blank values, invalid URLs, invalid bounds, missing files, directory
  paths, and unsafe permissions where enforceable.

## 9. Failure taxonomy and retry policy

| Boundary outcome | Category | Retry in Stage 6A | Required behavior |
| --- | --- | --- | --- |
| UNO Q DNS/connect failure | `connection` | Bounded, later worker only | No mailbox action; record failure |
| Inference timeout | `timeout` | At most one explicit retry after evaluation | Same idempotency key and profile |
| HTTP 401/403 | `authentication` | No | Halt run; configuration error |
| HTTP 429 | `rate_limited` | Honor retry delay when provided | Do not increase concurrency |
| HTTP 503 during model load | `not_ready` | Short bounded wait | Preserve run state |
| Other HTTP 4xx | `request_rejected` | No | Sanitize response details |
| Other HTTP 5xx | `provider_failure` | Bounded | Record node and provider evidence |
| Non-JSON HTTP response | `invalid_provider_response` | No automatic retry initially | Preserve sanitized diagnostic |
| Valid provider response, malformed model text | `invalid_model_output` | No automatic repair initially | Mark item failed |
| Unknown triage label | `invalid_triage_label` | No | Never coerce to a real label |
| Gmail temporary HTTP error | `email_source_unavailable` | Bounded | No partial mailbox mutation |
| Gmail authentication failure | `email_authentication` | No | Halt retrieval |
| Unsupported/oversized message | `unsupported_email` | No | Record bounded reason |
| Langfuse unavailable | `trace_unavailable` | Independent only | Inference result remains valid |

Inference retries are semantically different from AC command retries: inference has no physical side
effect. Even so, retries must be bounded because they consume scarce node capacity and may duplicate
trace records.

## 10. Work packages

Each work package should normally be one reviewable branch or pull request. A package may be split
further, but later packages must not be pulled forward without recording the reason.

### Work Package 0 — Freeze and harden the UNO Q contract

**Goal:** turn the manually proven inference node into a documented dependency with a stable
network and security contract.

**Deliverables**

- Record the actual `uno-ai.service`, model path, llama.cpp revision, bind policy, restart policy,
  and key-file permissions in an operations document.
- Confirm RUBIK resolves `unoq-ai-01.local`; if it does not, reserve a DHCP address and use that
  stable address.
- Restrict TCP 8080 on the UNO Q to source `192.168.1.81` or the final reserved RUBIK address.
- Confirm the health endpoint is intentionally public but reveals no model path, key, prompt, or
  email data.
- Confirm `/v1/chat/completions` returns 401 without the key.
- Decide whether the 4B benchmark file remains on the node or is removed to reduce maintenance
  ambiguity. Its presence must never change the selected production model.
- Document key rotation without exposing the current key.
- Capture idle and one-request memory, swap, CPU, and latency evidence.

**Tests and verification**

- Reach health and authenticated completion from RUBIK.
- Reject completion from a second LAN client without a key.
- After the firewall is installed, reject TCP 8080 from a non-RUBIK source.
- Restart `uno-ai.service` and repeat the checks.
- Reboot the UNO Q and repeat the checks.
- Confirm Qwen3 1.7B, context 1024, four threads, and maximum one active request.

**Acceptance**

- RUBIK has one stable URL and one private key-file path.
- Reboot does not require an interactive SSH login.
- The production model is unambiguous.
- Network exposure matches the documented policy.

**Not included**

- RUBIK application code;
- Gmail;
- Langfuse;
- model quality decisions.

### Work Package 1 — RUBIK-to-UNO-Q connectivity slice

**Goal:** prove RUBIK can operate the node through packaged Python code rather than ad hoc `curl`.

**First user-visible behavior**

```bash
python -m personal_edge_lab.apps.ai_cli health
python -m personal_edge_lab.apps.ai_cli complete --text "Return exactly ready"
```

The exact CLI shape may change, but it must support one health check and one bounded completion.

**Deliverables**

- Minimal inference value types required by the CLI.
- A narrow `LanguageModel` application port.
- An `httpx`-based `LlamaCppLanguageModel` adapter.
- Sanitized adapter errors with the categories in Section 9.
- Configuration loading for base URL, key file, logical model alias, timeout, and output limit.
- An `ai_cli` composition root.
- Logs containing operation IDs, outcome categories, elapsed time, and token counts when available.
- No prompt system, Gmail code, persistence, Langfuse, or scheduler.

**Adapter contract**

- Send `POST /v1/chat/completions`.
- Use bearer authentication read from the private key file.
- Use one HTTP attempt by default in this package.
- Bound input and `max_tokens`.
- Set deterministic parameters explicitly rather than relying on server defaults.
- Translate the OpenAI-compatible envelope into internal types.
- Never expose the GGUF path as the application model identity; use a logical alias.
- Close the `httpx.Client` deterministically.

**Tests**

- Unit tests for configuration validation.
- Contract tests using `httpx.MockTransport` for success, 401, 429, 503, timeout, malformed JSON,
  missing choices, missing content, invalid usage fields, and oversized input.
- CLI contract tests for exit codes and sanitized output.
- An opt-in real-node integration test marked so the normal suite does not require the UNO Q.
- Architecture tests for the first real AI module/port/adapter boundaries.

**Acceptance**

- The packaged CLI succeeds from RUBIK against the real UNO Q.
- A bad key produces a sanitized authentication failure and non-zero exit.
- An unavailable node fails inside the configured timeout.
- No secret or authorization header appears in logs, exceptions, or test snapshots.
- Existing API, collector, alerting, Telegram, dashboard, and AC tests remain green.

### Work Package 2 — Provider contract and operational semantics

**Goal:** make the first adapter reliable enough to be consumed by later use cases without building
a provider platform.

**Deliverables**

- Finalize request/result types around the evidence the use case actually needs.
- Define logical provider/model identity separately from the server-reported GGUF path.
- Add a provider capability description only if structured output or token usage needs runtime
  negotiation.
- Enforce `LOCAL_LLM_MAX_CONCURRENCY=1` in RUBIK.
- Add one process-local concurrency guard so simultaneous apps cannot accidentally fan out inside
  the same process.
- Define readiness separately from liveness.
- Define sanitized metrics/log fields.
- Document whether a timeout includes connection, model wait, and response reading as one budget or
  separate budgets.
- Decide after benchmarks whether one bounded retry is useful; default remains no retry.

**Non-goal**

Do not add provider discovery, weighted routing, automatic fallback, model downloads, or remote
UNO-Q administration.

**Tests**

- Concurrency test proving a second request queues or fails according to the chosen policy.
- Timeout boundary tests.
- Stable logical model identity tests.
- Response usage normalization tests.
- Adapter close/reuse tests.

**Acceptance**

- Later modules depend only on the `LanguageModel` port.
- `llama.cpp` request and response structures appear only under infrastructure and adapter tests.
- Operational failures are sufficiently categorized for health and observability.

### Work Package 3 — Email-triage contract, prompt, and schema

**Goal:** define what “triage” means before introducing a mailbox.

**Decisions required before implementation**

- Initial owner-defined labels and their plain-language definitions.
- Whether “needs reply” is a label, a separate boolean, or deferred.
- Whether newsletters and automated notifications are distinct.
- Maximum subject/body characters sent to the model.
- Treatment of quoted replies, signatures, tracking text, and multilingual content.
- Whether the reason field is retained and where it may be displayed.

**Recommended initial output**

```json
{
  "label": "billing",
  "confidence": 0.91,
  "reason": "A monthly invoice is available"
}
```

The exact taxonomy must be closed and versioned. Example candidate labels are illustrative only:

```text
work
needs_reply
billing
notification
newsletter
personal
other
```

**Deliverables**

- Pure `TriageLabel`, `TriageDecision`, and `TriageProfile` domain types.
- A prompt renderer owned by `modules/email_triage`, not the HTTP adapter.
- A checked-in prompt/profile version for reproducible evaluation.
- A strict Pydantic schema at the app/infrastructure parsing boundary, mapped into domain types.
- Explicit temperature, output-token limit, context budget, and no-thinking instruction.
- Structured-output request support when confirmed compatible with the deployed llama.cpp build.
- A deterministic fallback parser only if the returned envelope requires it; do not “repair” an
  unknown label into a valid one.
- Prompt-injection resistance instructions: email content is untrusted data, never instructions.

**Prompt version identity**

At minimum, one result must record:

```text
profile_name
profile_version
prompt_version
taxonomy_version
provider
model_alias
generation_parameters
```

**Tests**

- Renderer tests for escaping and clear separation between instructions and email data.
- Schema tests for every valid label.
- Rejection tests for unknown labels, missing fields, extra dangerous fields, NaN/out-of-range
  confidence, excessive reason length, Markdown fences, and prose around JSON.
- Injection fixtures asking the model to ignore the taxonomy or disclose secrets.
- Unicode, Spanish, English, mixed-language, empty-body, and long-body cases.

**Acceptance**

- Every model response becomes either a valid `TriageDecision` or a typed validation failure.
- The HTTP adapter contains no email labels or prompt text.
- Changing a prompt or taxonomy changes its recorded version.
- The model cannot expand the allowed action or label set.

### Work Package 4 — Evaluation harness without Gmail

**Goal:** determine whether Qwen3 1.7B is good enough using repeatable evidence rather than mailbox
experimentation.

**Fixture policy**

- Use synthetic or irreversibly sanitized messages.
- Keep expected labels under version control.
- Include difficult and ambiguous examples, not only obvious successes.
- Do not include real addresses, order numbers, account numbers, tokens, or private signatures.
- Keep a small human-readable core set and a larger evaluation set if needed.

**Minimum fixture dimensions**

- each allowed label;
- Spanish, English, and mixed language;
- terse subjects with empty bodies;
- long newsletters;
- invoices and payment notices;
- automated work notifications;
- messages requiring an answer;
- ambiguous personal/work messages;
- quoted reply chains;
- HTML-derived noise;
- prompt-injection content;
- unsupported or oversized content.

**Deliverables**

- An evaluation entrypoint that reads fixtures and calls the real `LanguageModel` port.
- A fake provider for deterministic unit tests.
- Metrics for:
  - schema-valid rate;
  - accuracy by label;
  - confusion matrix;
  - unknown/invalid output rate;
  - latency median and p95;
  - prompt and completion token counts;
  - repeated-run disagreement;
  - model-reported confidence distribution.
- Machine-readable evaluation output and a concise human report.
- A stable evaluation run identifier tied to prompt, taxonomy, model, and fixture versions.

**Gates**

- Automated tests must prove metric calculation, not model quality.
- The initial real-model run establishes the baseline; agents must not invent a pass threshold
  after seeing only a few examples.
- Before Gmail work starts, the owner records acceptable minimum quality by label and maximum
  tolerable latency.
- Labels that fail the precision requirement remain “review only” or are removed from the initial
  taxonomy.
- Confidence must not drive automation until calibration is measured against labelled data.

**Acceptance**

- The same evaluation can be rerun after prompt, model, or llama.cpp changes.
- Results make regressions visible.
- A model failure cannot crash or truncate the whole report.
- The owner explicitly records whether the 1.7B model is accepted for read-only shadow use.

### Work Package 5 — Non-blocking observability and Langfuse

**Goal:** make inference behavior inspectable without coupling the domain or core use case to
Langfuse availability.

**Placement**

Preferred shape:

```text
LanguageModel port
       ^
       |
ObservedLanguageModel decorator
       |
LlamaCppLanguageModel

ObservedLanguageModel -> TraceSink -> Langfuse adapter
```

The decorator implements the same port. Modules do not import the Langfuse SDK.

**Trace content by default**

- operation/run/item correlation IDs;
- provider and logical model alias;
- profile, prompt, and taxonomy versions;
- generation parameters;
- start/end timestamps and latency;
- token usage;
- completion outcome category;
- schema-validation outcome;
- retry number;
- input character/token counts;
- a one-way message identifier hash.

**Excluded by default**

- raw sender address;
- raw subject;
- raw body;
- attachments;
- Gmail access/refresh tokens;
- UNO Q API key;
- full provider authorization headers;
- persisted Gmail payloads.

For fixture evaluation, synthetic prompt/input capture may be enabled explicitly. Real mailbox
content capture requires a separate privacy decision.

**Deliverables**

- A narrow trace sink or observed-provider implementation.
- A no-op implementation used when Langfuse is disabled.
- Failure isolation: trace submission errors never replace inference results.
- Flush/shutdown behavior owned by the app composition root.
- Configuration and secret-file validation.
- A trace naming and metadata convention.
- Documentation of whether Langfuse is hosted, self-hosted on a separate node, or deferred.

Langfuse should not be placed on the UNO Q. Before self-hosting it on RUBIK, measure its database,
memory, and operational requirements; observability must not overload the platform it observes.

**Tests**

- Successful trace around a successful inference.
- Trace around each failure category.
- Trace sink timeout/failure while inference succeeds.
- Disabled/no-op behavior.
- Redaction tests proving secrets and raw email content are absent.
- Flush behavior during graceful app shutdown.

**Acceptance**

- An operator can correlate an evaluation item with one provider call.
- Langfuse downtime does not block or invalidate inference.
- Default traces contain no mailbox content.
- Metrics available locally remain sufficient to diagnose a total Langfuse outage.

### Work Package 6 — Gmail read-only source

**Goal:** retrieve and normalize a bounded Gmail batch without invoking the model and without
changing Gmail.

**OAuth scope**

Use the narrowest Gmail read-only scope that supports the accepted retrieval contract. Do not
request modify, compose, send, or label scopes in Stage 6A.

**Deliverables**

- An `EmailSource` application port expressed in domain terms.
- A Gmail adapter that owns OAuth, pagination, Gmail IDs, MIME payloads, and API errors.
- A local operator flow for initial OAuth authorization.
- Client secret and refresh token files outside Git with mode `0600`.
- Bounded query, batch size, pagination, and message-size configuration.
- Retrieval of message ID, thread ID, received timestamp, sender display, subject, and the content
  required for triage.
- MIME selection and HTML-to-text normalization.
- Removal or bounding of quoted history, signatures, tracking links, and repetitive footer text
  according to recorded rules.
- A read-only CLI command that lists normalized metadata and content lengths without printing bodies
  by default.

**Recommended first query**

Start with an explicit small batch such as the latest 10 messages matching an owner-supplied Gmail
query. Do not silently use the entire inbox.

**Tests**

- Gmail HTTP contract tests with recorded synthetic responses or a mock transport.
- Multipart plain-text and HTML-only messages.
- Nested MIME, encoded headers, Unicode, empty body, malformed MIME, oversized content, and
  unsupported attachment-only messages.
- Pagination and batch bounds.
- OAuth expiry/refresh and invalid-grant behavior.
- Logging redaction.
- Proof that no Gmail mutation endpoint is called.

**Live acceptance**

- Authorize the dedicated Gmail integration interactively on RUBIK.
- Retrieve a tiny bounded batch.
- Compare normalized metadata against Gmail manually.
- Revoke or rotate the token and verify a sanitized, non-retrying authentication failure.
- Confirm mailbox state is unchanged.

**Not included**

- model calls;
- local triage persistence;
- Gmail labels or writes;
- periodic polling.

### Work Package 7 — Durable read-only triage runs

**Goal:** connect Gmail retrieval, normalization, the prompt/profile, the local model, validation,
and local persistence in one bounded dry-run capability.

**Lifecycle**

```text
requested
  -> retrieving
  -> classifying each bounded item
  -> completed_with_results
  -> completed_with_failures

or

requested -> failed_before_items
```

Exact names may change, but the run must distinguish total failure from partial per-item failure.

**Idempotency identity**

At minimum:

```text
gmail_message_id
+ triage_profile_version
+ prompt_version
+ taxonomy_version
+ model_alias
+ generation_parameter_version
```

Rerunning an identical identity should return or reference the existing result unless the operator
explicitly requests a new evaluation attempt. Attempts remain separately auditable.

**Persistence design**

Append a new ordered SQLite migration only after lifecycle and query needs are fixed. Candidate
records:

- triage runs;
- run items;
- inference attempts;
- validated decisions;
- categorized failures.

Store normalized input only if a separate retention/privacy decision permits it. Prefer hashes,
lengths, Gmail IDs, and decision evidence over copied mailbox content.

**Deliverables**

- `TriageMailboxBatch` use case under `modules/email_triage`.
- Repository ports and SQLite adapter.
- One transactional reservation/creation path so duplicate runs cannot race.
- Bounded sequential processing; maximum one UNO Q inference at a time.
- A dry-run CLI that starts a run and prints a concise result summary.
- Query commands for recent runs and one run's items.
- Graceful interruption: completed items remain recorded; interrupted pending work has an explicit
  state.
- No Gmail write client in the process.

**Tests**

- Full use-case tests with fake email source, fake model, fake clock, and in-memory/fake repository.
- Integration tests for migration, uniqueness, partial failure, restart recovery, and query bounds.
- One message succeeding while another fails validation.
- Gmail retrieval failing before item creation.
- UNO Q unavailable mid-run.
- Duplicate invocation with identical idempotency identity.
- Graceful SIGTERM between items.
- Architecture boundary tests.

**Acceptance**

- An operator can run triage for a bounded Gmail query and inspect recommendations locally.
- Gmail remains unchanged.
- Every item has a valid decision or explicit failure.
- Repeating the same profile does not create ambiguous duplicate results.
- A process crash cannot turn a failed or unknown item into an apparent success.

### Work Package 8 — Shadow-mode operator presentation

**Goal:** make dry-run results useful enough for human evaluation before considering automation.

Start with the narrowest existing operator surface. A CLI is sufficient for first acceptance.
Dashboard or Casadaqui presentation should be added only when a concrete review workflow is chosen.

**Possible first presentation**

```text
Run 42: 10 messages
7 classified, 2 review-required, 1 provider failure

message hash | received | proposed label | confidence | status
```

Do not print raw bodies. Sender/subject disclosure requires an explicit trusted-surface decision.

**Deliverables**

- bounded run list and detail query;
- clear distinction between model recommendation and applied mailbox state;
- filters for failed, invalid, and low-confidence items;
- prompt/model/profile version shown for reproducibility;
- evaluation feedback capture only if a concrete correction workflow is implemented;
- no “approve” button that mutates Gmail in Stage 6A.

**Acceptance**

- The owner can review whether recommendations are useful.
- The UI cannot imply that a Gmail label was applied.
- Failures remain visible rather than disappearing from aggregate success counts.
- Existing authentication and authorization policy protects any dashboard view.

### Work Package 9 — Optional scheduled shadow operation

**Goal:** run bounded read-only triage without an operator shell, but only after manual runs are
accepted.

This is optional for Stage 6A. Do not start it merely because the earlier code exists.

**Deliverables if approved**

- A dedicated `email_triage_worker` or one-shot app plus systemd timer.
- Independent lifecycle and health evidence; do not attach it to telemetry, alert evaluation, API,
  or Telegram polling loops.
- One active run maximum.
- Bounded Gmail query and batch size.
- Backoff for source/provider unavailability.
- Pause/disable configuration.
- Clean shutdown between items.
- Runtime status available to platform health only after a concrete query need exists.

**Deployment**

- Capture the real RUBIK service user, working directory, environment files, restart policy, and
  Python path before checking in a unit.
- Deploy first with `GMAIL_TRIAGE_ENABLED=false`.
- Apply additive migrations and inspect integrity.
- Run one manual dry-run.
- Enable one scheduled invocation.
- Reboot and verify service/timer behavior.

**Acceptance**

- Scheduling cannot create overlapping runs.
- Failure does not affect telemetry, API, AC, alerting, or Casadaqui.
- Disabling the feature stops new work without deleting history.
- Gmail remains read-only.

## 11. Test strategy

### 11.1 Unit tests

- pure domain validation;
- prompt rendering;
- schema parsing;
- taxonomy enforcement;
- use-case orchestration with fakes;
- metric computation;
- error and retry classification;
- redaction.

### 11.2 Contract tests

- llama-server HTTP requests and responses through `httpx.MockTransport`;
- Gmail API responses through a mock transport;
- CLI exit codes and output;
- FastAPI contracts only if an operator API is later added;
- systemd unit content only after the live unit is captured.

### 11.3 Integration tests

- SQLite migrations and repositories;
- run idempotency and partial failure;
- observed-provider behavior with a fake trace sink;
- application composition with temporary secret files;
- opt-in real UNO Q calls from RUBIK.

### 11.4 Evaluation tests

Evaluation measures model behavior and must not make the normal deterministic test suite flaky.
Real-model evaluation should be an explicit command/artifact, not a mandatory unit-test assertion.

### 11.5 Live acceptance

Live checks occur in this order:

1. UNO Q health and authenticated completion.
2. Packaged RUBIK `ai_cli`.
3. Fixture evaluation.
4. Optional Langfuse trace.
5. Bounded Gmail read.
6. One-message dry-run.
7. Ten-message dry-run.
8. Restart and retry behavior.
9. RUBIK reboot.
10. Optional scheduled shadow run.

At every point, confirm Gmail state is unchanged.

## 12. Quality gates

Every merged package must satisfy:

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m pyright
python -m build
python scripts/inspect_wheel.py dist/*.whl
```

Additional Stage 6A gates:

- no secret-like values in Git;
- no raw email fixture derived from a real mailbox without documented sanitization;
- no domain/module import of `httpx`, Gmail SDKs, Langfuse SDKs, SQLite, FastAPI, or app code;
- no Gmail write OAuth scope;
- no Gmail mutation endpoint;
- no unbounded mailbox query;
- no unbounded model input or output;
- no more than one in-flight inference on the UNO Q;
- no implicit cloud fallback;
- all output validation failures are explicit;
- Langfuse-disabled operation is fully supported;
- existing physical-control semantics remain unchanged.

## 13. Security and privacy checklist

- [ ] UNO Q port 8080 is restricted to RUBIK at the network layer.
- [ ] UNO Q API key exists only in private secret files.
- [ ] RUBIK service account can read the key; other users cannot.
- [ ] Authorization headers are absent from logs and traces.
- [x] Gmail client secret and token files are mode `0600`.
- [x] Gmail OAuth uses read-only scope in Stage 6A.
- [x] Raw email bodies are absent from normal logs.
- [x] Real email content is absent from Langfuse by default.
- [ ] Fixture data is synthetic or irreversibly sanitized.
- [ ] Model input has character/token bounds.
- [ ] Email content is delimited and treated as untrusted data.
- [ ] Model output cannot add labels or actions.
- [ ] No model response is executed as code or a tool call.
- [ ] No attachment is sent to the model in the initial slice.
- [ ] Local persistence retention is explicitly chosen.
- [ ] Backup and rollback include any new SQLite migration.

## 14. Open decisions

Resolve each decision at the start of the package that needs it, not all at once.

### Before Work Package 1

- Does RUBIK reliably resolve `unoq-ai-01.local`, or should the router reserve the UNO Q address?
- Where will RUBIK store the UNO Q API key?
- What is the accepted request timeout for the diagnostic CLI?
- Should health distinguish node reachability from model readiness?

### Before Work Package 3

- What is the initial closed taxonomy?
- Is “needs reply” mutually exclusive with categories such as work/billing?
- How much sender, subject, and body content is necessary?
- Is the reason stored or only shown during evaluation?
- What languages must the initial profile support?

### Before Work Package 4

- How many labelled fixtures are sufficient for the first baseline?
- Which per-label precision/recall requirements make the model useful?
- What latency is acceptable for manual and scheduled batches?
- How many repeated runs are needed to measure consistency?

### Before Work Package 5

- Hosted or self-hosted Langfuse?
- If self-hosted, on RUBIK or a separate node?
- Is any real email content permitted in traces?
- Is packaged prompt source-of-truth sufficient initially, or is Langfuse prompt management a
  concrete requirement?

### Before Work Package 6

- Which Gmail account is in scope?
- Which exact Gmail query bounds the first batch?
- Which read-only OAuth scope is sufficient?
- How are quoted threads and HTML normalized?
- What local metadata may be persisted?

### Before Work Package 9

- Is scheduled shadow triage useful enough to operate continuously?
- Polling interval and maximum batch size?
- Retry/backoff and pause policy?
- Retention period for run and item evidence?

## 15. Stage 6A completion criteria

Stage 6A is done only when:

- the UNO Q inference contract is documented, stable after reboot, and network-restricted to RUBIK;
- RUBIK has a tested, sanitized `LanguageModel` port and llama.cpp adapter;
- prompt, taxonomy, profile, model, and parameter versions are reproducible;
- all outputs become valid decisions or typed failures;
- a sanitized labelled fixture set and repeatable evaluation report exist;
- model quality and latency are explicitly accepted for shadow use;
- Langfuse is integrated non-blockingly or explicitly deferred with local evidence retained;
- Gmail OAuth uses read-only authority;
- a bounded Gmail batch is retrieved and normalized without mailbox changes;
- one durable dry-run connects Gmail to the UNO Q through application ports and use cases;
- results and failures are inspectable;
- duplicate work is controlled by a recorded identity;
- shutdown, restart, node outage, Gmail outage, and invalid output behavior are verified;
- existing tests and quality gates pass;
- RUBIK deployment, reboot acceptance, backup, and rollback are recorded;
- the main roadmap and development log are updated with delivered behavior and known limitations.

## 16. Stage 6B boundary — mailbox actions

Stage 6B may begin only after Stage 6A evidence shows that one or more labels are sufficiently
precise. It requires a separate plan covering:

- a distinct `EmailLabelWriter` port;
- Gmail modify scope added deliberately;
- an allowlist of labels;
- creation versus use of existing labels;
- manual approval mode;
- per-label automation thresholds based on measured precision;
- optimistic checks against message changes;
- idempotent label application;
- durable audit;
- a kill switch;
- rollout from shadow to suggestion to limited automatic labeling;
- no archive/delete/send/reply authority in the first write slice.

Nothing in Stage 6A should pre-authorize these actions.

## 17. Agent execution protocol

Agents working from this document must:

1. Read this plan, `docs/architecture.md`, the relevant current implementation, and architecture
   tests before editing.
2. Select one work package or a clearly bounded sub-package.
3. Inspect the dirty worktree and preserve unrelated user changes.
4. Record unresolved decisions instead of silently choosing broad new scope.
5. Implement the smallest useful real behavior; do not create empty future packages.
6. Add tests at the same boundary as the behavior.
7. Run the proportional quality gates.
8. Update this document's package status and the main development log with factual evidence.
9. Separate local implementation verification from real RUBIK/UNO-Q acceptance.
10. Stop when new credentials, OAuth consent, mailbox authority, router changes, or root access are
    required and hand the exact action to the owner.

### Handoff template

```markdown
## Work Package N handoff

**Status:** Not started | In progress | Implemented locally | Accepted on RUBIK | Blocked

**Delivered**

- Concrete behavior and files.

**Decisions**

- Decisions made and why.

**Verification**

- Commands and results.
- Real-node checks, if any.

**Security/privacy**

- Secrets, scopes, logging, and data-handling checks.

**Known limitations**

- Explicitly deferred behavior.

**Next**

- Smallest next package.

**Owner action required**

- Exact manual action, or “None”.
```

## 18. Work-package status

| Package | Status | Exit artifact |
| --- | --- | --- |
| WP0. UNO Q contract and hardening | Accepted on RUBIK | Stable, rebooted, source-restricted node |
| WP1. RUBIK connectivity slice | Accepted on RUBIK | Packaged `ai_cli` real-node success |
| WP2. Provider operational semantics | Accepted on RUBIK | Stable `LanguageModel` contract |
| WP3. Triage prompt and schema | Accepted on RUBIK | Versioned validated triage profile |
| WP4. Fixture evaluation | Not started | Reproducible quality/latency report |
| WP5. Langfuse observability | Accepted on RUBIK | Non-blocking synthetic trace contract |
| WP6. Gmail read-only source | Accepted on RUBIK | Bounded normalized Gmail retrieval |
| WP7. Durable dry-run pipeline | Accepted on RUBIK | Audited Gmail-to-UNO-Q recommendations |
| WP8. Shadow-mode presentation | Not started | Human-inspectable dry-run results |
| WP9. Scheduled shadow operation | Optional | Bounded independent worker/timer |

WP0 was accepted on RUBIK on 2026-07-26. The live contract was captured, the RUBIK key copy was
installed with mode `0600`, `--parallel 1` was made explicit, a bounded authenticated request
succeeded, resource evidence was recorded, key rotation was documented, and service-restart checks
passed. A compatible persistent legacy-iptables source rule permits RUBIK while blocking a
non-RUBIK LAN source. Reboot acceptance passed, reliable pre/post-reboot mDNS resolution made
`unoq-ai-01.local` the stable application identity, and the unused 4B benchmark model was removed
after explicit owner approval.

## Work Package 0 handoff

**Status:** Accepted on RUBIK

**Delivered**

- Captured the live UNO Q service, llama.cpp revision, production-model identity, bind/restart
  policy, user lingering, key metadata, and idle resource baseline.
- Added the reviewed service and dedicated source-filter rule under `deploy/unoq-ai-01`.
- Added the versioned operational contract at `docs/contracts/unoq-ai-01.md`.
- Installed the private API-key copy for RUBIK and protected repository `secrets/` paths.
- Made one parallel server slot explicit and retained the prior service unit for rollback.
- Removed the unreferenced 4B benchmark model after explicit owner approval.
- Included the generated dashboard artifacts in source distributions so the documented isolated
  build gate remains reproducible.

**Decisions**

- Canonical application URL is `http://unoq-ai-01.local:8080`; reliable pre/post-reboot mDNS means
  the observed `192.168.1.159` address is not application configuration.
- RUBIK stores the key at `/home/ubuntu/personal-edge-lab/secrets/unoq-ai-01.key`.
- The health response is minimal and unauthenticated; authenticated completion proves model
  readiness until Work Package 2 defines separate operational semantics.

**Verification**

- RUBIK health returned `200`; unauthenticated completion returned `401`.
- Authenticated bounded completion returned `200` in 8.329 seconds with 31 total tokens.
- The service remained enabled and active after installing the one-slot unit and restarting it.
- Process RSS remained between 1,443,560 and 1,450,140 KiB and process swap remained zero across the
  recorded request window.
- After firewall installation, RUBIK retained health and authenticated completion access, a
  non-RUBIK source timed out on TCP 8080, and SSH remained available.
- After a full UNO Q reboot, both services started automatically, RUBIK retained authenticated
  access, the non-RUBIK source remained blocked, and process swap remained zero.
- The final local gate passed 265 tests, Ruff lint/format, Pyright with the CI interpreter,
  isolated source/wheel builds, wheel inspection, shell syntax checks, and Git diff checks.

**Security/privacy**

- No key value or digest was printed or added to Git.
- UNO Q and RUBIK key files are mode `0600`; the RUBIK secrets directory is mode `0700`.
- TCP 8080 is restricted to RUBIK by the dedicated `UNO_AI_INPUT` legacy-iptables chain.

**Known limitations**

- The bounded diagnostic returned a valid provider envelope but did not follow the requested exact
  text. Prompt/model quality remains explicitly deferred to Work Packages 3 and 4.

**Next**

- Implement Work Package 1, the packaged RUBIK-to-UNO-Q connectivity slice.

**Owner action required**

- None.

## Work Package 1 handoff

**Status:** Accepted on RUBIK

**Delivered**

- Added pure bounded inference request, message, usage, and result types plus the narrow
  `LanguageModel.complete` port and sanitized failure categories.
- Added a single-attempt synchronous llama.cpp adapter, separate public health probe, deterministic
  generation parameters, provider-envelope validation, and logical model identity translation.
- Added packaged `health` and feature-gated `complete --text` commands with bounded configuration,
  private-key validation, human-readable evidence, stable exit codes, and content-free logs.
- Added the eight frozen `LOCAL_LLM_*` settings, wheel inspection, release `0.9.0`, and a RUBIK
  deployment guard that validates and backs up the enabled key.
- Added no feature module, prompt system, persistence, Gmail access, Langfuse integration, retry,
  scheduler, service, migration, provider framework, or dashboard surface.

**Decisions**

- Public health remains liveness only and reads neither the feature gate nor API key.
- Authenticated completion is the WP1 readiness proof; any valid completion envelope is accepted
  without treating instruction-following as a quality gate.
- The server-reported GGUF path is ignored. Evidence uses provider `llama_cpp` and logical alias
  `qwen3-1.7b-q4-k-m`.
- WP1 performs exactly one synchronous request. Concurrency and retry policy remain WP2 work.

**Verification**

- The local and RUBIK full gates each passed 341 tests with the one opt-in live test skipped, Ruff
  lint/format, Pyright with Python 3.12, ShellCheck, frontend lint/10 tests/build, isolated wheel
  build, wheel inspection, and Git diff checks.
- The opt-in `unoq_live` test passed on RUBIK.
- Disabled completion exited `2`; enabled health and authenticated completion succeeded from the
  packaged `0.9.0` wheel. The accepted completion used 11 prompt and 32 completion tokens in
  13.690 seconds.
- A temporary valid-format wrong key produced sanitized `authentication` and exit `5`. An
  unavailable loopback origin produced `connection` and exit `3`.
- The API reported `0.9.0`; collector, API, alert timer, Casadaqui, Nginx, UNO Q inference, and the
  WP0 firewall were active. SQLite integrity returned `ok`, the dashboard returned `200`, and a
  non-RUBIK source still timed out on TCP 8080.
- The deployment retained a mode-`0600`, `ubuntu`-owned key backup under
  `/home/ubuntu/backups/personal-edge-lab/20260726T174041Z`.

**Security/privacy**

- Contract and CLI tests prove sentinel keys, authorization values, prompts, provider error bodies,
  and GGUF paths do not appear in errors or logs.
- Successful model text is written only to CLI standard output after terminal-control sanitization.
- The real key remained in its mode-`0600` file and was never printed or added to Git.

**Known limitations**

- The accepted diagnostic returned a valid envelope with empty visible `message.content`; prompt
  and model quality remain deliberately deferred to WP3 and WP4.
- Health is liveness, not a generic language-model capability method.
- There is no retry or concurrency guard.

**Next**

- Plan and implement WP2 provider operational semantics without widening into email or prompt work.

**Owner action required**

- None.

## Work Package 2 handoff

**Status:** Accepted on RUBIK on 2026-07-27

**Delivered**

- Added validated logical model identity and separate queue/provider timing while retaining the
  existing result compatibility properties.
- Added a standard-library process-local concurrency limiter with one permit, bounded waiting,
  guaranteed release, and sanitized `concurrency_limited` failures before any HTTP attempt.
- Corrected public `health` to process liveness and added public `ready` for loaded-model readiness.
- Added `LOCAL_LLM_MAX_CONCURRENCY=1` and `LOCAL_LLM_QUEUE_TIMEOUT_SECONDS=60`, including
  configuration and deployment-guard validation.
- Kept completion to one authenticated HTTP attempt with no automatic retry or provider framework.
- Bumped package, frontend, runtime, API contract, and wheel metadata to `0.10.0`.

**Decisions**

- A second in-process caller waits for at most 60 seconds instead of failing immediately.
- Queue waiting and HTTP transport use separate budgets; queue time is excluded from provider time
  and included in total operation time.
- The generic `LanguageModel` port remains completion-only. Liveness and readiness remain concrete
  llama.cpp deployment probes.
- Empty visible completion text remains valid provider output because the accepted Qwen envelope
  can contain it.
- Retry eligibility and `Retry-After` are metadata only; WP2 performs no retry.

**Verification**

- The full local suite passed 370 tests with the one opt-in real-node test skipped.
- Deterministic threaded tests prove one active delegate call, bounded queueing, zero provider calls
  on queue expiry, and permit release after expected and unexpected failures.
- Ruff lint/format, Pyright with Python 3.12, ShellCheck, Git diff checks, frontend lint/10 tests,
  and the production frontend build passed.
- Isolated source/wheel builds and inspection of the packaged AI CLI, limiter, port, and domain
  files passed for `0.10.0`.
- On 2026-07-27 the owner reran the packaged liveness, readiness, completion, opt-in UNO Q, and
  platform checks on RUBIK and confirmed they passed.

**Security/privacy**

- Liveness accepts the documented loading `503` without reading or logging its body.
- Readiness and completion preserve sanitized failures; tests exclude sentinel keys, prompts,
  provider bodies, authorization values, and GGUF paths.
- No Gmail, prompt, persistence, Langfuse, scheduler, service, migration, or dashboard behavior was
  added.

**Known limitations**

- The limiter coordinates only callers sharing one model instance inside one process. UNO Q's
  server-side `--parallel 1` remains the cross-process limit.
- HTTPX applies the completion timeout to its HTTP phases; it is not combined with queue waiting
  into one wall-clock deadline.

**Next**

- Preserve the accepted one-slot, one-attempt provider contract in later feature work.

**Owner action required**

- None.

## Combined WP3/WP5 implementation handoff

Release `0.11.0` implements the minimum observable email-triage foundation above WP2:

- one synthetic fixture enters the first real `modules/email_triage` use case;
- a production-labelled Langfuse chat prompt is resolved through a narrow port with the packaged
  `1.0.0` manifest as a permanent fallback;
- the existing one-slot llama.cpp path receives a strict provider-neutral JSON schema and disabled
  reasoning request;
- exact `label` and `reason` JSON is decoded without repair;
- one deterministic Langfuse trace contains root `classify-email` and child generation
  `generate-triage-decision`;
- only `prompt-publish` may create and promote a remote prompt version.

The detailed implementation and acceptance record is
[`stage-6a-wp3-wp5-handoff.md`](stage-6a-wp3-wp5-handoff.md). WP4 quality evaluation remains
deferred. WP6 may add read-only Gmail retrieval, but real Gmail-to-model execution remains blocked
until privacy and minimum-quality decisions are explicitly revisited. WP2 and the combined WP3/WP5
slice were accepted on RUBIK on 2026-07-27.

## Work Package 6 implementation handoff

Release `0.12.0` implements bounded read-only Gmail retrieval:

- pure `EmailSource` request, document, cursor, batch, and failure contracts;
- a GET-only Gmail adapter with owner-supplied queries, three-page and 25-message bounds, full MIME
  retrieval, response/message/text caps, and one attempt per API call;
- conservative plain-text/HTML normalization that ignores attachments and removes standard quoted
  history, signatures, tracking markup, duplicate lines, and excess whitespace;
- Desktop OAuth authorization through a fixed SSH-loopback-compatible listener, exact
  `gmail.readonly` authority, atomic mode-`0600` token refresh, and sanitized invalid-grant
  behavior;
- a separate `email_triage_cli` that presents trusted sender/subject metadata and normalization
  evidence without printing bodies or exposing raw queries in logs;
- no model call, Langfuse trace, persistence, service, timer, migration, dashboard surface, or
  mailbox mutation.

The detailed implementation, security, deployment, rollback, and acceptance record is
[`stage-6a-wp6-handoff.md`](stage-6a-wp6-handoff.md). WP6 was accepted on RUBIK and personal Gmail
on 2026-07-28.

## Work Package 7 acceptance handoff

Release `0.13.0` implements durable read-only triage runs:

- an explicit, at-most-ten-message Gmail query enters the existing email-triage feature module;
- prompt resolution is separated from inference so the exact versioned evaluation identity can be
  transactionally reserved before contacting UNO Q;
- migration `006_email_triage_runs` stores run, item, evaluation, attempt, decision-hash, label,
  usage, timing, trace, and categorized failure evidence without copied email content;
- identical successful evaluations are reused, while `--new-attempt` creates another separately
  auditable inference;
- real-Gmail Langfuse traces use a dedicated redacted payload and preserve the exact prompt link,
  model, usage, timing, stable root span, and one child generation;
- the manual CLI exposes live recommendations plus bounded evidence history and never mutates
  Gmail.

The detailed deployment, rollback, and acceptance record is
[`stage-6a-wp7-handoff.md`](stage-6a-wp7-handoff.md). WP7 was accepted on RUBIK, personal Gmail,
UNO Q, and Langfuse Cloud on 2026-07-28. WP4 quality evaluation remains deferred, and WP8 owns any
broader operator review surface.
