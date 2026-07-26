from __future__ import annotations

import os

import pytest

from personal_edge_lab.apps.ai_cli.config import CompletionSettings, HealthSettings
from personal_edge_lab.domain.ai import CompletionRequest, ModelMessage, ModelRole
from personal_edge_lab.infrastructure.ai.llama_cpp import (
    LlamaCppHealthProbe,
    LlamaCppLanguageModel,
)

pytestmark = [
    pytest.mark.unoq_live,
    pytest.mark.skipif(
        os.getenv("RUN_UNOQ_LIVE_TESTS", "").lower() != "true",
        reason="set RUN_UNOQ_LIVE_TESTS=true on RUBIK to call the real UNO Q",
    ),
]


def test_real_unoq_health_and_bounded_completion() -> None:
    health_settings = HealthSettings.from_env()
    completion_settings = CompletionSettings.from_env()
    with LlamaCppHealthProbe(
        base_url=health_settings.base_url,
        timeout_seconds=health_settings.timeout_seconds,
    ) as probe:
        assert probe.check().status == "ok"
    request = CompletionRequest(
        messages=(ModelMessage(ModelRole.USER, "Return one word"),),
        model_alias=completion_settings.model_alias,
        max_output_tokens=1,
        temperature=0,
    )
    with LlamaCppLanguageModel(
        base_url=completion_settings.base_url,
        api_key=completion_settings.api_key,
        timeout_seconds=completion_settings.timeout_seconds,
    ) as model:
        result = model.complete(request)
    assert isinstance(result.text, str)
    assert result.provider == "llama_cpp"
    assert result.model_alias == completion_settings.model_alias
