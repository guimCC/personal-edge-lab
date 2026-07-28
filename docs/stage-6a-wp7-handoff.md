# Stage 6A Work Package 7 handoff

**Release:** `0.13.0`
**Status:** Accepted on RUBIK, personal Gmail, UNO Q, and Langfuse Cloud on 2026-07-28

## Delivered

- Added the bounded `TriageMailboxBatch` use case connecting the accepted Gmail source, packaged or
  managed prompt, queued llama.cpp model, strict decision decoder, trace sink, and evidence
  repository.
- Added prepared classification so prompt identity is known before transactional evaluation
  reservation. The compatible synthetic `classify()` entry point remains unchanged.
- Added SQLite migration `006_email_triage_runs` with explicit run, item, evaluation, and attempt
  lifecycles. Successful identities are reused; `--new-attempt` creates a distinct auditable
  attempt; concurrent identical work performs no duplicate inference.
- Added partial-result continuation, source and inference failure evidence, a 300-second stale-work
  recovery boundary, and graceful `SIGINT`/`SIGTERM` handling between items.
- Added `triage`, `runs`, and `show` commands to the existing email-triage CLI. The live command
  prints trusted sender/subject plus label/reason; durable history is evidence-only.
- Added a dedicated redacted Gmail trace payload. Each new inference retains the stable
  `classify-email` root and `generate-triage-decision` generation plus exact managed-prompt linking.

## Privacy and safety

- Gmail operations remain GET-only under `gmail.readonly`; the process exposes no label, modify,
  send, archive, trash, or mark-read operation.
- SQLite stores Gmail IDs, hashes, lengths, cleanup flags, versions, label, decision hash, reason
  length, timing, usage, trace availability, and failure categories. It does not store the query,
  sender, subject, body, compiled prompt, raw model output, or reason.
- Real-Gmail traces contain only hashes, lengths, cleanup evidence, label, versions, timing, and
  usage. Synthetic traces retain their explicitly authorized full-content behavior.
- There are no automatic Gmail or inference retries. Trace failure never invalidates inference.

## Local verification

- The full Python suite passed 556 tests with the one opt-in UNO Q live test skipped.
- Ruff lint/format, Pyright with Python 3.12, ShellCheck, Git whitespace checks, and architecture
  boundaries passed.
- Transactional repository and use-case tests cover successful reuse, explicit new attempts,
  concurrent reservation, partial Gmail/model failures, stale recovery, graceful interruption,
  bounded history, and content-free persistence.
- Trace and redaction tests prove real sender, subject, message, compiled prompt, raw model output,
  and reason do not enter the Gmail trace record or Langfuse payload.
- Frontend lint, 10 tests, and the production build passed without adding an operator UI.
- Isolated source and `0.13.0` wheel builds passed. Wheel inspection confirmed the new domain,
  repository port, batch use case, SQLite adapter, CLI, migration, dashboard assets, and release
  metadata. A clean environment installed and imported the wheel successfully.

## RUBIK acceptance

- Release `0.13.0` deployed first with Gmail triage disabled, then with Gmail read, local inference,
  and Gmail triage enabled. Migration `006_email_triage_runs` was present and SQLite integrity
  returned `ok`.
- Run `366cfdd6ca96441cb11e0ad135276344` processed three normalizable messages sequentially with
  three successful recommendations, no item failures, three redacted traces, and
  `Gmail changes: none`.
- The owner repeated the exact batch and confirmed all three identities were reused quickly without
  another UNO Q call or Langfuse trace.
- An explicit new attempt created a separately auditable inference and distinct redacted trace.
  Bounded `runs` and exact `show` output retained fingerprints, label, prompt/profile/model,
  usage, timing, status, and trace evidence without durable message content or reason text.
- Run `3491124bf8254dbdb6ddd8bfe1a169f0` received one `SIGINT`, preserved one completed inference,
  marked two pending items interrupted, and recorded the run as interrupted. A separate powered-off
  UNO Q run recorded sanitized connection failures plus interruption evidence and remained isolated
  from Gmail and the rest of the platform.
- The owner audited Gmail traces and confirmed one `classify-email` root plus one
  `generate-triage-decision` generation, the exact managed-prompt link, tags, hashes, lengths,
  cleanup evidence, label, usage, and timing. Real query, sender, subject, body, compiled prompt,
  raw model output, and reason were absent.
- Gmail read state, labels, archive state, and mailbox contents remained unchanged. The owner
  confirmed the API, collector, alert evaluator, Telegram, dashboard, AC, Gmail retrieval, UNO Q
  firewall, and existing platform checks remained healthy.
- Final liveness, readiness, authenticated completion, synthetic triage, managed prompt and trace,
  migration, and SQLite integrity checks passed.

## Acceptance findings

- Real mailbox calls took approximately 21 to 113 seconds. RUBIK therefore uses
  `LOCAL_LLM_TIMEOUT_SECONDS=180`; the prior 60-second budget caused false timeouts on valid
  messages.
- One message in a ten-message Gmail diagnostic batch returned the intentionally sanitized
  `invalid_message` item failure while nine messages normalized successfully.
- The provisional taxonomy produced questionable recommendations and some reasons reached the
  160-character schema boundary. WP7 accepts architecture and operational behavior only; it makes
  no classification-quality claim.

## Rollback

Set `GMAIL_TRIAGE_ENABLED=false`, reinstall the retained `0.12.0` wheel, and restart only existing
processes that received the package. Migration 006 is additive and remains inert under `0.12.0`;
do not destructively remove it. No Gmail, Langfuse prompt, or mailbox rollback is required.
