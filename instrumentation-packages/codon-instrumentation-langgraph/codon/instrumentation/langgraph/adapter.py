"""LangGraph integration helpers for Codon Workloads."""
from __future__ import annotations

import inspect
import json
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from codon_sdk.agents import CodonWorkload
from codon_sdk.agents.codon_workload import WorkloadRuntimeError

try:  # pragma: no cover - we do not require langgraph at install time
    from langgraph.graph import StateGraph  # type: ignore
except Exception:  # pragma: no cover
    StateGraph = Any  # fallback for type checkers

JsonDict = Dict[str, Any]
RawNodeMap = Mapping[str, Any]
RawEdgeIterable = Iterable[Tuple[str, str]]


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
        role_overrides: Optional[Mapping[str, str]] = None,
        entry_nodes: Optional[Sequence[str]] = None,
        max_reviews: Optional[int] = None,
    ) -> CodonWorkload:
        """Create a :class:`CodonWorkload` from a LangGraph ``StateGraph``."""

        compiled, raw_nodes, raw_edges = cls._normalise_graph(graph)
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

        role_overrides = role_overrides or {}

        for node_name, runnable in node_map.items():
            role = cls._derive_role(node_name, runnable, role_overrides)
            instrumented_callable = cls._wrap_node(
                node_name=node_name,
                role=role,
                runnable=runnable,
                successors=tuple(successors.get(node_name, ())),
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

        workload._langgraph_compiled = compiled

        return workload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_graph(graph: Any) -> Tuple[Any, Any, Any]:
        """Return compiled graph plus raw node/edge structures."""

        raw_nodes, raw_edges = LangGraphWorkloadAdapter._extract_nodes_edges(graph)
        compiled = graph
        if hasattr(graph, "compile"):
            compiled = graph.compile()
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
            return dict(nodes)

        result: Dict[str, Any] = {}
        for item in nodes:
            name = None
            runnable = None

            if isinstance(item, tuple):
                if len(item) >= 2:
                    name, data = item[0], item[1]
                    if callable(data):
                        runnable = data
                    elif isinstance(data, Mapping):
                        runnable = data.get("callable") or data.get("node") or data.get("value")
                if runnable is None and len(item) >= 2 and hasattr(item[1], "node"):
                    runnable = getattr(item[1], "node")
            else:
                name = getattr(item, "name", None) or getattr(item, "key", None)
                runnable = (
                    getattr(item, "callable", None)
                    or getattr(item, "node", None)
                    or getattr(item, "value", None)
                )

            if name is None or runnable is None:
                raise ValueError(f"Cannot determine callable for LangGraph node entry: {item!r}")

            result[name] = runnable

        return result

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
        overrides: Mapping[str, str],
    ) -> str:
        if node_name in overrides:
            return overrides[node_name]

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
    ) -> Callable[..., Any]:
        from codon.instrumentation.langgraph import track_node

        decorator = track_node(node_name=node_name, role=role)

        async def invoke_callable(state: Any) -> Any:
            if hasattr(runnable, "ainvoke"):
                return await runnable.ainvoke(state)
            if inspect.iscoroutinefunction(runnable):
                return await runnable(state)
            if hasattr(runnable, "invoke"):
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

            result = await invoke_callable(state)

            if isinstance(result, Mapping):
                next_state: JsonDict = {**state, **result}
            else:
                next_state = {"value": result}

            for target in successors:
                runtime.emit(target, {"state": next_state})

            return next_state

        return node_callable

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
