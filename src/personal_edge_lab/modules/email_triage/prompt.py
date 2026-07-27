"""Packaged prompt manifest and deterministic local resolution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files

from personal_edge_lab.application.ports.email_triage import TriagePromptSource
from personal_edge_lab.domain.ai import ModelMessage, ModelRole
from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    TriagePrompt,
    TriagePromptIdentity,
    TriagePromptManifest,
    TriageValidationError,
)

REQUIRED_VARIABLES = frozenset({"taxonomy", "email_json"})


def load_packaged_prompt() -> TriagePromptManifest:
    resource = files("personal_edge_lab.modules.email_triage").joinpath("prompt.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "chat"
        or not isinstance(payload.get("name"), str)
        or not isinstance(payload.get("version"), str)
        or not isinstance(payload.get("messages"), list)
    ):
        raise TriageValidationError("packaged triage prompt is invalid")
    messages: list[tuple[ModelRole, str]] = []
    for item in payload["messages"]:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise TriageValidationError("packaged triage prompt messages are invalid")
        try:
            role = ModelRole(item["role"])
        except (TypeError, ValueError) as error:
            raise TriageValidationError("packaged triage prompt role is invalid") from error
        content = item["content"]
        if not isinstance(content, str) or not content.strip():
            raise TriageValidationError("packaged triage prompt content is invalid")
        messages.append((role, content))
    manifest = TriagePromptManifest(
        name=payload["name"],
        version=payload["version"],
        messages=tuple(messages),
    )
    _validate_variables(manifest)
    return manifest


class LocalTriagePromptSource(TriagePromptSource):
    def __init__(self, manifest: TriagePromptManifest | None = None) -> None:
        self.manifest = manifest or load_packaged_prompt()

    def resolve(self, variables: Mapping[str, str]) -> TriagePrompt:
        if set(variables) != REQUIRED_VARIABLES or not all(
            isinstance(value, str) for value in variables.values()
        ):
            raise TriageValidationError("triage prompt variables are invalid")
        messages = tuple(
            ModelMessage(role=role, content=_render(content, variables))
            for role, content in self.manifest.messages
        )
        return TriagePrompt(
            identity=TriagePromptIdentity(
                name=self.manifest.name,
                version=self.manifest.version,
                source=PromptSourceKind.LOCAL_FALLBACK,
            ),
            messages=messages,
        )


def _validate_variables(manifest: TriagePromptManifest) -> None:
    joined = "\n".join(content for _role, content in manifest.messages)
    found = {variable for variable in REQUIRED_VARIABLES if f"{{{{{variable}}}}}" in joined}
    if found != REQUIRED_VARIABLES:
        raise TriageValidationError("packaged triage prompt variables are invalid")


def _render(template: str, variables: Mapping[str, str]) -> str:
    rendered = template
    for name, value in variables.items():
        rendered = rendered.replace(f"{{{{{name}}}}}", value)
    if "{{" in rendered or "}}" in rendered:
        raise TriageValidationError("triage prompt contains unresolved variables")
    return rendered
