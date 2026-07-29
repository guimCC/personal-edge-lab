# Telemetry retention policy

## Current decision

Raw temperature readings are retained for 365 days. This preserves seasonal analysis while placing
a predictable bound on SQLite size, backups, integrity checks, and deployment copies.

At the current 15-second cadence this is approximately 2.1 million rows per device per year.
Command audit, authentication throttle state, collector runtime status, alert incidents, and alert
transitions are not included in automatic telemetry retention.

Email-triage migration-006 execution records began as evidence-only. Migrations 007–009 now retain
the owner-authorized product dataset locally: query text, sender, subject, normalized content, exact
model input, successful reason text, and append-only confirm/correct/dismiss feedback. Raw MIME,
attachments, OAuth credentials, authorization headers, and provider error bodies remain excluded.
These records currently have indefinite retention and are included in owner-only SQLite deployment
backups. Real-email Langfuse traces and feedback dataset items remain redacted.

## Enforcement

Retention cleanup is intentionally deferred until the first stored reading approaches 365 days old.
Before enabling deletion, implement it as a separately audited maintenance command or timer with:

- a dry-run count;
- deletion by `received_at_utc` in bounded transactions;
- an SQLite integrity check afterward;
- a backup taken before the first production run;
- no deletion of alert, audit, session, or runtime tables;
- a documented rollback and operator acceptance on RUBIK.

Until that maintenance capability exists, no production row is deleted automatically. Disk usage
and database age should be checked during release acceptance:

```sql
SELECT
    COUNT(*) AS readings,
    MIN(received_at_utc) AS oldest_reading,
    MAX(received_at_utc) AS newest_reading
FROM temperature_readings;
```

This decision should be revisited before adding additional high-frequency devices or long-term
aggregate storage.
