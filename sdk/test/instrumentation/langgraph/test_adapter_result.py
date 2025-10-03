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

    def compile(self, **kwargs):
        self.compile_called = True
        self.compile_kwargs = kwargs
        return {"compiled": True, "kwargs": kwargs}


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
    assert result.compiled_graph["kwargs"]["checkpointer"] == "memory"

    assert getattr(workload, "langgraph_state_graph") is graph
    assert getattr(workload, "langgraph_compiled_graph") == result.compiled_graph
    assert getattr(workload, "langgraph_compile_kwargs") == {"checkpointer": "memory"}

    node_names = {spec.name for spec in workload.nodes}
    assert node_names == {"start", "end"}


class RecordingRunnable:
    def __init__(self):
        self.seen_configs: list[Mapping[str, Any]] = []

    def invoke(self, state, *, config=None):
        self.seen_configs.append(config or {})
        return {"value": state.get("value", 0) + 1}


def passthrough(state):
    return state


def test_runtime_config_merges_callbacks():
    recording = RecordingRunnable()
    nodes = {"start": recording, "end": passthrough}
    graph = FakeGraph(nodes=nodes)

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
    workload.execute(
        {"state": {"value": 0}},
        deployment_id="dev",
        langgraph_config=invocation_config,
    )

    assert recording.seen_configs
    config = recording.seen_configs[0]

    assert config["metadata"] == "override"
    callbacks = config["callbacks"]
    assert callbacks[0] == "base"
    assert callbacks[1] == "call"
    assert isinstance(callbacks[2], LangGraphTelemetryCallback)
