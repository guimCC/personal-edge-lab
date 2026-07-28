# Telemetry retention policy

## Current decision

Raw temperature readings are retained for 365 days. This preserves seasonal analysis while placing
a predictable bound on SQLite size, backups, integrity checks, and deployment copies.

At the current 15-second cadence this is approximately 2.1 million rows per device per year.
Command audit, authentication throttle state, collector runtime status, alert incidents, and alert
transitions are not included in automatic telemetry retention.

Email-triage migration-006 records retain evidence only: internal Gmail identifiers, hashes,
lengths, versions, proposed label, usage, timing, trace availability, and categorized outcomes.
They do not retain query text, sender, subject, body, prompt, model output, or reason text. WP8
private review content is fetched on demand, held only in browser component memory, and is not a
retained data class.

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
