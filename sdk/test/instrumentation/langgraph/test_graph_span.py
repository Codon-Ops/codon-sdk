import json

import pytest

opentelemetry = pytest.importorskip("opentelemetry")
trace = opentelemetry.trace
sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
trace_export = pytest.importorskip("opentelemetry.sdk.trace.export")

TracerProvider = sdk_trace.TracerProvider
InMemorySpanExporter = trace_export.InMemorySpanExporter
SimpleSpanProcessor = trace_export.SimpleSpanProcessor

from codon.instrumentation.langgraph import LangGraphWorkloadAdapter
from codon_sdk.instrumentation.schemas.telemetry.spans import (
    CodonGraphSpanAttributes,
    CodonSpanNames,
)


class FakeGraph:
    def __init__(self):
        self.nodes = {"start": lambda state: state}
        self.edges = [("start", "start")]

    def compile(self, **kwargs):
        return self

    def invoke(self, state, *, config=None):
        return state


def test_graph_span_emitted(monkeypatch):
    monkeypatch.setenv("ORG_NAMESPACE", "test-org")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        trace.set_tracer_provider(provider)
    except Exception:  # pragma: no cover - reconfigure in existing test runs
        trace._TRACER_PROVIDER = provider  # type: ignore[attr-defined]

    graph = FakeGraph()
    wrapped = LangGraphWorkloadAdapter.from_langgraph(
        graph,
        name="GraphAgent",
        version="0.1.0",
    )

    wrapped.invoke({"value": 1})

    spans = exporter.get_finished_spans()
    graph_spans = [span for span in spans if span.name == CodonSpanNames.AgentGraph.value]
    assert graph_spans
    graph_span = graph_spans[0]
    attrs = graph_span.attributes

    assert CodonGraphSpanAttributes.NodeCount.value in attrs
    assert CodonGraphSpanAttributes.EdgeCount.value in attrs
    assert CodonGraphSpanAttributes.DefinitionJson.value in attrs

    definition = json.loads(attrs[CodonGraphSpanAttributes.DefinitionJson.value])
    assert definition["nodes"]
    assert definition["edges"]
