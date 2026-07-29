from __future__ import annotations

import json

import pytest

from personal_edge_lab.apps.configuration import ConfigurationError
from personal_edge_lab.apps.email_triage_cli.config import read_triage_rules
from personal_edge_lab.domain.email_triage import (
    TriageEmail,
    TriageLabel,
    TriageValidationError,
)
from personal_edge_lab.modules.email_triage.rules import match_rule, parse_rule_set


def test_rules_match_exact_addresses_and_boundary_safe_subdomains_by_priority() -> None:
    rules = parse_rule_set(
        {
            "version": "2026-07-29",
            "rules": [
                {
                    "id": "education-domain",
                    "priority": 20,
                    "label": "education",
                    "domains": ["uab.cat"],
                },
                {
                    "id": "mckinsey-address",
                    "priority": 10,
                    "label": "mckinsey",
                    "exact_addresses": ["person@sub.uab.cat"],
                },
            ],
        }
    )

    exact = match_rule(rules, TriageEmail("Person <PERSON@sub.uab.cat>", "x", "body"))
    domain = match_rule(rules, TriageEmail("Other <other@school.uab.cat>", "x", "body"))
    lookalike = match_rule(rules, TriageEmail("Other <other@notuab.cat>", "x", "body"))

    assert exact is not None and exact.rule_id == "mckinsey-address"
    assert domain is not None and domain.label is TriageLabel.EDUCATION
    assert lookalike is None


@pytest.mark.parametrize(
    "value",
    [
        {"version": "1", "rules": [{"id": "x", "priority": 1, "label": "work"}]},
        {
            "version": "1",
            "rules": [
                {
                    "id": "x",
                    "priority": 1,
                    "label": "job",
                    "domains": ["*.example.test"],
                }
            ],
        },
        {"version": "1", "rules": [{"id": "x", "priority": 1, "label": "job"}]},
    ],
)
def test_rules_reject_legacy_labels_wildcards_and_missing_matchers(value: object) -> None:
    with pytest.raises(TriageValidationError):
        parse_rule_set(value)


def test_rules_file_is_optional_and_must_be_private(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("EMAIL_TRIAGE_RULES_FILE", raising=False)
    assert read_triage_rules() is None

    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "version": "1",
                "rules": [
                    {
                        "id": "known",
                        "priority": 1,
                        "label": "job",
                        "domains": ["example.test"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.setenv("EMAIL_TRIAGE_RULES_FILE", str(path))
    assert read_triage_rules().rules[0].rule_id == "known"

    path.chmod(0o644)
    with pytest.raises(ConfigurationError, match="contains invalid rules|mode 0600"):
        read_triage_rules()
