import asyncio
from typing import Any

import pytest

from codon_sdk.agents import (
    CodonWorkload,
    ExecutionReport,
    WorkloadRegistrationError,
    WorkloadRuntimeError,
)


@pytest.fixture(autouse=True)
def org_namespace(monkeypatch):
    monkeypatch.setenv("ORG_NAMESPACE", "test-org")


@pytest.fixture
def simple_workload():
    workload = CodonWorkload(name="DocAgent", version="1.0.0")

    def ingest(message, *, runtime, context):
        tokens = message["text"].split()
        runtime.emit("count", {"words": tokens})
        return tokens

    def count(message, *, runtime, context):
        return len(message["words"])

    workload.add_node(ingest, name="ingest", role="parser")
    workload.add_node(count, name="count", role="analyzer")
    workload.add_edge("ingest", "count")
    return workload


def test_add_node_requires_unique_names():
    workload = CodonWorkload(name="Duplicate", version="0.0.1")

    def foo(message, *, runtime, context):
        return message

    workload.add_node(foo, name="foo", role="processor")

    with pytest.raises(WorkloadRegistrationError):
        workload.add_node(foo, name="foo", role="processor")


def test_add_edge_requires_known_nodes(simple_workload):
    with pytest.raises(WorkloadRegistrationError):
        simple_workload.add_edge("missing", "ingest")
    with pytest.raises(WorkloadRegistrationError):
        simple_workload.add_edge("ingest", "missing")


def test_token_runtime_flow(simple_workload):
    report = simple_workload.execute({"text": "hello codon"}, deployment_id="dev")
    assert isinstance(report, ExecutionReport)
    assert report.node_results("count")[-1] == 2
    assert len(report.ledger) > 0


def test_execute_requires_deployment_id(simple_workload):
    with pytest.raises(ValueError):
        simple_workload.execute({"text": "hello"}, deployment_id="")


def test_logic_id_changes_when_graph_mutates(simple_workload):
    baseline_logic_id = simple_workload.logic_id

    def echo(message, *, runtime, context):
        return message

    simple_workload.add_node(echo, name="echo", role="responder")
    simple_workload.add_edge("count", "echo")

    assert simple_workload.logic_id != baseline_logic_id


def test_dependency_context_flow():
    workload = CodonWorkload(name="Context", version="0.0.1")

    def source(message, *, runtime, context):
        runtime.emit("count", message)
        return message

    def count(message, *, runtime, context):
        total = len(message["text"].split())
        runtime.emit("summary", {"total": total})
        return total

    def summary(message, *, runtime, context):
        runtime.state.setdefault("calls", 0)
        runtime.state["calls"] += 1
        return {
            "upstream": message["total"],
            "deployment": context["deployment_id"],
            "caller": context.get("invoked_by"),
            "call_count": runtime.state["calls"],
        }

    workload.add_node(source, name="source", role="ingest")
    workload.add_node(count, name="count", role="analyzer")
    workload.add_node(summary, name="summary", role="writer")
    workload.add_edge("source", "count")
    workload.add_edge("count", "summary")

    report = workload.execute(
        {"text": "hi there"}, deployment_id="qa", invoked_by="pytest"
    )

    summary_result = report.node_results("summary")[0]
    assert summary_result["upstream"] == 2
    assert summary_result["deployment"] == "qa"
    assert summary_result["caller"] == "pytest"
    assert summary_result["call_count"] == 1


def test_emit_to_invalid_target_raises():
    workload = CodonWorkload(name="InvalidRouting", version="0.0.1")

    def alpha(message, *, runtime, context):
        runtime.emit("beta", message)
        return message

    def beta(message, *, runtime, context):
        runtime.emit("gamma", message)
        return message

    workload.add_node(alpha, name="alpha", role="start")
    workload.add_node(beta, name="beta", role="next")
    workload.add_edge("alpha", "beta")

    with pytest.raises(WorkloadRuntimeError):
        workload.execute({"value": 1}, deployment_id="dev", entry_nodes=["alpha"])


def test_looping_node_respects_max_steps():
    workload = CodonWorkload(name="Looper", version="0.1.0")

    def loop(message, *, runtime, context):
        iteration = runtime.state.get("iteration", 0)
        runtime.state["iteration"] = iteration + 1
        if iteration < 2:
            runtime.emit("loop", message)
        else:
            runtime.stop()
        return iteration

    workload.add_node(loop, name="loop", role="cycler")
    workload.add_edge("loop", "loop")

    report = workload.execute({"payload": 1}, deployment_id="qa", max_steps=10)
    assert len(report.node_results("loop")) == 3  # initial + 2 re-entries


