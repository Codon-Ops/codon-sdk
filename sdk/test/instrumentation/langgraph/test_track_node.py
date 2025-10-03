import json
import os

import pytest

opentelemetry = pytest.importorskip("opentelemetry")
trace = opentelemetry.trace
sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
trace_export = pytest.importorskip("opentelemetry.sdk.trace.export")

TracerProvider = sdk_trace.TracerProvider
InMemorySpanExporter = trace_export.InMemorySpanExporter
SimpleSpanProcessor = trace_export.SimpleSpanProcessor

from codon_sdk.agents import CodonWorkload
from codon_sdk.instrumentation.schemas.telemetry.spans import CodonBaseSpanAttributes
from codon.instrumentation.langgraph import (
    LangGraphTelemetryCallback,
    current_invocation,
    track_node,
)


@pytest.fixture(autouse=True)
def _org_namespace(monkeypatch):
    monkeypatch.setenv("ORG_NAMESPACE", "test-org")


@pytest.fixture()
def span_exporter(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        trace.set_tracer_provider(provider)
    except Exception:  # pragma: no cover - reconfigure in existing test runs
        trace._TRACER_PROVIDER = provider  # type: ignore[attr-defined]
    yield exporter
    exporter.clear()


class _RuntimeStub:
    def __init__(self, workload):
        self._workload = workload


def test_track_node_emits_workload_and_token_attributes(span_exporter):
    workload = CodonWorkload(name="TestAgent", version="1.0.0")

    callback = LangGraphTelemetryCallback()

    @track_node("demo_node", role="researcher")
    def instrumented_node(message, *, runtime, context):
        invocation = current_invocation()
        assert invocation is not None

        callback.on_llm_start(
            {"kwargs": {"model": "gpt-4o", "provider": "openai"}},
            ["Prompt body"],
        )

        class _Response:
            llm_output = {
                "token_usage": {"prompt_tokens": 5, "completion_tokens": 7},
                "model_name": "gpt-4o",
                "model_vendor": "openai",
                "response_metadata": {"request_id": "req-123"},
            }
            generations = []

        callback.on_llm_end(_Response())
        return {"echo": message}

    context = {
        "deployment_id": "dev-east",
        "workload_id": workload.agent_class_id,
        "logic_id": workload.logic_id,
        "workload_run_id": "run-42",
        "organization_id": os.getenv("ORG_NAMESPACE"),
    }

    instrumented_node(
        {"question": "What is Codon?"},
        runtime=_RuntimeStub(workload),
        context=context,
    )

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    attributes = span.attributes

    assert attributes[CodonBaseSpanAttributes.WorkloadRunId.value] == "run-42"
    assert attributes[CodonBaseSpanAttributes.WorkloadId.value] == workload.agent_class_id
    assert attributes[CodonBaseSpanAttributes.WorkloadLogicId.value] == workload.logic_id
    assert attributes[CodonBaseSpanAttributes.OrganizationId.value] == "test-org"
    assert attributes[CodonBaseSpanAttributes.DeploymentId.value] == "dev-east"
    assert attributes[CodonBaseSpanAttributes.TokenInput.value] == 5
    assert attributes[CodonBaseSpanAttributes.TokenOutput.value] == 7
    assert attributes[CodonBaseSpanAttributes.ModelVendor.value] == "openai"
    assert attributes[CodonBaseSpanAttributes.ModelIdentifier.value] == "gpt-4o"
    raw_attributes = attributes[CodonBaseSpanAttributes.NodeRawAttributes.value]
    raw_payload = json.loads(raw_attributes)
    assert raw_payload["token_usage"]["prompt_tokens"] == 5
