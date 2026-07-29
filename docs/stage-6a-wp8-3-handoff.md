# Stage 6A WP8.3 handoff — Owner feedback and redacted dataset

**Release:** `0.16.0`
**Status:** Implemented locally; RUBIK acceptance pending

## Delivered

- Migration `009_email_triage_feedback` stores append-only, per-message feedback versions tied to
  the exact successful recommendation attempt.
- The shared `RecordTriageFeedback` use case supports `confirm`, `correct`, and `dismiss` from both
  the protected dashboard and owner-only Telegram bot.
- SQLite remains the authoritative private dataset. It retains the email, recommendation, reason,
  and every feedback event inside the existing owner-only database and backups.
- Langfuse dataset `personal-edge-lab/email-triage-feedback` receives a stable item per message.
  Confirm/correct makes the item active with an expected label; dismiss archives it.
- Existing redacted real-Gmail traces receive categorical `owner-label-verdict` and
  `owner-expected-label` scores when the reviewed attempt has a trace.
- Langfuse publication is best-effort. Local feedback succeeds first, publication errors are
  sanitized, and pending/unavailable records remain retriable.
- Telegram adds a manual `/triage_review` queue with bounded inline callbacks, stale-view
  protection, explicit correction labels, and no automatic notification.

## Privacy and behavior

- Langfuse receives hashes, character lengths, normalization/cleanup/truncation evidence, labels,
  feedback source/version, and release metadata only.
- Sender, subject, email body, exact model input, reason, Gmail IDs, credentials, authorization
  headers, and provider bodies remain absent from Langfuse feedback payloads and normal logs.
- The protected dashboard and private owner Telegram chat may transiently display authorized
  content. Neither surface changes Gmail.
- Feedback does not trigger inference, create a new trace, change a prompt, or claim model quality.

## Acceptance

1. Deploy with `EMAIL_TRIAGE_FEEDBACK_ENABLED=false`.
2. Verify migration `009_email_triage_feedback` and `PRAGMA integrity_check`.
3. Enable the authenticated workspace, feedback, Telegram bot, and Langfuse.
4. Confirm one recommendation, correct one to another taxonomy-v2 label, and dismiss one.
5. Repeat one operation from `/triage_review` and verify stale callbacks cannot overwrite newer
   feedback.
6. Inspect the Langfuse dataset and linked trace scores; confirm the payload is redacted.
7. Temporarily make Langfuse unavailable and prove local feedback survives with retryable sync
   evidence.
8. Confirm Gmail is unchanged and existing platform, AI, Gmail, tracing, dashboard, Telegram,
   SQLite, UNO Q, and firewall checks remain healthy.

## Rollback

Set `EMAIL_TRIAGE_FEEDBACK_ENABLED=false` and reinstall `0.15.1`. Migration 009 and its data remain
inert. No Gmail, prompt, trace, or destructive database rollback is required.
