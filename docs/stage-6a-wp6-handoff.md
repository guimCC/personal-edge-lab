# Stage 6A Work Package 6 handoff

**Release:** `0.12.0`
**Status:** Accepted on RUBIK and personal Gmail on 2026-07-28

## Delivered

- Added pure bounded email-source values and the narrow `EmailSource.retrieve` port.
- Added a Gmail adapter restricted to `users.messages.list` and `users.messages.get` with
  `format=full`, one attempt per request, three-page and 25-message bounds, response caps, and
  sanitized transport/API failures.
- Added nested MIME decoding with plain-text preference and HTML visible-text fallback. Attachments
  are never downloaded; attachment-only, malformed, and oversized messages become explicit item
  failures.
- Added conservative removal of standard quoted history, signatures, scripts/styles, image and
  link tracking data, duplicate lines, and excessive whitespace. Normalization records truncation
  and cleanup evidence without summarizing content.
- Added Desktop OAuth authorization on `127.0.0.1:8765`, exact `gmail.readonly` scope, explicit
  replacement, bounded token refresh, and atomic owner-only token writes.
- Added `authorize` and `fetch --query ... --limit ...` under the separate
  `email_triage_cli` composition root. Fetch output includes IDs, timestamp, sender, subject, content
  source, sizes, and flags but never the normalized body.
- Added release/configuration/wheel/deployment support without a service, timer, migration,
  dashboard, model call, Langfuse trace, persistence, or Gmail mutation.

## Security and failure semantics

- Client and token files must be absolute, regular, non-symlinked, owner-owned, readable, valid
  private JSON with mode `0600`. The token must contain only the Gmail read-only scope.
- The deployment guard validates and backs up both credential files only after retrieval is
  enabled. Authorization remains available while disabled for safe bootstrap.
- OAuth credentials, authorization values, refresh tokens, raw queries, Gmail error bodies, and
  message content are excluded from errors and logs.
- Sender, subject, timestamp, and Gmail IDs are authorized only on trusted CLI stdout. Terminal
  control characters are removed before presentation.
- Connection and timeout failures retain exits `3` and `4`; configuration/input uses `2`; auth,
  permission, rate, API/protocol, and partial-message failures use `5`. Zero matches is success.
- Expired OAuth credentials receive one refresh attempt before Gmail access. Gmail API calls are
  never retried automatically.

## Local verification

- The full Python suite passed 533 tests with the one opt-in UNO Q live test skipped.
- Domain, normalization, HTTP, OAuth, configuration, CLI, redaction, and architecture tests cover
  the frozen WP6 contract.
- Ruff lint/format, Pyright with Python 3.12, ShellCheck, and Git whitespace checks passed.
- Frontend lint, 10 tests, and the production build passed without introducing a Gmail UI.
- Isolated source and `0.12.0` wheel builds passed. Wheel inspection confirmed the Gmail CLI,
  domain/port, OAuth, normalization and HTTP adapters, exact Google dependency pins, existing
  runtime surfaces, dashboard assets, and release metadata. A clean environment installed and
  imported the wheel successfully.

## RUBIK acceptance

On 2026-07-28 the owner confirmed that the documented WP6 checks passed:

- release `0.12.0` was deployed on RUBIK;
- the personal Gmail account was authorized through the Desktop OAuth and SSH loopback flow;
- the private client and token files passed the documented ownership and mode checks;
- bounded retrieval with the explicit inbox query worked for the requested small batches;
- sender, subject, timestamp, content source, length, and cleanup evidence were usable;
- normalized bodies and credentials were absent from CLI output and normal logs;
- Gmail read state, labels, archive state, and mailbox contents remained unchanged;
- the documented authorization-failure/recovery and existing-platform regression checks completed
  successfully.

No Gmail address, message ID, subject, body, OAuth value, query result, or raw command output is
recorded because those exact values were not supplied to the repository.

## Known limitations and next boundary

- The external OAuth app remains in Testing for WP6, so Google may expire its refresh token after
  seven days and require reauthorization.
- Text parts represented only by Gmail attachment IDs and actual file attachments are deliberately
  not downloaded.
- Normalization is conservative and not yet evaluated for classification quality.
- WP7 may connect this batch to the existing local triage use case only after content/trace privacy
  and minimum-quality decisions are explicitly revisited.

## Rollback

Set `GMAIL_READ_ENABLED=false`, reinstall `0.11.0`, and restart only existing processes that
received the package. The OAuth client and token files may remain inert or be revoked and removed
under owner control. No database or mailbox rollback exists.
