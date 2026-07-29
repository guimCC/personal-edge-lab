"""Small transactional SQLite migration runner."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from personal_edge_lab.infrastructure.persistence.sqlite.connection import (
    DEFAULT_TIMEOUT_SECONDS,
    open_connection,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    statements: Sequence[str]


MIGRATIONS = (
    Migration(
        version="001_initial",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS temperature_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                received_at_utc TEXT NOT NULL,
                estimated_sample_at_utc TEXT NOT NULL,
                temperature_c REAL NOT NULL,
                raw_adc INTEGER NOT NULL,
                age_ms INTEGER NOT NULL,
                sample_interval_ms INTEGER NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_temperature_device_received
            ON temperature_readings (device_id, received_at_utc)
            """,
            """
            CREATE TABLE IF NOT EXISTS ac_command_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                command_type TEXT NOT NULL,
                command_payload_json TEXT NOT NULL,
                requested_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
                outcome TEXT NOT NULL,
                http_status INTEGER,
                response_body TEXT,
                error_category TEXT,
                error_message TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ac_command_device_requested
            ON ac_command_audit (device_id, requested_at_utc)
            """,
        ),
    ),
    Migration(
        version="002_collector_runtime_status",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS collector_runtime_status (
                device_id TEXT PRIMARY KEY,
                process_started_at_utc TEXT NOT NULL,
                heartbeat_at_utc TEXT NOT NULL,
                stopped_at_utc TEXT,
                last_attempt_at_utc TEXT,
                last_attempt_outcome TEXT,
                last_success_at_utc TEXT,
                last_failure_at_utc TEXT,
                last_failure_category TEXT,
                last_failure_message TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0
                    CHECK (consecutive_failures >= 0),
                CHECK (
                    last_attempt_outcome IS NULL
                    OR last_attempt_outcome IN ('success', 'failure')
                )
            )
            """,
        ),
    ),
    Migration(
        version="003_authenticated_control",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                csrf_token TEXT NOT NULL,
                credential_fingerprint TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                last_seen_at_utc TEXT NOT NULL,
                idle_expires_at_utc TEXT NOT NULL,
                absolute_expires_at_utc TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
            ON auth_sessions (idle_expires_at_utc, absolute_expires_at_utc)
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_login_throttle (
                actor_id TEXT PRIMARY KEY,
                window_started_at_utc TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL
                    CHECK (failed_attempts >= 0),
                blocked_until_utc TEXT
            )
            """,
            "ALTER TABLE ac_command_audit ADD COLUMN actor_id TEXT",
            """
            ALTER TABLE ac_command_audit
            ADD COLUMN request_source TEXT NOT NULL DEFAULT 'local_cli'
            """,
            "ALTER TABLE ac_command_audit ADD COLUMN idempotency_key TEXT",
            "ALTER TABLE ac_command_audit ADD COLUMN request_fingerprint TEXT",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ac_command_actor_idempotency
            ON ac_command_audit (actor_id, idempotency_key)
            WHERE actor_id IS NOT NULL AND idempotency_key IS NOT NULL
            """,
            """
            CREATE TABLE IF NOT EXISTS ac_command_device_locks (
                device_id TEXT PRIMARY KEY,
                command_id INTEGER NOT NULL,
                lease_expires_at_utc TEXT NOT NULL,
                FOREIGN KEY (command_id) REFERENCES ac_command_audit (id)
            )
            """,
        ),
    ),
    Migration(
        version="004_operational_alerts",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS alert_runtime_status (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                last_started_at_utc TEXT NOT NULL,
                last_finished_at_utc TEXT,
                last_outcome TEXT,
                last_error_category TEXT,
                last_error_message TEXT,
                CHECK (last_outcome IS NULL OR last_outcome IN ('success', 'failure'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL
                    CHECK (alert_type IN ('telemetry_stale', 'edge_unavailable')),
                status TEXT NOT NULL
                    CHECK (status IN ('active', 'recovered')),
                suspect_started_at_utc TEXT NOT NULL,
                alerting_at_utc TEXT NOT NULL,
                recovered_at_utc TEXT,
                last_observed_at_utc TEXT NOT NULL,
                evidence_category TEXT NOT NULL,
                evidence_message TEXT NOT NULL,
                CHECK (
                    recovered_at_utc IS NULL
                    OR recovered_at_utc >= alerting_at_utc
                ),
                CHECK (last_observed_at_utc >= suspect_started_at_utc)
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_one_active_incident
            ON alert_incidents (device_id, alert_type)
            WHERE status = 'active'
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_alert_incident_device_newest
            ON alert_incidents (device_id, id DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_states (
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL
                    CHECK (alert_type IN ('telemetry_stale', 'edge_unavailable')),
                lifecycle TEXT NOT NULL
                    CHECK (lifecycle IN ('healthy', 'suspect', 'alerting', 'recovered')),
                suspect_started_at_utc TEXT,
                active_incident_id INTEGER,
                recovered_at_utc TEXT,
                recovery_display_until_utc TEXT,
                last_observed_at_utc TEXT NOT NULL,
                evidence_category TEXT NOT NULL,
                evidence_message TEXT NOT NULL,
                PRIMARY KEY (device_id, alert_type),
                FOREIGN KEY (active_incident_id) REFERENCES alert_incidents (id),
                CHECK (
                    lifecycle != 'alerting'
                    OR active_incident_id IS NOT NULL
                ),
                CHECK (
                    lifecycle != 'suspect'
                    OR suspect_started_at_utc IS NOT NULL
                ),
                CHECK (
                    lifecycle != 'recovered'
                    OR (
                        recovered_at_utc IS NOT NULL
                        AND recovery_display_until_utc IS NOT NULL
                    )
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_transition_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER,
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL
                    CHECK (alert_type IN ('telemetry_stale', 'edge_unavailable')),
                from_state TEXT NOT NULL
                    CHECK (from_state IN ('healthy', 'suspect', 'alerting', 'recovered')),
                to_state TEXT NOT NULL
                    CHECK (to_state IN ('healthy', 'suspect', 'alerting', 'recovered')),
                transitioned_at_utc TEXT NOT NULL,
                evidence_category TEXT NOT NULL,
                evidence_message TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES alert_incidents (id),
                CHECK (from_state != to_state)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_alert_transition_device_newest
            ON alert_transition_events (device_id, id DESC)
            """,
        ),
    ),
    Migration(
        version="005_notification_outbox",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS notification_policy (
                channel TEXT NOT NULL,
                recipient TEXT NOT NULL,
                topic TEXT NOT NULL,
                mode TEXT NOT NULL
                    CHECK (mode IN ('enabled', 'paused_until', 'paused_indefinitely')),
                paused_until_utc TEXT,
                changed_at_utc TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                PRIMARY KEY (channel, recipient, topic),
                CHECK (
                    (mode = 'paused_until' AND paused_until_utc IS NOT NULL)
                    OR (mode != 'paused_until' AND paused_until_utc IS NULL)
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                channel TEXT NOT NULL,
                recipient TEXT NOT NULL,
                topic TEXT NOT NULL,
                event_type TEXT NOT NULL
                    CHECK (
                        event_type IN (
                            'operational_alert_started',
                            'operational_alert_recovered'
                        )
                    ),
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL
                    CHECK (alert_type IN ('telemetry_stale', 'edge_unavailable')),
                incident_id INTEGER NOT NULL,
                transition_id INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                occurred_at_utc TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'pending', 'leased', 'delivered', 'suppressed', 'expired'
                        )
                    ),
                attempt_count INTEGER NOT NULL DEFAULT 0
                    CHECK (attempt_count >= 0),
                coalesced_count INTEGER NOT NULL DEFAULT 1
                    CHECK (coalesced_count >= 1),
                next_attempt_at_utc TEXT NOT NULL,
                leased_until_utc TEXT,
                last_attempt_at_utc TEXT,
                delivered_at_utc TEXT,
                external_message_id TEXT,
                last_error_category TEXT,
                last_error_message TEXT,
                FOREIGN KEY (incident_id) REFERENCES alert_incidents (id),
                FOREIGN KEY (transition_id) REFERENCES alert_transition_events (id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_notification_outbox_due
            ON notification_outbox (status, next_attempt_at_utc, id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_notification_outbox_alert_flapping
            ON notification_outbox (
                channel, recipient, topic, device_id, alert_type, occurred_at_utc
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notification_delivery_runtime (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                last_started_at_utc TEXT NOT NULL,
                last_finished_at_utc TEXT,
                last_outcome TEXT
                    CHECK (last_outcome IS NULL OR last_outcome IN ('success', 'failure')),
                delivered_count INTEGER NOT NULL DEFAULT 0
                    CHECK (delivered_count >= 0),
                failed_count INTEGER NOT NULL DEFAULT 0
                    CHECK (failed_count >= 0),
                last_error_category TEXT,
                last_error_message TEXT
            )
            """,
        ),
    ),
    Migration(
        version="006_email_triage_runs",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS email_triage_runs (
                run_id TEXT PRIMARY KEY,
                operation_id TEXT NOT NULL UNIQUE,
                query_sha256 TEXT NOT NULL,
                requested_limit INTEGER NOT NULL
                    CHECK (requested_limit BETWEEN 1 AND 10),
                force_new_attempt INTEGER NOT NULL
                    CHECK (force_new_attempt IN (0, 1)),
                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'requested', 'retrieving', 'classifying',
                            'completed_with_results', 'completed_with_failures',
                            'failed_before_items', 'interrupted'
                        )
                    ),
                requested_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
                document_count INTEGER NOT NULL DEFAULT 0 CHECK (document_count >= 0),
                retrieval_failure_count INTEGER NOT NULL DEFAULT 0
                    CHECK (retrieval_failure_count >= 0),
                pages_fetched INTEGER NOT NULL DEFAULT 0 CHECK (pages_fetched >= 0),
                api_call_count INTEGER NOT NULL DEFAULT 0 CHECK (api_call_count >= 0),
                retrieval_seconds REAL NOT NULL DEFAULT 0 CHECK (retrieval_seconds >= 0),
                has_more INTEGER NOT NULL DEFAULT 0 CHECK (has_more IN (0, 1)),
                failure_category TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_email_triage_runs_recent
            ON email_triage_runs (requested_at_utc DESC, run_id DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS email_triage_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_sha256 TEXT NOT NULL UNIQUE,
                gmail_message_id TEXT NOT NULL,
                gmail_thread_id TEXT NOT NULL,
                received_at_utc TEXT NOT NULL,
                message_fingerprint TEXT NOT NULL,
                normalized_sha256 TEXT NOT NULL,
                model_input_sha256 TEXT NOT NULL,
                sender_chars INTEGER NOT NULL CHECK (sender_chars >= 0),
                subject_chars INTEGER NOT NULL CHECK (subject_chars >= 0),
                normalized_chars INTEGER NOT NULL CHECK (normalized_chars >= 0),
                model_message_chars INTEGER NOT NULL CHECK (model_message_chars >= 0),
                original_size_bytes INTEGER NOT NULL CHECK (original_size_bytes >= 0),
                content_source TEXT NOT NULL
                    CHECK (content_source IN ('plain_text', 'html', 'empty')),
                source_truncated INTEGER NOT NULL CHECK (source_truncated IN (0, 1)),
                model_input_truncated INTEGER NOT NULL
                    CHECK (model_input_truncated IN (0, 1)),
                metadata_truncated INTEGER NOT NULL CHECK (metadata_truncated IN (0, 1)),
                cleanup_flags_json TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                taxonomy_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                generation_parameters_version TEXT NOT NULL,
                prompt_name TEXT NOT NULL,
                prompt_source TEXT NOT NULL
                    CHECK (prompt_source IN ('langfuse', 'local_fallback')),
                prompt_version TEXT NOT NULL,
                model_alias TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS email_triage_run_items (
                run_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
                gmail_message_id TEXT,
                message_fingerprint TEXT NOT NULL,
                received_at_utc TEXT,
                evaluation_id INTEGER,
                selected_attempt_id INTEGER,
                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'pending', 'classifying', 'succeeded',
                            'reused', 'failed', 'interrupted'
                        )
                    ),
                failure_category TEXT,
                recorded_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
                PRIMARY KEY (run_id, ordinal),
                FOREIGN KEY (run_id) REFERENCES email_triage_runs (run_id),
                FOREIGN KEY (evaluation_id) REFERENCES email_triage_evaluations (id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_email_triage_items_evaluation
            ON email_triage_run_items (evaluation_id, run_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS email_triage_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluation_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                item_ordinal INTEGER NOT NULL,
                operation_id TEXT NOT NULL UNIQUE,
                attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
                status TEXT NOT NULL
                    CHECK (status IN ('reserved', 'running', 'succeeded', 'failed', 'interrupted')),
                reserved_at_utc TEXT NOT NULL,
                started_at_utc TEXT,
                completed_at_utc TEXT,
                provider TEXT,
                model_alias TEXT,
                queue_wait_seconds REAL NOT NULL DEFAULT 0 CHECK (queue_wait_seconds >= 0),
                provider_seconds REAL CHECK (provider_seconds IS NULL OR provider_seconds >= 0),
                total_seconds REAL CHECK (total_seconds IS NULL OR total_seconds >= 0),
                provider_attempt_count INTEGER NOT NULL DEFAULT 1
                    CHECK (provider_attempt_count >= 1),
                retry_eligible INTEGER CHECK (retry_eligible IN (0, 1)),
                retry_after_seconds REAL
                    CHECK (retry_after_seconds IS NULL OR retry_after_seconds >= 0),
                prompt_tokens INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
                completion_tokens INTEGER
                    CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
                total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
                label TEXT
                    CHECK (
                        label IS NULL
                        OR label IN (
                            'work', 'billing', 'notification',
                            'newsletter', 'personal', 'other'
                        )
                    ),
                decision_sha256 TEXT,
                reason_chars INTEGER CHECK (reason_chars IS NULL OR reason_chars BETWEEN 1 AND 160),
                failure_category TEXT,
                trace_id TEXT,
                trace_unavailable INTEGER NOT NULL DEFAULT 1
                    CHECK (trace_unavailable IN (0, 1)),
                FOREIGN KEY (evaluation_id) REFERENCES email_triage_evaluations (id),
                FOREIGN KEY (run_id, item_ordinal)
                    REFERENCES email_triage_run_items (run_id, ordinal),
                UNIQUE (evaluation_id, attempt_number)
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_email_triage_one_active_attempt
            ON email_triage_attempts (evaluation_id)
            WHERE status IN ('reserved', 'running')
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_email_triage_attempts_run
            ON email_triage_attempts (run_id, item_ordinal, id)
            """,
        ),
    ),
    Migration(
        version="007_email_triage_messages",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS email_triage_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL UNIQUE,
                gmail_message_id TEXT NOT NULL UNIQUE,
                gmail_thread_id TEXT NOT NULL,
                received_at_utc TEXT NOT NULL,
                current_content_snapshot_id INTEGER,
                latest_run_id TEXT NOT NULL,
                latest_item_ordinal INTEGER NOT NULL CHECK (latest_item_ordinal BETWEEN 1 AND 10),
                latest_status TEXT NOT NULL
                    CHECK (
                        latest_status IN (
                            'pending', 'classifying', 'succeeded',
                            'reused', 'failed', 'interrupted'
                        )
                    ),
                latest_failure_category TEXT,
                latest_successful_attempt_id INTEGER,
                first_seen_at_utc TEXT NOT NULL,
                last_seen_at_utc TEXT NOT NULL,
                FOREIGN KEY (latest_run_id) REFERENCES email_triage_runs (run_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_email_triage_messages_recent
            ON email_triage_messages (received_at_utc DESC, record_id DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_email_triage_messages_status
            ON email_triage_messages (latest_status, received_at_utc DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS email_triage_content_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_record_id INTEGER NOT NULL,
                sender TEXT NOT NULL CHECK (length(sender) BETWEEN 1 AND 160),
                subject TEXT NOT NULL CHECK (length(subject) <= 256),
                normalized_text TEXT NOT NULL CHECK (length(normalized_text) <= 8000),
                model_input TEXT NOT NULL CHECK (length(model_input) <= 1600),
                normalized_sha256 TEXT NOT NULL,
                model_input_sha256 TEXT NOT NULL,
                original_size_bytes INTEGER NOT NULL CHECK (original_size_bytes >= 0),
                content_source TEXT NOT NULL
                    CHECK (content_source IN ('plain_text', 'html', 'empty')),
                cleanup_flags_json TEXT NOT NULL,
                source_truncated INTEGER NOT NULL CHECK (source_truncated IN (0, 1)),
                model_input_truncated INTEGER NOT NULL CHECK (model_input_truncated IN (0, 1)),
                metadata_truncated INTEGER NOT NULL CHECK (metadata_truncated IN (0, 1)),
                created_at_utc TEXT NOT NULL,
                UNIQUE (message_record_id, normalized_sha256, model_input_sha256),
                FOREIGN KEY (message_record_id) REFERENCES email_triage_messages (id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS email_triage_evaluation_content (
                evaluation_id INTEGER PRIMARY KEY,
                content_snapshot_id INTEGER NOT NULL,
                FOREIGN KEY (evaluation_id) REFERENCES email_triage_evaluations (id),
                FOREIGN KEY (content_snapshot_id) REFERENCES email_triage_content_snapshots (id)
            )
            """,
            """
            ALTER TABLE email_triage_runs ADD COLUMN query_text TEXT
            """,
            """
            ALTER TABLE email_triage_run_items ADD COLUMN message_record_id INTEGER
            """,
            """
            ALTER TABLE email_triage_attempts ADD COLUMN reason_text TEXT
                CHECK (reason_text IS NULL OR length(reason_text) BETWEEN 1 AND 160)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_email_triage_items_message
            ON email_triage_run_items (message_record_id, run_id)
            """,
        ),
    ),
    Migration(
        version="008_email_triage_taxonomy_v2",
        statements=(
            """
            ALTER TABLE email_triage_evaluations
            ADD COLUMN decision_source TEXT NOT NULL DEFAULT 'model'
                CHECK (decision_source IN ('model', 'rule'))
            """,
            """
            ALTER TABLE email_triage_evaluations ADD COLUMN rule_id TEXT
            """,
            """
            ALTER TABLE email_triage_evaluations ADD COLUMN rule_version TEXT
            """,
            """
            CREATE TABLE email_triage_attempts_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluation_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                item_ordinal INTEGER NOT NULL,
                operation_id TEXT NOT NULL UNIQUE,
                attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
                status TEXT NOT NULL
                    CHECK (status IN ('reserved', 'running', 'succeeded', 'failed', 'interrupted')),
                reserved_at_utc TEXT NOT NULL,
                started_at_utc TEXT,
                completed_at_utc TEXT,
                provider TEXT,
                model_alias TEXT,
                queue_wait_seconds REAL NOT NULL DEFAULT 0 CHECK (queue_wait_seconds >= 0),
                provider_seconds REAL CHECK (provider_seconds IS NULL OR provider_seconds >= 0),
                total_seconds REAL CHECK (total_seconds IS NULL OR total_seconds >= 0),
                provider_attempt_count INTEGER NOT NULL DEFAULT 1
                    CHECK (provider_attempt_count >= 0),
                retry_eligible INTEGER CHECK (retry_eligible IN (0, 1)),
                retry_after_seconds REAL
                    CHECK (retry_after_seconds IS NULL OR retry_after_seconds >= 0),
                prompt_tokens INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
                completion_tokens INTEGER
                    CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
                total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
                label TEXT
                    CHECK (
                        label IS NULL
                        OR label IN (
                            'mckinsey', 'education', 'job', 'personal', 'admin',
                            'notification', 'newsletter', 'slop', 'other',
                            'work', 'billing'
                        )
                    ),
                decision_sha256 TEXT,
                reason_chars INTEGER CHECK (reason_chars IS NULL OR reason_chars BETWEEN 1 AND 160),
                failure_category TEXT,
                trace_id TEXT,
                trace_unavailable INTEGER NOT NULL DEFAULT 1
                    CHECK (trace_unavailable IN (0, 1)),
                reason_text TEXT
                    CHECK (reason_text IS NULL OR length(reason_text) BETWEEN 1 AND 160),
                decision_source TEXT NOT NULL DEFAULT 'model'
                    CHECK (decision_source IN ('model', 'rule')),
                rule_id TEXT,
                rule_version TEXT,
                FOREIGN KEY (evaluation_id) REFERENCES email_triage_evaluations (id),
                FOREIGN KEY (run_id, item_ordinal)
                    REFERENCES email_triage_run_items (run_id, ordinal),
                UNIQUE (evaluation_id, attempt_number)
            )
            """,
            """
            INSERT INTO email_triage_attempts_v2 (
                id, evaluation_id, run_id, item_ordinal, operation_id,
                attempt_number, status, reserved_at_utc, started_at_utc,
                completed_at_utc, provider, model_alias, queue_wait_seconds,
                provider_seconds, total_seconds, provider_attempt_count,
                retry_eligible, retry_after_seconds, prompt_tokens,
                completion_tokens, total_tokens, label, decision_sha256,
                reason_chars, failure_category, trace_id, trace_unavailable,
                reason_text, decision_source, rule_id, rule_version
            )
            SELECT
                id, evaluation_id, run_id, item_ordinal, operation_id,
                attempt_number, status, reserved_at_utc, started_at_utc,
                completed_at_utc, provider, model_alias, queue_wait_seconds,
                provider_seconds, total_seconds, provider_attempt_count,
                retry_eligible, retry_after_seconds, prompt_tokens,
                completion_tokens, total_tokens, label, decision_sha256,
                reason_chars, failure_category, trace_id, trace_unavailable,
                reason_text, 'model', NULL, NULL
            FROM email_triage_attempts
            """,
            """
            DROP TABLE email_triage_attempts
            """,
            """
            ALTER TABLE email_triage_attempts_v2 RENAME TO email_triage_attempts
            """,
            """
            CREATE UNIQUE INDEX idx_email_triage_one_active_attempt
            ON email_triage_attempts (evaluation_id)
            WHERE status IN ('reserved', 'running')
            """,
            """
            CREATE INDEX idx_email_triage_attempts_run
            ON email_triage_attempts (run_id, item_ordinal, id)
            """,
        ),
    ),
)


def run_migrations(
    database_path: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Apply pending migrations atomically, preserving compatible existing tables."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with open_connection(database_path, timeout_seconds=timeout_seconds) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )
                """
            )
            applied = {
                str(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, applied_at_utc)
                    VALUES (?, ?)
                    """,
                    (migration.version, datetime.now(UTC).isoformat()),
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
