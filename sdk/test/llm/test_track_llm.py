import asyncio

import pytest

pytest.importorskip("opentelemetry")
pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import InMemorySpanExporter, SimpleSpanProcessor

from codon_sdk.instrumentation.telemetry import NodeTelemetryPayload
from codon_sdk.llm import track_llm_async, track_llm


@pytest.fixture(autouse=True)
def tracer_provider():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()


@pytest.fixture(autouse=True)
def reset_current_invocation(monkeypatch):
    payload = NodeTelemetryPayload(
        workload_id="demo-workload",
        workload_logic_id="logic-id",
        workload_run_id="run-id",
        nodespec_id="node-123",
        node_name="node",
        node_role="role",
    )

    from codon_sdk import llm as llm_module

    monkeypatch.setattr(llm_module, "current_invocation", lambda: payload)
    return payload


class DummyResponse:
    def __init__(self):
        self.usage = {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "total_tokens": 12,
        }
        self.model = "gpt-test"
        self.provider = "openai"


async def test_track_llm_async_updates_payload(reset_current_invocation, tracer_provider):
    async def dummy_call(*args, **kwargs):
        return DummyResponse()

    response = await track_llm_async(dummy_call)
    assert isinstance(response, DummyResponse)

    payload = reset_current_invocation
    assert payload.input_tokens == 5
    assert payload.output_tokens == 7
    assert payload.total_tokens == 12
    assert payload.model_identifier == "gpt-test"

    spans = tracer_provider.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["codon.tokens.input"] == 5
    assert span.attributes["codon.model.id"] == "gpt-test"


def test_track_llm_sync(reset_current_invocation, tracer_provider):
    def dummy_sync(*args, **kwargs):
        return DummyResponse()

    response = track_llm(dummy_sync)
    assert isinstance(response, DummyResponse)

    payload = reset_current_invocation
    assert payload.total_tokens == 12

    spans = tracer_provider.get_finished_spans()
    assert len(spans) == 1


async def test_track_llm_async_handles_config(monkeypatch, reset_current_invocation):
    call_history = []

    async def dummy_call(*args, **kwargs):
        call_history.append(kwargs)
        return DummyResponse()

    response = await track_llm_async(
        dummy_call,
        config={"callbacks": ["existing"]},
    )

    assert isinstance(response, DummyResponse)
    assert len(call_history) == 1
    assert "callbacks" in call_history[0]
    assert call_history[0]["callbacks"] == ["existing"]
