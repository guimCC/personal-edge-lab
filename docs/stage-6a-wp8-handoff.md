# Stage 6A Work Package 8 handoff

**Release:** `0.14.0`
**Status:** Implemented locally; RUBIK acceptance pending

## Delivered

- Added pure protected-review contracts plus narrow ports for bounded run evidence, exact internal
  item references, and one exact Gmail-message read.
- Reused migration `006_email_triage_runs`; no schema change was added. Public run/detail responses
  expose decision hash and reason length but never Gmail IDs or reason text.
- Extended the Gmail adapter with one exact `messages.get?format=full` request. It performs no list,
  retry, attachment download, mutation, model call, or Langfuse call.
- Reused the canonical WP7 conversion to recompute the normalized hash, canonical model-input hash,
  message fingerprint, and 1,600-character input length. Changed or unverifiable content is never
  associated with a stored recommendation.
- Added authenticated, feature-gated list, detail, and item-review API routes with bounded filters,
  sanitized failures, and no-store/no-cache responses.
- Added the feature-gated `#email-triage` dashboard workspace with run/item filters, explicit
  recommendation language, and `Gmail labels applied: none`.
- Added an explicit private-content action. Sender, subject, model-visible content, and normalized
  remainder are rendered as text and kept only in component memory.
- Moved shared Gmail credential validation into API/CLI composition and changed the canonical token
  path to the mode-`0700` `secrets/gmail-oauth` directory. The API service can write only that
  directory and `data`.

## Privacy and security contract

- Private email content is never prefetched, periodically refreshed, persisted, logged, traced,
  placed in browser storage, or cached through React Query.
- Private content is cleared on close, item/run/filter change, workspace change, logout,
  authentication loss, or component unmount.
- The protected review endpoints return 404 while disabled and require the existing owner session
  while enabled.
- `API_AUTH_ENABLED=true` and `GMAIL_READ_ENABLED=true` are required.
  `GMAIL_TRIAGE_ENABLED`, `LOCAL_LLM_ENABLED`, and `LANGFUSE_ENABLED` are not.
- The dashboard cannot run triage, capture feedback, schedule work, notify Telegram, or change
  Gmail state.

## Local verification

- The complete Python suite passed 568 tests with one opt-in UNO Q live test skipped.
- Ruff lint and format, Pyright, ShellCheck, frontend lint and type checking, all 13 frontend tests,
  and the production frontend build passed.
- Isolated source and `0.14.0` wheel builds passed; wheel inspection confirmed the review domain,
  ports, use case, shared Gmail configuration, Gmail adapter, SQLite adapter, and dashboard assets.
- The in-app browser verified desktop and mobile layouts, disabled automatic private-content
  loading, explicit loading, collapsed normalized remainder, recommendation/no-Gmail-change
  language, and immediate close-and-clear behavior using synthetic preview evidence.
- RUBIK evidence is not inferred from these local results.

## RUBIK acceptance checklist

1. Create `secrets/gmail-oauth` as the owner with mode `0700`, copy the accepted token into it with
   mode `0600`, update `GMAIL_TOKEN_FILE`, and retain the old copy.
2. Deploy with `GMAIL_TRIAGE_REVIEW_ENABLED=false`; confirm navigation is absent and endpoints are
   sanitized 404 responses with no-store headers.
3. Enable review with API authentication and Gmail read enabled, deploy again, and confirm the API
   unit can write only `data` and the dedicated OAuth directory.
4. Inspect accepted successful, reused, failed, and interrupted WP7 runs.
5. Explicitly load one reviewable item and compare sender, subject, model-visible content,
   normalized remainder, and stored label with Gmail and the original CLI result.
6. Confirm hash matching, inert text rendering, no-store headers, and content clearing after close
   and logout.
7. Confirm Gmail remains unchanged and private content is absent from SQLite, normal logs,
   Langfuse, and browser storage.
8. Rerun Gmail, AI, API, collector, evaluator, Telegram, dashboard, AC, SQLite, UNO Q, and firewall
   checks.
9. Record observed acceptance here, then remove the old token copy only through an explicit owner
   action.

## Rollback

Set `GMAIL_TRIAGE_REVIEW_ENABLED=false`, reinstall the retained `0.13.0` wheel, restore the prior
API unit, and restart the API. Keep the canonical token path; it remains compatible with the CLI.
No database, Gmail, trace, or prompt rollback exists.

## Deferred

- Feedback and corrected labels.
- Quality evaluation and replacement of the provisional taxonomy.
- Scheduled shadow runs.
- Telegram review or notifications.
- Gmail label application or any other mailbox write.
