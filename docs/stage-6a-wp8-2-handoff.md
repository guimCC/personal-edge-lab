# Stage 6A WP8.2 handoff

**Release:** `0.15.1`
**Status:** Implemented locally; RUBIK acceptance pending

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

1. Deploy `0.15.1` with `EMAIL_TRIAGE_RULES_FILE` unset and verify migration 008 plus SQLite
   integrity.
2. Publish prompt v2 explicitly with `ai_cli prompt-publish`.
3. Run `ai_cli evaluate --fixture-set taxonomy-v2-core`; record the baseline without treating any
   score as a release threshold.
4. Create the private rules file from the synthetic example, set mode `0600`, run `rules-check`,
   and deploy again so it is validated and backed up.
5. Run one bounded triage containing a known rule match and one non-match. Confirm the first has
   source `rule`, no reason, no UNO Q call, and no Langfuse trace; confirm the second has source
   `model`, an English reason, and the exact v2 prompt link.
6. Confirm the dashboard distinguishes Rule from AI and legacy rows remain viewable.
7. Re-run the existing Gmail, AI, tracing, API, dashboard, platform, SQLite, UNO Q, and firewall
   checks.

## Rollback

Unset `EMAIL_TRIAGE_RULES_FILE`, disable active triage during rollback, and reinstall `0.15.0`.
Migration 008 remains inert and preserves all data. The prompt-v2 version may remain in Langfuse;
ordinary runtime follows the selected production label after the owner chooses the rollback prompt.
