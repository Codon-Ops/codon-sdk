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

import hashlib
import logging
import inspect
import json
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from codon_sdk.agents import CodonWorkload
from codon_sdk.instrumentation.schemas.telemetry.spans import (
    CodonBaseSpanAttributes,
    CodonGraphSpanAttributes,
    CodonSpanNames,
)
from codon_sdk.instrumentation.schemas.nodespec import (
    _RESOLVED_ORG_ID,
    _RESOLVED_ORG_NAMESPACE,
)
from opentelemetry import trace

from .context import (
    GraphInvocationContext,
    _ACTIVE_CONFIG,
    _ACTIVE_GRAPH_CONTEXT,
    current_langgraph_config,
)
from codon_sdk.agents.codon_workload import WorkloadRuntimeError

from .callbacks import (
    BoundInvocationTelemetryCallback,
    LangGraphNodeSpanCallback,
    LangGraphTelemetryCallback,
    _lookup_invocation_metadata,
)
from . import current_invocation

try:  # pragma: no cover - we do not require langgraph at install time
    from langgraph.graph import StateGraph  # type: ignore
except Exception:  # pragma: no cover
    StateGraph = Any  # fallback for type checkers

JsonDict = Dict[str, Any]
RawNodeMap = Mapping[str, Any]
RawEdgeIterable = Iterable[Tuple[str, str]]


def _ensure_callback_list(value: Any) -> List[Any]:
    if value is None:
        return []
    handlers = getattr(value, "handlers", None)
    if handlers is not None:
        return list(handlers)
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _wrap_runnable(value: Any) -> Any:
    if isinstance(value, _RunnableConfigWrapper):
        return value
    if not (hasattr(value, "invoke") or hasattr(value, "ainvoke")):
        return value
    return _RunnableConfigWrapper(value)


def _extract_invocation_from_config(config: Mapping[str, Any]) -> Optional[Any]:
    metadata = config.get("metadata")
    if isinstance(metadata, Mapping):
        invocation = metadata.get("codon_invocation")
        if invocation is not None:
            return invocation
    invocation = _lookup_invocation_metadata(config)
    if invocation is not None:
        return invocation
    return None


