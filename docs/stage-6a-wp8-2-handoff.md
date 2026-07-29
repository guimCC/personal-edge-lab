# Stage 6A WP8.2 handoff

**Release:** `0.15.1`
**Status:** Accepted on RUBIK on 2026-07-29

## Delivered

- Replaced the model taxonomy with `mckinsey`, `education`, `job`, `personal`, `admin`,
  `notification`, `newsletter`, `slop`, and `other`, with explicit contextual precedence.
- Added prompt/profile/taxonomy/schema version `2.0.0` under the existing managed prompt name and
  production-label workflow. The packaged prompt remains the permanent runtime fallback.
- Added an optional private, owner-only deterministic rules file supporting stable IDs, priorities,
  exact sender addresses, and boundary-safe domain/subdomain matching.
- Rule matches skip prompt lookup, UNO Q, and Langfuse; they retain no reason and persist explicit
  rule source/identity evidence.
- Added migration `008_email_triage_taxonomy_v2`, API/dashboard Rule-versus-AI presentation, the
  `rules-check` command, and the `taxonomy-v2-core` synthetic baseline command.

## Privacy and compatibility

- Private sender/domain matchers exist only in the configured mode-`0600` RUBIK JSON file and its
  owner-only deployment backup. They are not committed, logged, traced, returned by the API, or
  persisted in SQLite.
- Existing taxonomy-v1 `work` and `billing` rows remain readable history. They cannot be emitted by
  prompt v2 or selected by a new deterministic rule.
- Real Gmail Langfuse traces remain redacted. Deterministic results create no trace.

## RUBIK acceptance

- Deployed commit `8436220` as package `0.15.1`. Migration `008_email_triage_taxonomy_v2` was
  present and SQLite returned `ok` from `PRAGMA integrity_check`.
- Published prompt v2 explicitly. Langfuse reported the production prompt was already unchanged at
  version `2`.
- Ran `taxonomy-v2-core` as an observational baseline: seven of nine cases matched. The recruiting
  case resolved to `notification` instead of `job`, and the deliberately unclassified case resolved
  to `slop` instead of `other`. No quality threshold was applied.
- Installed and validated one private domain rule without exposing its matcher. A bounded real-email
  triage completed in about half a second with source `rule`, no retained reason, no provider
  attempt, and no trace.
- Audited the resulting SQLite evidence directly: the attempt was successful, the decision source
  and rule identity were retained, and provider-attempt, provider-identity, reason, and trace
  evidence were absent as required.
- Ran the non-rule synthetic invoice through prompt v2. It completed through `llama_cpp`, returned
  an English `admin` decision, linked Langfuse prompt version `2`, and exported a trace.
- Re-ran the guarded deployment after installing the private rules file. The complete Python and
  frontend suites passed, the wheel was rebuilt, and the owner-only deployment backup contained the
  rules file with mode `0600`.
- Post-deployment checks confirmed the collector, API, alert-evaluator timer, Telegram bot, Avahi,
  and Nginx active; the evaluator result was successful; API liveness and the dashboard returned
  HTTP `200`; AI liveness/readiness succeeded; and SQLite integrity remained `ok`.

The release establishes technical routing behavior only. The seven-of-nine baseline is evidence for
the next feedback and evaluation work, not a claim that the taxonomy or prompt is sufficiently
accurate.

## Rollback

Unset `EMAIL_TRIAGE_RULES_FILE`, disable active triage during rollback, and reinstall `0.15.0`.
Migration 008 remains inert and preserves all data. The prompt-v2 version may remain in Langfuse;
ordinary runtime follows the selected production label after the owner chooses the rollback prompt.
