"""Pure deterministic sender routing for private owner-defined rules."""

from __future__ import annotations

from email.utils import parseaddr
from typing import Any

from personal_edge_lab.domain.email_triage import (
    TriageEmail,
    TriageLabel,
    TriageRule,
    TriageRuleMatch,
    TriageRuleSet,
    TriageValidationError,
)

MAX_MATCHERS_PER_RULE = 100


def parse_rule_set(value: object) -> TriageRuleSet:
    if not isinstance(value, dict) or set(value) != {"version", "rules"}:
        raise TriageValidationError("triage rules must contain version and rules")
    version = value["version"]
    entries = value["rules"]
    if not isinstance(version, str) or not isinstance(entries, list):
        raise TriageValidationError("triage rules have an invalid shape")
    rules = tuple(_parse_rule(entry) for entry in entries)
    return TriageRuleSet(version=version, rules=rules)


def match_rule(ruleset: TriageRuleSet | None, email: TriageEmail) -> TriageRuleMatch | None:
    if ruleset is None or not ruleset.rules:
        return None
    address = _sender_address(email.sender)
    if address is None:
        return None
    domain = address.rsplit("@", 1)[1]
    for rule in sorted(ruleset.rules, key=lambda candidate: candidate.priority):
        if address in rule.exact_addresses or any(
            domain == candidate or domain.endswith(f".{candidate}") for candidate in rule.domains
        ):
            return TriageRuleMatch(
                rule_id=rule.rule_id,
                ruleset_version=ruleset.version,
                label=rule.label,
                priority=rule.priority,
            )
    return None


def _parse_rule(value: object) -> TriageRule:
    if not isinstance(value, dict):
        raise TriageValidationError("triage rule entry is invalid")
    allowed = {"id", "priority", "label", "exact_addresses", "domains"}
    if not set(value).issubset(allowed) or not {"id", "priority", "label"}.issubset(value):
        raise TriageValidationError("triage rule entry has invalid fields")
    try:
        label = TriageLabel(value["label"])
    except (TypeError, ValueError) as error:
        raise TriageValidationError("triage rule label is invalid") from error
    exact_addresses = _string_list(value.get("exact_addresses", []), "address")
    domains = _string_list(value.get("domains", []), "domain")
    return TriageRule(
        rule_id=value["id"],
        priority=value["priority"],
        label=label,
        exact_addresses=tuple(_normalize_address(item) for item in exact_addresses),
        domains=tuple(_normalize_domain(item) for item in domains),
    )


def _string_list(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_MATCHERS_PER_RULE
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise TriageValidationError(f"triage rule {label} matchers are invalid")
    if len(set(value)) != len(value):
        raise TriageValidationError(f"triage rule {label} matchers must be unique")
    return value


def _sender_address(sender: str) -> str | None:
    _display_name, address = parseaddr(sender)
    try:
        return _normalize_address(address)
    except TriageValidationError:
        return None


def _normalize_address(value: str) -> str:
    stripped = value.strip().lower()
    if stripped.count("@") != 1:
        raise TriageValidationError("triage rule address is invalid")
    local, domain = stripped.rsplit("@", 1)
    if not local or any(character.isspace() for character in local):
        raise TriageValidationError("triage rule address is invalid")
    return f"{local}@{_normalize_domain(domain)}"


def _normalize_domain(value: str) -> str:
    stripped = value.strip().lower().rstrip(".")
    if (
        not stripped
        or len(stripped) > 253
        or stripped.startswith(".")
        or any(character.isspace() for character in stripped)
    ):
        raise TriageValidationError("triage rule domain is invalid")
    try:
        ascii_value = stripped.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise TriageValidationError("triage rule domain is invalid") from error
    labels = ascii_value.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise TriageValidationError("triage rule domain is invalid")
    return ascii_value
