import os
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

PACKAGE_ROOT = (
    Path(__file__).resolve().parents[4]
    / "instrumentation-packages"
    / "codon-instrumentation-langgraph"
)
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

pytest.importorskip("opentelemetry")
pytest.importorskip("opentelemetry.sdk.trace")

from codon.instrumentation.langgraph import (  # type: ignore
    LangGraphAdapterResult,
    LangGraphNodeSpanCallback,
    LangGraphTelemetryCallback,
    LangGraphWorkloadAdapter,
)


@pytest.fixture(autouse=True)
def org_namespace(monkeypatch):
    monkeypatch.setenv("ORG_NAMESPACE", "test-org")


def dummy_start(state):
    return {"value": state.get("value", 0) + 1}


def dummy_end(state):
    return state


class FakeGraph:
    def __init__(self, nodes=None, edges=None):
        self.nodes = nodes or {"start": dummy_start, "end": dummy_end}
        self.edges = edges or [("start", "end")]
        self.compile_called = False
        self.compile_kwargs = None
        self.seen_configs: list[Mapping[str, Any]] = []

    def compile(self, **kwargs):
        self.compile_called = True
        self.compile_kwargs = kwargs
        return self

    def invoke(self, state, *, config=None):
        if config is not None:
            self.seen_configs.append(config)
        return state


def test_adapter_returns_artifacts_with_compile_kwargs():
    graph = FakeGraph()

    result = LangGraphWorkloadAdapter.from_langgraph(
        graph,
        name="StubAgent",
        version="0.0.1",
        compile_kwargs={"checkpointer": "memory"},
        return_artifacts=True,
    )

    assert isinstance(result, LangGraphAdapterResult)
    workload = result.workload

    assert result.state_graph is graph
    assert graph.compile_called is True
    assert graph.compile_kwargs == {"checkpointer": "memory"}
    assert result.compiled_graph is graph

    assert getattr(workload, "langgraph_state_graph") is graph
    assert getattr(workload, "langgraph_compiled_graph") == result.compiled_graph
    assert getattr(workload, "langgraph_compile_kwargs") == {"checkpointer": "memory"}
    assert result.wrapped_graph.workload is workload

    node_names = {spec.name for spec in workload.nodes}
    assert node_names == {"start", "end"}

    start_spec = next(spec for spec in workload.nodes if spec.name == "start")
    end_spec = next(spec for spec in workload.nodes if spec.name == "end")

    assert start_spec.callable_signature.startswith("node_callable(")
    assert end_spec.callable_signature.startswith("node_callable(")


class RecordingRunnable:
    def __init__(self):
        self.seen_configs: list[Mapping[str, Any]] = []

    def invoke(self, state, *, config=None):
        self.seen_configs.append(config or {})
        return {"value": state.get("value", 0) + 1}

    def ainvoke(self, state, *, config=None):
        self.seen_configs.append(config or {})
        return {"value": state.get("value", 0) + 1}


def passthrough(state):
    return state


class NodeWrapper:
    def __init__(self, fn):
        self.value = fn

    def invoke(self, state):
        return self.value(state)


def test_runtime_config_merges_callbacks():
    graph = FakeGraph()

    base_config = {"callbacks": ["base"], "metadata": "base"}
    result = LangGraphWorkloadAdapter.from_langgraph(
        graph,
        name="ConfigurableAgent",
        version="0.0.2",
        runtime_config=base_config,
        return_artifacts=True,
    )

    workload = result.workload
    assert workload.langgraph_runtime_config == base_config

    invocation_config = {"metadata": "override", "callbacks": ["call"]}
    wrapped = result.wrapped_graph
    wrapped.invoke({"value": 0}, config=invocation_config)

    assert graph.seen_configs
    config = graph.seen_configs[0]

    assert config["metadata"] == "override"
    callbacks = config["callbacks"]
    assert len(callbacks) >= 4
    assert callbacks[0] == "base"
    assert callbacks[1] == "call"
    assert isinstance(callbacks[2], LangGraphNodeSpanCallback)
    assert isinstance(callbacks[3], LangGraphTelemetryCallback)

    start_spec = next(spec for spec in workload.nodes if spec.name == "start")
    assert start_spec.callable_signature.startswith("node_callable(")


def test_node_overrides_supply_signature_and_model_metadata():
    wrapper = NodeWrapper(dummy_start)
    graph = FakeGraph(nodes={"start": wrapper, "end": dummy_end})

    result = LangGraphWorkloadAdapter.from_langgraph(
        graph,
        name="WrappedAgent",
        version="0.0.3",
        node_overrides={
            "start": {
                "callable": dummy_start,
                "model_name": "gpt-test",
                "model_version": "1.0",
            }
        },
        return_artifacts=True,
    )

    workload = result.workload

    start_spec = next(spec for spec in workload.nodes if spec.name == "start")
    assert start_spec.callable_signature.startswith("dummy_start(")
    assert start_spec.model_name == "gpt-test"
    assert start_spec.model_version == "1.0"