def test_execute_async_handles_coroutines():
    workload = CodonWorkload(name="Async", version="0.0.1")

    async def first(message, *, runtime, context):
        await asyncio.sleep(0)
        runtime.emit("second", {"value": message["value"] + 1})
        return {"value": message["value"]}

    async def second(message, *, runtime, context):
        await asyncio.sleep(0)
        return message["value"]

    workload.add_node(first, name="first", role="starter")
    workload.add_node(second, name="second", role="finisher")
    workload.add_edge("first", "second")

    report = asyncio.run(
        workload.execute_async({"value": 1}, deployment_id="async")
    )

    assert report.node_results("second")[0] == 2


def test_execution_context_includes_workload_identifiers(monkeypatch):
    monkeypatch.setenv("ORG_NAMESPACE", "context-org")

    workload = CodonWorkload(name="ContextAgent", version="1.0.0")
    captured_context: dict[str, Any] = {}

    def node(message, *, runtime, context):
        captured_context.update(context)
        return message

    workload.add_node(node, name="echo", role="responder")

    workload.execute({"value": 1}, deployment_id="dev-west")

    assert captured_context["workload_id"] == workload.agent_class_id
    assert captured_context["logic_id"] == workload.logic_id
    assert captured_context["workload_run_id"] == captured_context["run_id"]
    assert captured_context["organization_id"] == "context-org"
    assert captured_context["org_namespace"] == "context-org"
    assert captured_context["workload_name"] == "ContextAgent"
    assert captured_context["workload_version"] == "1.0.0"


def test_tracing_opt_in_emits_spans(monkeypatch):
    opentelemetry = pytest.importorskip("opentelemetry")
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")

    InMemorySpanExporter = export.InMemorySpanExporter
    SimpleSpanProcessor = export.SimpleSpanProcessor
    TracerProvider = sdk_trace.TracerProvider
    trace = opentelemetry.trace

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    workload = CodonWorkload(name="TraceAgent", version="1.0.0", enable_tracing=True)

    def first(message, *, runtime, context):
        runtime.emit("second", {"value": message["value"] + 1})
        return {"value": message["value"]}

    def second(message, *, runtime, context):
        return message["value"]

    workload.add_node(first, name="first", role="starter")
    workload.add_node(second, name="second", role="finisher")
    workload.add_edge("first", "second")

    workload.execute({"value": 1}, deployment_id="dev-trace")

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    span_names = {span.name for span in spans}
    assert "codon.node.first" in span_names
    assert "codon.node.second" in span_names
    for span in spans:
        assert span.attributes.get("codon.workload.id") == workload.agent_class_id
        assert span.attributes.get("codon.workload.logic_id") == workload.logic_id
        assert span.attributes.get("codon.workload.run_id")
        assert span.attributes.get("codon.workload.deployment_id") == "dev-trace"
        assert span.attributes.get("org.namespace") == "test-org"
        # organization id defaults to namespace in this test setup
        assert span.attributes.get("codon.organization.id") == "test-org"
    exporter.clear()


def test_tracing_opt_out_produces_no_spans(monkeypatch):
    opentelemetry = pytest.importorskip("opentelemetry")
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")

    InMemorySpanExporter = export.InMemorySpanExporter
    SimpleSpanProcessor = export.SimpleSpanProcessor
    TracerProvider = sdk_trace.TracerProvider
    trace = opentelemetry.trace

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    workload = CodonWorkload(name="TraceOff", version="1.0.0", enable_tracing=False)

    def node(message, *, runtime, context):
        return message["value"]

    workload.add_node(node, name="only", role="solo")

    workload.execute({"value": 1}, deployment_id="dev")

    spans = exporter.get_finished_spans()
    assert len(spans) == 0
    exporter.clear()
    assert captured_context["deployment_id"] == "dev-west"


def test_execute_streaming_sync(simple_workload):
    events = list(
        simple_workload.execute_streaming(
            {"text": "hello codon"}, deployment_id="dev"
        )
    )
    event_types = [event.event_type for event in events]
    assert "node_completed" in event_types
    assert event_types[-1] == "workflow_finished"
    report = events[-1].data["report"]
    assert report.node_results("count")[-1] == 2


def test_execute_streaming_async(simple_workload):
    async def collect():
        collected = []
        async for event in simple_workload.execute_streaming_async(
            {"text": "hello codon"}, deployment_id="dev"
        ):
            collected.append(event)
        return collected

    events = asyncio.run(collect())
    event_types = [event.event_type for event in events]
    assert "token_dequeued" in event_types
    assert "node_completed" in event_types
    assert event_types[-1] == "workflow_finished"
