"""Langfuse prompt management and isolated email-triage tracing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from langfuse import Langfuse, propagate_attributes
from langfuse.model import ChatMessageDict, ChatMessageWithPlaceholdersDict

from personal_edge_lab.application.ports.email_triage import (
    TriagePromptSource,
    TriageTraceSink,
)
from personal_edge_lab.domain.ai import ModelMessage, ModelRole
from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    SyntheticTriageTracePayload,
    TriagePrompt,
    TriagePromptIdentity,
    TriagePromptManifest,
    TriageTraceRecord,
)

PROMPT_LABEL = "production"
REQUIRED_VARIABLES = frozenset({"taxonomy", "email_json"})


class PromptPublicationError(RuntimeError):
    """Sanitized failure from explicit Langfuse prompt publication."""


class LangfuseTriageRuntime(TriagePromptSource, TriageTraceSink):
    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        timeout_seconds: float,
        release: str,
        manifest: TriagePromptManifest,
    ) -> None:
        self._manifest = manifest
        self._native_prompts: dict[tuple[str, str], Any] = {}
        self._remote_prompt_confirmed = False
        secrets = (public_key, secret_key)

        def mask(*, data: Any, **_kwargs: Any) -> Any:
            return _mask_secrets(data, secrets)

        self._client = Langfuse(  # pyright: ignore[reportCallIssue]
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            timeout=max(1, int(timeout_seconds)),
            flush_at=1,
            flush_interval=1,
            environment="personal-edge-lab",
            release=release,
            mask=mask,
        )
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._release = release

    def resolve(self, variables: Mapping[str, str]) -> TriagePrompt:
        if set(variables) != REQUIRED_VARIABLES:
            raise ValueError("triage prompt variables are invalid")
        try:
            native = self._client.get_prompt(
                self._manifest.name,
                label=PROMPT_LABEL,
                type="chat",
                cache_ttl_seconds=300,
                fallback=_manifest_messages(self._manifest),
                max_retries=0,
                fetch_timeout_seconds=self._timeout_seconds,
            )
            if native.is_fallback or set(native.variables) != REQUIRED_VARIABLES:
                return _local_prompt(self._manifest, variables)
            if not _compatible_config(native.config):
                return _local_prompt(self._manifest, variables)
            compiled = native.compile(**dict(variables))
            messages = _validated_messages(compiled)
            identity = TriagePromptIdentity(
                name=native.name,
                version=str(native.version),
                source=PromptSourceKind.LANGFUSE,
            )
            self._remote_prompt_confirmed = True
            self._native_prompts[(identity.name, identity.version)] = native
            return TriagePrompt(identity=identity, messages=messages)
        except Exception:
            return _local_prompt(self._manifest, variables)

    def publish_packaged_prompt(self) -> tuple[str, str]:
        packaged = _manifest_messages(self._manifest)
        try:
            current = self._client.get_prompt(
                self._manifest.name,
                label=PROMPT_LABEL,
                type="chat",
                cache_ttl_seconds=0,
                fallback=packaged,
                max_retries=0,
                fetch_timeout_seconds=self._timeout_seconds,
            )
            if (
                not current.is_fallback
                and _normalized_prompt(current.prompt) == _normalized_prompt(packaged)
                and _compatible_config(current.config)
            ):
                return "unchanged", str(current.version)
            published = self._client.create_prompt(
                name=self._manifest.name,
                prompt=cast(
                    list[ChatMessageWithPlaceholdersDict | ChatMessageDict],
                    packaged,
                ),
                labels=[PROMPT_LABEL],
                type="chat",
                config=_prompt_config(),
                commit_message=(
                    f"Publish packaged email-triage prompt for release {self._release}"
                ),
            )
            return "published", str(published.version)
        except Exception as error:
            raise PromptPublicationError("Langfuse prompt publication failed") from error

    def record(self, record: TriageTraceRecord) -> str | None:
        usage = record.usage
        timing = record.timing
        if isinstance(record.payload, SyntheticTriageTracePayload):
            decision_output = (
                {
                    "label": record.payload.decision.label.value,
                    "reason": record.payload.decision.reason,
                }
                if record.payload.decision
                else None
            )
            trace_input: dict[str, Any] = {
                "sender": record.payload.email.sender,
                "subject": record.payload.email.subject,
                "message": record.payload.email.message,
            }
            generation_input: Any = [
                {"role": message.role.value, "content": message.content}
                for message in record.payload.prompt_messages
            ]
            generation_output: Any = record.payload.raw_output
            trace_output: dict[str, Any] = decision_output or {
                "outcome": "failure",
                "category": record.failure_category,
            }
            tags = ["email-triage", "synthetic"]
        else:
            payload = record.payload
            trace_input = {
                "content_sha256": payload.content_sha256,
                "sender_chars": payload.sender_chars,
                "subject_chars": payload.subject_chars,
                "message_chars": payload.message_chars,
                "source": payload.source,
                "cleanup_flags": list(payload.cleanup_flags),
            }
            generation_input = trace_input
            generation_output = (
                {
                    "label": payload.label.value,
                    "decision_sha256": payload.decision_sha256,
                    "reason_chars": payload.reason_chars,
                }
                if payload.label is not None
                else {"outcome": "failure", "category": record.failure_category}
            )
            trace_output = generation_output
            tags = ["email-triage", "gmail"]
        native_prompt = self._native_prompts.get((record.prompt.name, record.prompt.version))
        metadata = {
            "operation_id": record.operation_id,
            "profile": record.profile.name,
            "profile_version": record.profile.version,
            "taxonomy_version": record.profile.taxonomy_version,
            "schema_version": record.profile.schema_version,
            "generation_parameters_version": record.profile.generation_parameters_version,
            "prompt_source": record.prompt.source.value,
            "prompt_name": record.prompt.name,
            "prompt_version": record.prompt.version,
            "provider": record.provider,
            "queue_wait_seconds": (
                timing.queue_wait_seconds if timing else record.failure_queue_wait_seconds
            ),
            "provider_seconds": (
                timing.provider_seconds if timing else record.failure_provider_seconds
            ),
            "total_seconds": (
                timing.total_seconds
                if timing
                else (
                    record.failure_queue_wait_seconds + record.failure_provider_seconds
                    if record.failure_provider_seconds is not None
                    else record.failure_queue_wait_seconds
                )
            ),
            "schema_outcome": record.outcome,
            "failure_category": record.failure_category,
            "attempt_count": record.attempt_count,
            "retry_eligible": record.retry_eligible,
            "retry_after_seconds": record.retry_after_seconds,
        }
        with (
            propagate_attributes(  # pyright: ignore[reportCallIssue]
                tags=tags,
                trace_name="classify-email",
                version=record.profile.version,
                metadata={"operation_id": record.operation_id},
            ),
            self._client.start_as_current_observation(
                trace_context={"trace_id": record.trace_id},
                name="classify-email",
                as_type="span",
                input=trace_input,
                output=trace_output,
                metadata=metadata,
                version=record.profile.version,
                level="ERROR" if record.outcome == "failure" else "DEFAULT",
                status_message=record.failure_category,
            ),
            self._client.start_as_current_observation(
                name="generate-triage-decision",
                as_type="generation",
                input=generation_input,
                output=generation_output,
                metadata=metadata,
                model=record.model_alias,
                model_parameters={
                    "temperature": record.profile.temperature,
                    "max_output_tokens": record.profile.max_output_tokens,
                    "reasoning": "disabled",
                    "seed": 0,
                },
                usage_details=(
                    {
                        "input": usage.prompt_tokens,
                        "output": usage.completion_tokens,
                        "total": usage.total_tokens,
                    }
                    if usage
                    else None
                ),
                prompt=native_prompt,
                level="ERROR" if record.outcome == "failure" else "DEFAULT",
                status_message=record.failure_category,
            ),
        ):
            pass
        return record.trace_id if self._remote_prompt_confirmed else None

    def close(self) -> None:
        self._client.flush()
        self._client.shutdown()


def _validated_messages(value: Any) -> tuple[ModelMessage, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("remote prompt messages are invalid")
    messages: list[ModelMessage] = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"role", "content", "type"}:
            raise ValueError("remote prompt messages are invalid")
        if item.get("type") == "placeholder":
            raise ValueError("remote prompt placeholders are not supported")
        role = ModelRole(item.get("role"))
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError("remote prompt content is invalid")
        if "{{" in content or "}}" in content:
            raise ValueError("remote prompt contains unresolved variables")
        messages.append(ModelMessage(role=role, content=content))
    if sum(len(message.content) for message in messages) > 4096:
        raise ValueError("remote prompt is too large")
    return tuple(messages)


def _manifest_messages(manifest: TriagePromptManifest) -> list[ChatMessageDict]:
    return [
        ChatMessageDict(role=role.value, content=content) for role, content in manifest.messages
    ]


def _local_prompt(
    manifest: TriagePromptManifest,
    variables: Mapping[str, str],
) -> TriagePrompt:
    if set(variables) != REQUIRED_VARIABLES:
        raise ValueError("triage prompt variables are invalid")
    messages: list[ModelMessage] = []
    for role, template in manifest.messages:
        rendered = template
        for name, value in variables.items():
            rendered = rendered.replace(f"{{{{{name}}}}}", value)
        if "{{" in rendered or "}}" in rendered:
            raise ValueError("triage prompt contains unresolved variables")
        messages.append(ModelMessage(role=role, content=rendered))
    return TriagePrompt(
        identity=TriagePromptIdentity(
            name=manifest.name,
            version=manifest.version,
            source=PromptSourceKind.LOCAL_FALLBACK,
        ),
        messages=tuple(messages),
    )


def _prompt_config() -> dict[str, str]:
    return {
        "profile_version": "1.0.0",
        "taxonomy_version": "1.0.0",
        "schema_version": "1.0.0",
        "generation_parameters_version": "1.0.0",
    }


def _compatible_config(value: Any) -> bool:
    return isinstance(value, dict) and all(
        value.get(key) == expected for key, expected in _prompt_config().items()
    )


def _normalized_prompt(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            return []
        role = item.get("role")
        content = item.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            return []
        normalized.append({"role": role, "content": content})
    return normalized


def _mask_secrets(value: Any, secrets: tuple[str, str]) -> Any:
    if isinstance(value, str):
        masked = value
        for secret in secrets:
            masked = masked.replace(secret, "[REDACTED]")
        return masked
    if isinstance(value, dict):
        return {key: _mask_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_secrets(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_secrets(item, secrets) for item in value)
    return value