def _inject_bound_callback(config: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(config, Mapping):
        return config
    invocation = _extract_invocation_from_config(config) or current_invocation()
    if os.getenv("CODON_LANGGRAPH_DEBUG_USAGE") == "1":
        logger = logging.getLogger(__name__)
        logger.info(
            "codon.langgraph usage debug: inject_bound_callback invocation_present=%s metadata_keys=%s",
            bool(invocation),
            sorted(config.get("metadata", {}).keys())
            if isinstance(config.get("metadata"), Mapping)
            else None,
        )
    if not invocation:
        return config
    callbacks = _ensure_callback_list(config.get("callbacks"))
    callbacks = [
        cb for cb in callbacks if not isinstance(cb, BoundInvocationTelemetryCallback)
    ]
    invocation.extra_attributes.setdefault("codon_span_defer", True)
    updated = dict(config)
    updated["callbacks"] = callbacks + [BoundInvocationTelemetryCallback(invocation)]
    return updated


def _ensure_codon_run_metadata(config: Mapping[str, Any], run_id: str) -> None:
    if not isinstance(config, dict):
        return
    metadata = config.get("metadata")
    if not isinstance(metadata, dict):
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        config["metadata"] = metadata
    metadata.setdefault("codon_run_id", run_id)


def _normalize_org_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value if value.startswith("ORG_") else None


def _resource_org_id() -> Optional[str]:
    provider = trace.get_tracer_provider()
    resource = getattr(provider, "resource", None)
    if not resource:
        return None
    attributes = getattr(resource, "attributes", None)
    if not isinstance(attributes, Mapping):
        return None
    candidate = attributes.get(CodonBaseSpanAttributes.OrganizationId.value) or attributes.get(
        "codon.organization.id"
    )
    if isinstance(candidate, str) and candidate.startswith("ORG_"):
        return candidate
    return None


def _wrap_config_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        wrapped: Dict[str, Any] = {}
        for key, item in value.items():
            if key == "callbacks":
                wrapped[key] = item
            else:
                wrapped[key] = _wrap_config_values(item)
        return wrapped
    if isinstance(value, list):
        return [_wrap_config_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_wrap_config_values(item) for item in value)
    return _wrap_runnable(value)


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
                callbacks.extend(_ensure_callback_list(value))
            else:
                merged[key] = value

    if not any(isinstance(cb, LangGraphNodeSpanCallback) for cb in callbacks):
        callbacks.append(LangGraphNodeSpanCallback())
    if not any(isinstance(cb, LangGraphTelemetryCallback) for cb in callbacks):
        callbacks.append(LangGraphTelemetryCallback())
    merged["callbacks"] = callbacks
    return _wrap_config_values(merged)


class _RunnableConfigWrapper:
    def __init__(self, runnable: Any) -> None:
        self._runnable = runnable

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runnable, name)

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("config") is None:
            config = current_langgraph_config()
            if config is not None:
                kwargs = dict(kwargs)
                kwargs["config"] = _inject_bound_callback(config)
        try:
            if kwargs.get("config") is not None:
                kwargs = dict(kwargs)
                kwargs["config"] = _inject_bound_callback(kwargs["config"])
            return self._runnable.invoke(*args, **kwargs)
        except TypeError:
            kwargs.pop("config", None)
            return self._runnable.invoke(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("config") is None:
            config = current_langgraph_config()
            if config is not None:
                kwargs = dict(kwargs)
                kwargs["config"] = _inject_bound_callback(config)
        try:
            if kwargs.get("config") is not None:
                kwargs = dict(kwargs)
                kwargs["config"] = _inject_bound_callback(kwargs["config"])
            return await self._runnable.ainvoke(*args, **kwargs)
        except TypeError:
            kwargs.pop("config", None)
            return await self._runnable.ainvoke(*args, **kwargs)


def _resolve_deployment_id(config: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not config:
        return None
    for key in ("deployment_id", "codon_deployment_id"):
        value = config.get(key)
        if value:
            return str(value)
    configurable = config.get("configurable")
    if isinstance(configurable, Mapping):
        value = configurable.get("deployment_id") or configurable.get("codon_deployment_id")
        if value:
            return str(value)
    metadata = config.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("deployment_id") or metadata.get("codon_deployment_id")
        if value:
            return str(value)
    return None


def _build_graph_definition(
    node_specs: Mapping[str, Any], edges: Sequence[Tuple[str, str]]
) -> Dict[str, Any]:
    nodes = []
    for name, spec in node_specs.items():
        nodes.append(
            {
                "name": name,
                "role": getattr(spec, "role", None),
                "nodespec_id": getattr(spec, "id", None),
            }
        )
    return {
        "nodes": nodes,
        "edges": [{"source": src, "target": dst} for src, dst in edges],
    }


def _hash_graph_definition(definition: Mapping[str, Any]) -> str:
    payload = json.dumps(definition, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _WrappedLangGraph:
    def __init__(
        self,
        graph: Any,
        *,
        workload: CodonWorkload,
        node_specs: Mapping[str, Any],
        graph_definition: Optional[Dict[str, Any]],
        state_graph: Optional[Any] = None,
        compiled_graph: Optional[Any] = None,
        compile_kwargs: Optional[Mapping[str, Any]] = None,
        runtime_config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._graph = graph
        self.workload = workload
        self.node_specs = dict(node_specs)
        self.graph_definition = graph_definition
        self.runtime_config = dict(runtime_config or {})
        self.langgraph_state_graph = state_graph
        self.langgraph_compiled_graph = compiled_graph or graph
        self.langgraph_compile_kwargs = dict(compile_kwargs or {})
        self.langgraph_runtime_config = dict(runtime_config or {})

    def __getattr__(self, item: str) -> Any:
        return getattr(self._graph, item)

    def _emit_graph_span(self, run_context: GraphInvocationContext) -> None:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(CodonSpanNames.AgentGraph.value) as span:
            span.set_attribute(
                CodonBaseSpanAttributes.AgentFramework.value,
                "langgraph",
            )
            span.set_attribute(
                CodonBaseSpanAttributes.WorkloadId.value,
                run_context.workload.agent_class_id,
            )
            span.set_attribute(
                CodonBaseSpanAttributes.WorkloadLogicId.value,
                run_context.workload.logic_id,
            )
            span.set_attribute(
                CodonBaseSpanAttributes.WorkloadRunId.value,
                run_context.run_id,
            )
            span.set_attribute(
                CodonBaseSpanAttributes.WorkloadName.value,
                run_context.workload.metadata.name,
            )
            span.set_attribute(
                CodonBaseSpanAttributes.WorkloadVersion.value,
                run_context.workload.metadata.version,
            )
            if run_context.deployment_id:
                span.set_attribute(
                    CodonBaseSpanAttributes.DeploymentId.value,
                    run_context.deployment_id,
                )
            org_id = run_context.organization_id or _resource_org_id()
            if org_id:
                span.set_attribute(
                    CodonBaseSpanAttributes.OrganizationId.value,
                    org_id,
                )
            if run_context.org_namespace:
                span.set_attribute(
                    CodonBaseSpanAttributes.OrgNamespace.value,
                    run_context.org_namespace,
                )

            if self.graph_definition:
                definition_hash = _hash_graph_definition(self.graph_definition)
                span.set_attribute(
                    CodonGraphSpanAttributes.DefinitionHash.value,
                    definition_hash,
                )
                span.set_attribute(
                    CodonGraphSpanAttributes.NodeCount.value,
                    len(self.graph_definition.get("nodes", [])),
                )
                span.set_attribute(
                    CodonGraphSpanAttributes.EdgeCount.value,
                    len(self.graph_definition.get("edges", [])),
                )
                span.set_attribute(
                    CodonGraphSpanAttributes.DefinitionJson.value,
                    json.dumps(self.graph_definition, default=str),
                )

    def _invoke(self, *args: Any, config: Optional[Mapping[str, Any]] = None, **kwargs: Any):
        merged_config = _merge_runtime_configs(self.runtime_config, config)
        org_id = _normalize_org_id(_RESOLVED_ORG_ID) or _normalize_org_id(
            self.workload.organization_id
        )
        if org_id is None:
            org_id = _resource_org_id()
        org_namespace = (
            _RESOLVED_ORG_NAMESPACE
            or os.getenv("ORG_NAMESPACE")
            or self.workload.organization_id
        )
        run_context = GraphInvocationContext(
            workload=self.workload,
            node_specs=self.node_specs,
            run_id=str(uuid.uuid4()),
            deployment_id=_resolve_deployment_id(merged_config),
            organization_id=org_id,
            org_namespace=org_namespace,
            graph_definition=self.graph_definition,
        )
        _ensure_codon_run_metadata(merged_config, run_context.run_id)
        graph_token = _ACTIVE_GRAPH_CONTEXT.set(run_context)
        config_token = _ACTIVE_CONFIG.set(merged_config)
        try:
            self._emit_graph_span(run_context)
            try:
                return self._graph.invoke(*args, config=merged_config, **kwargs)
            except TypeError:
                return self._graph.invoke(*args, **kwargs)
        finally:
            _ACTIVE_GRAPH_CONTEXT.reset(graph_token)
            _ACTIVE_CONFIG.reset(config_token)

    async def _ainvoke(
        self, *args: Any, config: Optional[Mapping[str, Any]] = None, **kwargs: Any
    ):
        merged_config = _merge_runtime_configs(self.runtime_config, config)
        org_id = _normalize_org_id(_RESOLVED_ORG_ID) or _normalize_org_id(
            self.workload.organization_id
        )
        if org_id is None:
            org_id = _resource_org_id()
        org_namespace = (
            _RESOLVED_ORG_NAMESPACE
            or os.getenv("ORG_NAMESPACE")
            or self.workload.organization_id
        )
        run_context = GraphInvocationContext(
            workload=self.workload,
            node_specs=self.node_specs,
            run_id=str(uuid.uuid4()),
            deployment_id=_resolve_deployment_id(merged_config),
            organization_id=org_id,
            org_namespace=org_namespace,
            graph_definition=self.graph_definition,
        )
        _ensure_codon_run_metadata(merged_config, run_context.run_id)
        graph_token = _ACTIVE_GRAPH_CONTEXT.set(run_context)
        config_token = _ACTIVE_CONFIG.set(merged_config)
        try:
            self._emit_graph_span(run_context)
            try:
                return await self._graph.ainvoke(*args, config=merged_config, **kwargs)
            except TypeError:
                return await self._graph.ainvoke(*args, **kwargs)
        finally:
            _ACTIVE_GRAPH_CONTEXT.reset(graph_token)
            _ACTIVE_CONFIG.reset(config_token)

    def invoke(self, *args: Any, **kwargs: Any):
        return self._invoke(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any):
        return await self._ainvoke(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any):
        config = kwargs.pop("config", None)
        merged_config = _merge_runtime_configs(self.runtime_config, config)
        org_id = _normalize_org_id(_RESOLVED_ORG_ID) or _normalize_org_id(
            self.workload.organization_id
        )
        if org_id is None:
            org_id = _resource_org_id()
        org_namespace = (
            _RESOLVED_ORG_NAMESPACE
            or os.getenv("ORG_NAMESPACE")
            or self.workload.organization_id
        )
        run_context = GraphInvocationContext(
            workload=self.workload,
            node_specs=self.node_specs,
            run_id=str(uuid.uuid4()),
            deployment_id=_resolve_deployment_id(merged_config),
            organization_id=org_id,
            org_namespace=org_namespace,
            graph_definition=self.graph_definition,
        )
        _ensure_codon_run_metadata(merged_config, run_context.run_id)
        graph_token = _ACTIVE_GRAPH_CONTEXT.set(run_context)
        config_token = _ACTIVE_CONFIG.set(merged_config)
        self._emit_graph_span(run_context)

        def _iterator():
            try:
                try:
                    iterator = self._graph.stream(*args, config=merged_config, **kwargs)
                except TypeError:
                    iterator = self._graph.stream(*args, **kwargs)
                for item in iterator:
                    yield item
            finally:
                _ACTIVE_GRAPH_CONTEXT.reset(graph_token)
                _ACTIVE_CONFIG.reset(config_token)

        return _iterator()

    async def astream(self, *args: Any, **kwargs: Any):
        config = kwargs.pop("config", None)
        merged_config = _merge_runtime_configs(self.runtime_config, config)
        org_id = _normalize_org_id(_RESOLVED_ORG_ID) or _normalize_org_id(
            self.workload.organization_id
        )
        if org_id is None:
            org_id = _resource_org_id()
        org_namespace = (
            _RESOLVED_ORG_NAMESPACE
            or os.getenv("ORG_NAMESPACE")
            or self.workload.organization_id
        )
        run_context = GraphInvocationContext(
            workload=self.workload,
            node_specs=self.node_specs,
            run_id=str(uuid.uuid4()),
            deployment_id=_resolve_deployment_id(merged_config),
            organization_id=org_id,
            org_namespace=org_namespace,
            graph_definition=self.graph_definition,
        )
        _ensure_codon_run_metadata(merged_config, run_context.run_id)
        graph_token = _ACTIVE_GRAPH_CONTEXT.set(run_context)
        config_token = _ACTIVE_CONFIG.set(merged_config)
        self._emit_graph_span(run_context)

        async def _aiterator():
            try:
                try:
                    iterator = self._graph.astream(*args, config=merged_config, **kwargs)
                except TypeError:
                    iterator = self._graph.astream(*args, **kwargs)
                if inspect.isawaitable(iterator):
                    iterator = await iterator
                async for item in iterator:
                    yield item
            finally:
                _ACTIVE_GRAPH_CONTEXT.reset(graph_token)
                _ACTIVE_CONFIG.reset(config_token)

        return _aiterator()


@dataclass(frozen=True)
class LangGraphAdapterResult:
    """Artifacts produced when adapting a LangGraph graph."""

    workload: CodonWorkload
    state_graph: Any
    compiled_graph: Any
    wrapped_graph: Any


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
        edge_overrides: Optional[Sequence[Tuple[str, str]]] = None,
        entry_nodes: Optional[Sequence[str]] = None,
        max_reviews: Optional[int] = None,
        compile_kwargs: Optional[Mapping[str, Any]] = None,
        runtime_config: Optional[Mapping[str, Any]] = None,
        return_artifacts: bool = False,
    ) -> Union[Any, LangGraphAdapterResult]:
        """Wrap a LangGraph graph and return an instrumented graph.

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
            workload, the original state graph, the compiled graph, and the
            instrumented graph wrapper.
        """

        compiled, raw_nodes, raw_edges = cls._normalise_graph(
            graph, compile_kwargs=compile_kwargs
        )
        if edge_overrides is not None:
            raw_edges = edge_overrides
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

        node_specs = {spec.name: spec for spec in workload.nodes}
        graph_definition = _build_graph_definition(node_specs, valid_edges)
        wrapped_graph = _WrappedLangGraph(
            compiled,
            workload=workload,
            node_specs=node_specs,
            graph_definition=graph_definition,
            state_graph=graph,
            compiled_graph=compiled,
            compile_kwargs=compile_kwargs,
            runtime_config=runtime_config,
        )

        if return_artifacts:
            return LangGraphAdapterResult(
                workload=workload,
                state_graph=graph,
                compiled_graph=compiled,
                wrapped_graph=wrapped_graph,
            )

        return wrapped_graph

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

        if nodes is None:
            raise ValueError(
                "Unable to extract nodes from LangGraph graph. Pass the original StateGraph or ensure the compiled graph exposes config.nodes/config.edges."
            )
        if edges is None:
            edges = []

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
