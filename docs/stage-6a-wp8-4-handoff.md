# Stage 6A WP8.4 handoff — Resumable historical backfill

**Release:** `0.16.1`

WP8.4 adds one manual, resumable parent job for received Gmail from the previous twelve months.
The cutoff is frozen at job creation. Inbox and archived received mail are included; Sent, Drafts,
Spam, Trash, and Chats are excluded.

Each operator step discovers at most one page of IDs and processes at most ten messages through the
accepted WP7/WP8 pipeline. Accepted evaluations are reused without another provider request or
trace. Failures and interruptions are durable and require the explicit `--retry-failures` option.
There is no scheduler, service, Gmail mutation, automatic notification, or prompt change.

## RUBIK acceptance

1. Deploy with `GMAIL_TRIAGE_BACKFILL_ENABLED=false`; verify migration
   `010_email_triage_backfill` and `PRAGMA integrity_check`.
2. Enable Gmail read, Gmail triage, the local model, and the backfill gate. Keep Langfuse optional.
3. Run `backfill-start --months 12` and record the returned job ID and frozen range.
4. Run one step with `--max-items 3`; confirm the dashboard shows progress and the processed emails
   enter the normal message workspace and feedback queue.
5. Interrupt a later step, inspect durable status, and resume. Confirm completed work survives.
6. Repeat a processed identity and confirm reuse causes no second UNO Q request or trace.
7. Exercise one explicit `--retry-failures` step only if a controlled failure exists.
8. Confirm Gmail state is unchanged and query text, Gmail IDs, page cursors, sender, subject, body,
   reason, credentials, and provider bodies are absent from normal logs.
9. Continue the full twelve-month pass only through owner-triggered bounded steps.

Rollback disables `GMAIL_TRIAGE_BACKFILL_ENABLED` and reinstalls `0.16.0`. Migration 010 and any
completed evidence remain inert; no destructive downgrade or Gmail rollback is required.
