# Stage 6A WP8.1 Handoff

**Release:** `0.15.0`
**Status:** Implemented locally; RUBIK acceptance pending

## Delivered

- Migration `007_email_triage_messages` adds one durable record per triaged Gmail message,
  immutable normalized-content snapshots, exact evaluation/content links, stored query text, and
  complete successful recommendation reasons.
- `TriageMailboxBatch` persists every decoded message before inference. Reuse does not duplicate
  the message; forced successes update its latest recommendation; later failures retain that
  recommendation while exposing the current issue.
- The authenticated message list/detail API uses opaque local IDs, no-store responses, bounded
  cursor pagination, and no Gmail call. Run list/detail APIs remain for Diagnostics.
- The dashboard defaults to individual emails and places run/attempt evidence under Diagnostics.
  It renders content only as text, fetches bodies only after a row is opened, and clears detail
  content from query/component memory.
- `reset-development-data` requires an exact destructive confirmation, refuses unfinished work,
  creates a mode-`0600` SQLite backup, and deletes only email-triage rows.
- `EMAIL_TRIAGE_WORKSPACE_ENABLED` is canonical. `GMAIL_TRIAGE_REVIEW_ENABLED` remains a deprecated
  compatibility fallback for this release.

## Privacy and safety

Authorized local SQLite and backups contain query text, sender, subject, bounded normalized body,
exact model input, label, and reason. Normal logs and real-Gmail Langfuse traces remain redacted.
Gmail IDs are internal and never returned by the message API. Raw MIME, attachments, OAuth/LLM
credentials, authorization headers, provider bodies, and GGUF paths are not persisted.

The workspace cannot invoke Gmail, UNO Q, Langfuse, Telegram, or a scheduler and cannot modify
Gmail. The API service now needs write access only to `data`.

## RUBIK acceptance

1. Deploy disabled and verify migration 007, SQLite integrity, owner-only backup permissions,
   absent navigation, and message-endpoint 404.
2. Run the explicitly confirmed development reset and verify its backup plus preservation of every
   non-triage table.
3. Enable the workspace, run a bounded three-message manual triage, and inspect the Emails view.
4. Open all three messages and verify stored content and recommendations without Gmail calls.
5. Repeat for reuse, then force one new attempt; verify one row per email and complete Diagnostics
   history.
6. Verify Gmail is unchanged; local content is present in SQLite/backups and absent from logs,
   Langfuse, browser storage, URLs, and provider errors.
7. Re-run Gmail, AI, tracing, API, collector, evaluator, Telegram, dashboard, AC, SQLite, UNO Q,
   and firewall checks.

Record only observed acceptance evidence here. Do not mark accepted from local tests.

## Local verification

- 582 Python tests passed; the single opt-in live UNO Q test was skipped.
- Ruff lint/format, Pyright, ShellCheck, 13 frontend tests, frontend lint/typecheck, and the
  production dashboard build passed.
- Isolated wheel/source builds and wheel-content inspection passed for `0.15.0`.
- Desktop and mobile preview checks confirmed the email-first default, persisted detail loading,
  content clearing, and separate Diagnostics view.
- Migration tests cover an existing populated WP7 database; reset tests cover backup permissions,
  non-triage preservation, unfinished-work refusal, and transactional rollback.

## Rollback

Disable `EMAIL_TRIAGE_WORKSPACE_ENABLED`, reinstall `0.14.0`, and restore its API unit. Migration
007 remains inert; no destructive database, Gmail, trace, prompt, or mailbox rollback is required.
