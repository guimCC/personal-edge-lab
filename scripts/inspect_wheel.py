"""Verify that a built wheel contains every runtime composition root and dashboard asset."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile

REQUIRED_FILES = (
    "personal_edge_lab/apps/api/static/dashboard/index.html",
    "personal_edge_lab/apps/api/static/dashboard/.vite/manifest.json",
    "personal_edge_lab/apps/alert_evaluator/__main__.py",
    "personal_edge_lab/apps/ai_cli/__main__.py",
    "personal_edge_lab/apps/ai_cli/config.py",
    "personal_edge_lab/apps/ai_cli/fixtures/synthetic-invoice.json",
    "personal_edge_lab/apps/ai_cli/fixtures/taxonomy-v2-core.json",
    "personal_edge_lab/apps/email_triage_cli/__main__.py",
    "personal_edge_lab/apps/email_triage_cli/config.py",
    "personal_edge_lab/apps/gmail_configuration.py",
    "personal_edge_lab/application/ports/email.py",
    "personal_edge_lab/application/ports/email_triage_runs.py",
    "personal_edge_lab/application/ports/email_triage_review.py",
    "personal_edge_lab/application/ports/email_triage_messages.py",
    "personal_edge_lab/application/ports/email_triage_feedback.py",
    "personal_edge_lab/application/ports/email_triage_backfill.py",
    "personal_edge_lab/domain/email.py",
    "personal_edge_lab/domain/email_triage.py",
    "personal_edge_lab/domain/email_triage_runs.py",
    "personal_edge_lab/domain/email_triage_review.py",
    "personal_edge_lab/domain/email_triage_messages.py",
    "personal_edge_lab/domain/email_triage_feedback.py",
    "personal_edge_lab/domain/email_triage_backfill.py",
    "personal_edge_lab/infrastructure/gmail/client.py",
    "personal_edge_lab/infrastructure/gmail/normalization.py",
    "personal_edge_lab/infrastructure/gmail/oauth.py",
    "personal_edge_lab/infrastructure/ai/concurrency.py",
    "personal_edge_lab/infrastructure/ai/triage_decoder.py",
    "personal_edge_lab/infrastructure/observability/langfuse.py",
    "personal_edge_lab/infrastructure/persistence/sqlite/email_triage.py",
    "personal_edge_lab/infrastructure/persistence/sqlite/email_triage_reset.py",
    "personal_edge_lab/infrastructure/persistence/sqlite/email_triage_backfill.py",
    "personal_edge_lab/modules/email_triage/prompt.json",
    "personal_edge_lab/modules/email_triage/batch.py",
    "personal_edge_lab/modules/email_triage/input.py",
    "personal_edge_lab/modules/email_triage/review.py",
    "personal_edge_lab/modules/email_triage/rules.py",
    "personal_edge_lab/modules/email_triage/service.py",
    "personal_edge_lab/modules/email_triage/feedback.py",
    "personal_edge_lab/modules/email_triage/backfill.py",
    "personal_edge_lab/apps/telegram_bot/__main__.py",
    "personal_edge_lab/apps/telegram_bot/owner_bot.py",
    "personal_edge_lab/apps/telegram_bot/capabilities/ac.py",
    "personal_edge_lab/apps/telegram_bot/capabilities/status.py",
    "personal_edge_lab/apps/telegram_bot/capabilities/email_triage.py",
    "personal_edge_lab/apps/telegram_cli/__main__.py",
    "personal_edge_lab/apps/telemetry_collector/__main__.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    arguments = parser.parse_args()
    with ZipFile(arguments.wheel) as archive:
        names = set(archive.namelist())
    missing = [name for name in REQUIRED_FILES if name not in names]
    if missing:
        parser.error(f"wheel is missing runtime files: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
