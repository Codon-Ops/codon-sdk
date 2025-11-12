# Copyright 2025 Codon, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""LangGraph integration helpers for Codon Workloads."""
from __future__ import annotations

import inspect
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from codon_sdk.agents import CodonWorkload
from codon_sdk.agents.codon_workload import WorkloadRuntimeError

from .callbacks import LangGraphTelemetryCallback

try:  # pragma: no cover - we do not require langgraph at install time
    from langgraph.graph import StateGraph  # type: ignore
except Exception:  # pragma: no cover
    StateGraph = Any  # fallback for type checkers

JsonDict = Dict[str, Any]
RawNodeMap = Mapping[str, Any]
RawEdgeIterable = Iterable[Tuple[str, str]]


def _merge_runtime_configs(
    base: Optional[Mapping[str, Any]],
    override: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    callbacks: List[Any] = []

    for cfg in (base, override):
        if not cfg:
            continue
        for key, value in cfg.items():
            if key == "callbacks":
                if isinstance(value, (list, tuple)):
                    callbacks.extend(value)
                else:
                    callbacks.append(value)
            else:
                merged[key] = value

    callbacks.append(LangGraphTelemetryCallback())
    merged["callbacks"] = callbacks
    return merged


@dataclass(frozen=True)
class LangGraphAdapterResult:
    """Artifacts produced when adapting a LangGraph graph."""

    workload: CodonWorkload
    state_graph: Any
    compiled_graph: Any


@dataclass(frozen=True)
class NodeOverride:
    """Caller-provided metadata overrides for a LangGraph node."""

    role: Optional[str] = None
    callable: Optional[Callable[..., Any]] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    input_schema: Optional[str] = None
    output_schema: Optional[str] = None


class LangGraphWorkloadAdapter:
    """Factory helpers for building Codon workloads from LangGraph graphs."""

    @classmethod
    def from_langgraph(
        cls,
        graph: Any,
        *,
        name: str,
        version: str,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        org_namespace: Optional[str] = None,
        node_overrides: Optional[Mapping[str, Any]] = None,
        entry_nodes: Optional[Sequence[str]] = None,
        max_reviews: Optional[int] = None,
        compile_kwargs: Optional[Mapping[str, Any]] = None,
        runtime_config: Optional[Mapping[str, Any]] = None,
        return_artifacts: bool = False,
    ) -> Union[CodonWorkload, LangGraphAdapterResult]:
        """Create a :class:`CodonWorkload` from a LangGraph ``StateGraph``.

        Parameters
        ----------
        graph
            A LangGraph ``StateGraph`` (preferred) or compatible object exposing
            ``nodes``/``edges``.
        compile_kwargs
            Optional keyword arguments forwarded to ``graph.compile(...)`` so
            you can attach checkpointers, memory stores, or other runtime extras.
        return_artifacts
            When ``True`` return a :class:`LangGraphAdapterResult` containing the
            workload, the original state graph, and the compiled graph.
        """

        compiled, raw_nodes, raw_edges = cls._normalise_graph(
            graph, compile_kwargs=compile_kwargs
        )
        overrides = cls._normalise_overrides(node_overrides)
        node_map = cls._coerce_node_map(raw_nodes)
        raw_edge_list = cls._coerce_edges(raw_edges)

        node_names = set(node_map.keys())
        valid_edges = []
        entry_from_virtual = set()
        for src, dst in raw_edge_list:
            if src not in node_names or dst not in node_names:
                if src not in node_names and dst in node_names:
                    entry_from_virtual.add(dst)
                continue
            valid_edges.append((src, dst))

        workload = CodonWorkload(
            name=name,
            version=version,
            description=description,
            tags=tags,
        )

        successors: Dict[str, Sequence[str]] = cls._build_successor_map(valid_edges)
        predecessors: Dict[str, Sequence[str]] = cls._build_predecessor_map(valid_edges)

        for node_name, runnable in node_map.items():
            override = overrides.get(node_name)
            role = cls._derive_role(node_name, runnable, override.role if override else None)
            model_name = override.model_name if override else None
            model_version = override.model_version if override else None
            nodespec_kwargs: Dict[str, Any] = {}
            if override and override.input_schema is not None:
                nodespec_kwargs["input_schema"] = override.input_schema
            if override and override.output_schema is not None:
                nodespec_kwargs["output_schema"] = override.output_schema

            instrumented_callable = cls._wrap_node(
                node_name=node_name,
                role=role,
                runnable=runnable,
                successors=tuple(successors.get(node_name, ())),
                nodespec_target=override.callable if override else None,
                model_name=model_name,
                model_version=model_version,
                nodespec_kwargs=nodespec_kwargs or None,
            )
            workload.add_node(
                instrumented_callable,
                name=node_name,
                role=role,
                org_namespace=org_namespace,
            )

        for edge in valid_edges:
            workload.add_edge(*edge)

        workload._predecessors.update({k: set(v) for k, v in predecessors.items()})
        workload._successors.update({k: set(v) for k, v in successors.items()})

        if entry_nodes is not None:
            workload._entry_nodes = list(entry_nodes)
        else:
            inferred = [node for node, preds in predecessors.items() if not preds]
            inferred = list({*inferred, *entry_from_virtual})
            workload._entry_nodes = inferred or list(node_map.keys())

        setattr(workload, "langgraph_state_graph", graph)
        setattr(workload, "langgraph_compiled_graph", compiled)
        setattr(workload, "langgraph_compile_kwargs", dict(compile_kwargs or {}))
        setattr(workload, "langgraph_runtime_config", dict(runtime_config or {}))

        if return_artifacts:
            return LangGraphAdapterResult(
                workload=workload,
                state_graph=graph,
                compiled_graph=compiled,
            )

        return workload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_graph(
        graph: Any, *, compile_kwargs: Optional[Mapping[str, Any]] = None
    ) -> Tuple[Any, Any, Any]:
        """Return compiled graph plus raw node/edge structures."""

        raw_nodes, raw_edges = LangGraphWorkloadAdapter._extract_nodes_edges(graph)
        compiled = graph
        if hasattr(graph, "compile"):
            kwargs = dict(compile_kwargs or {})
            compiled = graph.compile(**kwargs)
        comp_nodes, comp_edges = LangGraphWorkloadAdapter._extract_nodes_edges(compiled)

        nodes = raw_nodes or comp_nodes
        edges = raw_edges or comp_edges

        if nodes is None or edges is None:
            raise ValueError(
                "Unable to extract nodes/edges from LangGraph graph. Pass the original StateGraph or ensure the compiled graph exposes config.nodes/config.edges."
            )

        return compiled, nodes, edges

    @staticmethod
    def _extract_nodes_edges(obj: Any) -> Tuple[Optional[Any], Optional[Any]]:
        nodes = None
        edges = None

        graph_attr = getattr(obj, "graph", None)
        if graph_attr is not None:
            nodes = nodes or getattr(graph_attr, "nodes", None)
            edges = edges or getattr(graph_attr, "edges", None)

        nodes = nodes or getattr(obj, "nodes", None)
        edges = edges or getattr(obj, "edges", None)

        config = getattr(obj, "config", None)
        if config is not None:
            nodes = nodes or getattr(config, "nodes", None)
            edges = edges or getattr(config, "edges", None)
            if nodes is None and isinstance(config, Mapping):
                nodes = config.get("nodes")
            if edges is None and isinstance(config, Mapping):
                edges = config.get("edges")

        if nodes is not None and callable(getattr(nodes, "items", None)):
            nodes = dict(nodes)

        return nodes, edges

    @staticmethod
    def _coerce_node_map(nodes: Any) -> Dict[str, Any]:
        if isinstance(nodes, Mapping):
            result: Dict[str, Any] = {}
            for name, data in nodes.items():
                result[name] = LangGraphWorkloadAdapter._select_runnable(name, data)
            return result

        result: Dict[str, Any] = {}
        for item in nodes:
            if isinstance(item, tuple) and len(item) >= 2:
                name = item[0]
                data = item[1]
                result[name] = LangGraphWorkloadAdapter._select_runnable(name, data)
            else:
                raise ValueError(f"Unrecognized LangGraph node entry: {item!r}")

        return result

    @staticmethod
    def _normalise_overrides(overrides: Optional[Mapping[str, Any]]) -> Dict[str, NodeOverride]:
        if not overrides:
            return {}

        result: Dict[str, NodeOverride] = {}
        for name, value in overrides.items():
            if isinstance(value, NodeOverride):
                result[name] = value
                continue
            if isinstance(value, Mapping):
                result[name] = NodeOverride(
                    role=value.get("role"),
                    callable=value.get("callable"),
                    model_name=value.get("model_name"),
                    model_version=value.get("model_version"),
                    input_schema=value.get("input_schema"),
                    output_schema=value.get("output_schema"),
                )
                continue
            raise TypeError(
                "node_overrides values must be NodeOverride instances or mapping objects"
            )

        return result

    @staticmethod
    def _select_runnable(name: str, data: Any) -> Any:
        candidates: list[Any] = []

        if callable(data) or hasattr(data, "ainvoke") or hasattr(data, "invoke"):
            return data

        if isinstance(data, Mapping):
            for key in ("callable", "node", "value", "runnable", "invoke", "ainvoke"):
                if key in data and data[key] is not None:
                    candidates.append(data[key])
        else:
            for attr in ("callable", "node", "value", "runnable", "wrapped", "inner", "invoke", "ainvoke"):
                if hasattr(data, attr):
                    candidate = getattr(data, attr)
                    if candidate is not None and candidate is not data:
                        candidates.append(candidate)

        for candidate in candidates:
            if candidate is None:
                continue
            if callable(candidate) or hasattr(candidate, "ainvoke") or hasattr(candidate, "invoke"):
                return candidate

        raise WorkloadRuntimeError(f"Node '{name}' is not callable")

    @staticmethod
    def _coerce_edges(edges: Any) -> Sequence[Tuple[str, str]]:
        result: list[Tuple[str, str]] = []

        for item in edges:
            source = target = None
            if isinstance(item, tuple):
                if len(item) >= 2:
                    source, target = item[0], item[1]
            else:
                source = getattr(item, "source", None) or getattr(item, "start", None)
                target = getattr(item, "target", None) or getattr(item, "end", None)
                if source is None and isinstance(item, Mapping):
                    source = item.get("source")
                    target = item.get("target")

            if source is None or target is None:
                raise ValueError(f"Cannot determine edge endpoints for entry: {item!r}")

            result.append((source, target))

        return result

    @staticmethod
    def _derive_role(
        node_name: str,
        runnable: Any,
        override_role: Optional[str],
    ) -> str:
        if override_role:
            return override_role

        metadata = getattr(runnable, "metadata", None)
        if isinstance(metadata, Mapping):
            role = metadata.get("role") or metadata.get("tag")
            if isinstance(role, str):
                return role

        if "_" in node_name:
            return node_name.split("_")[0]
        return node_name

    @classmethod
    def _wrap_node(
        cls,
        *,
        node_name: str,
        role: str,
        runnable: Any,
        successors: Sequence[str],
        nodespec_target: Optional[Callable[..., Any]] = None,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        nodespec_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> Callable[..., Any]:
        from codon.instrumentation.langgraph import track_node

        runnable = cls._unwrap_runnable(runnable)

        decorator = track_node(
            node_name=node_name,
            role=role,
            model_name=model_name,
            model_version=model_version,
            introspection_target=nodespec_target,
            nodespec_kwargs=nodespec_kwargs,
        )

        async def invoke_callable(state: Any, config: Optional[Mapping[str, Any]]) -> Any:
            if hasattr(runnable, "ainvoke"):
                try:
                    if config:
                        return await runnable.ainvoke(state, config=config)
                    return await runnable.ainvoke(state)
                except TypeError:
                    return await runnable.ainvoke(state)
            if inspect.iscoroutinefunction(runnable):
                return await runnable(state)
            if hasattr(runnable, "invoke"):
                try:
                    if config:
                        result = runnable.invoke(state, config=config)
                    else:
                        result = runnable.invoke(state)
                except TypeError:
                    result = runnable.invoke(state)
                if inspect.isawaitable(result):
                    return await result
                return result
            if callable(runnable):
                result = runnable(state)
                if inspect.isawaitable(result):
                    return await result
                return result
            raise WorkloadRuntimeError(f"Node '{node_name}' is not callable")

        @decorator
        async def node_callable(message: Any, *, runtime, context):
            if isinstance(message, Mapping) and "state" in message:
                state = message["state"]
            else:
                state = message

            workload = getattr(runtime, "_workload", None)
            base_config = None
            if workload is not None:
                base_config = getattr(workload, "langgraph_runtime_config", None)
            invocation_config = context.get("langgraph_config") if isinstance(context, Mapping) else None
            config = _merge_runtime_configs(base_config, invocation_config)

            result = await invoke_callable(state, config)

            if isinstance(result, Mapping):
                next_state: JsonDict = {**state, **result}
            else:
                next_state = {"value": result}

            for target in successors:
                runtime.emit(target, {"state": next_state})

            return next_state

        return node_callable

    @staticmethod
    def _unwrap_runnable(runnable: Any) -> Any:
        """Attempt to peel wrappers to find the actual callable runnable."""

        seen: set[int] = set()
        current = runnable

        while True:
            if current is None:
                break

            identifier = id(current)
            if identifier in seen:
                break
            seen.add(identifier)

            if hasattr(current, "ainvoke") or hasattr(current, "invoke") or callable(current):
                return current

            candidate = None
            for attr in ("callable", "node", "value", "wrapped", "inner", "runnable"):
                if hasattr(current, attr):
                    candidate = getattr(current, attr)
                    if candidate is not current:
                        break

            if candidate is None and isinstance(current, Mapping):
                for key in ("callable", "node", "value", "runnable"):
                    if key in current:
                        candidate = current[key]
                        if candidate is not current:
                            break

            if candidate is None:
                break

            current = candidate

        return runnable

    @staticmethod
    def _build_successor_map(edges: Sequence[Tuple[str, str]]) -> Dict[str, Sequence[str]]:
        successors: Dict[str, list] = defaultdict(list)
        for src, dst in edges:
            successors[src].append(dst)
        return {k: tuple(v) for k, v in successors.items()}

    @staticmethod
    def _build_predecessor_map(edges: Sequence[Tuple[str, str]]) -> Dict[str, Sequence[str]]:
        predecessors: Dict[str, list] = defaultdict(list)
        for src, dst in edges:
            predecessors[dst].append(src)
        return {k: tuple(v) for k, v in predecessors.items()}
