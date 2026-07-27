# Stage 6A Work Package 7 handoff

**Release:** `0.13.0`
**Status:** Implemented locally; RUBIK acceptance pending

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

1. Deploy `0.13.0` with `GMAIL_TRIAGE_ENABLED=false` and verify migration 006 plus SQLite integrity.
2. Set `GMAIL_TRIAGE_ENABLED=true` only while `GMAIL_READ_ENABLED=true` and
   `LOCAL_LLM_ENABLED=true`.
3. Run:

   ```bash
   python -m personal_edge_lab.apps.email_triage_cli triage \
     --query "in:inbox newer_than:7d" --limit 3
   python -m personal_edge_lab.apps.email_triage_cli runs --limit 20
   python -m personal_edge_lab.apps.email_triage_cli show --run-id <run-id>
   ```

4. Repeat the identical query and confirm all successful identities are reused without new UNO Q
   calls or Langfuse traces.
5. Repeat once with `--new-attempt` and confirm a distinct attempt and redacted trace.
6. Interrupt a bounded run between items and confirm completed items remain successful while
   pending items and the run are explicitly interrupted.
7. Audit logs, SQLite, and Langfuse for absence of the raw query, sender, subject, body, reason,
   compiled prompt, raw output, credentials, provider body, and GGUF path.
8. Confirm Gmail read state, labels, archive state, and mailbox contents remain unchanged, then
   rerun the existing Gmail, AI, API, collector, evaluator, Telegram, dashboard, AC, SQLite, UNO Q,
   and firewall checks.

Do not change this status to accepted until the owner confirms the observed RUBIK results.

## Rollback

Set `GMAIL_TRIAGE_ENABLED=false`, reinstall the retained `0.12.0` wheel, and restart only existing
processes that received the package. Migration 006 is additive and remains inert under `0.12.0`;
do not destructively remove it. No Gmail, Langfuse prompt, or mailbox rollback is required.
