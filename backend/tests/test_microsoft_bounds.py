"""All Microsoft-provider checks here are local fakes: no identity or HTTP calls."""
import json
from types import SimpleNamespace

import pytest

from backend.agents import MicrosoftProvider
from backend.models import StrictModel


class Result(StrictModel):
    reviewed: bool


def fake_provider(max_calls=2):
    provider = MicrosoftProvider.__new__(MicrosoftProvider)
    provider.model = "local-test-deployment"
    provider.max_output_tokens = 1800
    provider.max_calls, provider.call_count = max_calls, 0
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_text='{"reviewed":true}')

    provider.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    return provider, requests


def test_unapproved_provider_rejects_before_sdk_or_credentials():
    with pytest.raises(RuntimeError, match="approval"):
        MicrosoftProvider("https://example.invalid/api/projects/local", "local", approved=False)


def test_approved_flag_without_explicit_call_budget_is_insufficient():
    with pytest.raises(RuntimeError, match="inference limit"):
        MicrosoftProvider("https://example.invalid/api/projects/local", "local", approved=True)


def test_provider_reserves_global_budget_and_preserves_structured_role_input():
    import asyncio

    provider, requests = fake_provider()

    async def exercise():
        results = await asyncio.gather(
            provider._invoke("analyst", {"fact_ids": ["f_observed"]}, Result),
            provider._invoke("editor", {"proposal": "verified"}, Result),
        )
        assert all(result.reviewed for result in results)
        with pytest.raises(RuntimeError, match="budget is exhausted"):
            await provider._invoke("analyst", {}, Result)

    asyncio.run(exercise())
    assert provider.call_count == len(requests) == 2
    assert all(request["max_output_tokens"] == 1800 for request in requests)
    analyst_request = next(request for request in requests if request["input"][0]["content"] == "analyst")
    assert json.loads(analyst_request["input"][1]["content"])["fact_ids"] == ["f_observed"]


def test_oversized_evidence_is_rejected_before_reserving_or_calling():
    import asyncio

    provider, requests = fake_provider()
    with pytest.raises(RuntimeError, match="request size"):
        asyncio.run(provider._invoke("editor", {"text": "x" * 40_001}, Result))
    assert provider.call_count == 0
    assert requests == []
