"""LangGraph integration helpers for Codon Workloads."""
from __future__ import annotations

import inspect
import json
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from codon_sdk.agents import CodonWorkload
from codon_sdk.agents.codon_workload import WorkloadRuntimeError
from codon_sdk.instrumentation.schemas.nodespec import NodeSpec

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
        """Create a :class:`CodonWorkload` from a LangGraph ``StateGraph``.

        Args:
            graph: Either a ``StateGraph`` or an already-compiled LangGraph graph.
            name: Workload name.
            version: Workload version string.
            description: Optional workload description.
            tags: Optional workload tags.
            org_namespace: Optionally override the ``ORG_NAMESPACE`` used for node specs.
            role_overrides: Optional mapping from LangGraph node name to Codon node role.
            entry_nodes: Optional explicit entry node list. If omitted, the adapter
                infers entry nodes from nodes with no predecessors.
            max_reviews: Optional guardrail to pass along when building reflective
                workflows. Currently unused but reserved for future extensions.

        Returns:
            A fully registered :class:`CodonWorkload` instance.
        """

        compiled, raw_nodes, raw_edges = cls._normalise_graph(graph)

        workload = CodonWorkload(
            name=name,
            version=version,
            description=description,
            tags=tags,
        )

        successors: Dict[str, Sequence[str]] = cls._build_successor_map(raw_edges)
        predecessors: Dict[str, Sequence[str]] = cls._build_predecessor_map(raw_edges)

        role_overrides = role_overrides or {}

        for node_name, runnable in raw_nodes.items():
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

        for edge in raw_edges:
            workload.add_edge(*edge)

        workload._predecessors.update({k: set(v) for k, v in predecessors.items()})
        workload._successors.update({k: set(v) for k, v in successors.items()})

        if entry_nodes is not None:
            workload._entry_nodes = list(entry_nodes)
        else:
            inferred = [node for node, preds in predecessors.items() if not preds]
            workload._entry_nodes = inferred or list(raw_nodes.keys())

        workload._langgraph_compiled = compiled

        return workload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_graph(graph: Any) -> Tuple[Any, RawNodeMap, RawEdgeIterable]:
        compiled = graph
        if hasattr(graph, "compile"):
            compiled = graph.compile()

        nodes = None
        if hasattr(compiled, "graph") and hasattr(compiled.graph, "nodes"):
            nodes = compiled.graph.nodes
        elif hasattr(compiled, "nodes"):
            nodes = compiled.nodes
        if nodes is None:
            raise ValueError("Unable to extract nodes from LangGraph graph")

        try:
            edges = list(compiled.graph.edges)
        except AttributeError:
            try:
                edges = list(compiled.edges)
            except AttributeError:
                raise ValueError("Unable to extract edges from LangGraph graph")

        return compiled, nodes, edges

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
    def _build_successor_map(edges: RawEdgeIterable) -> Dict[str, Sequence[str]]:
        successors: Dict[str, list] = defaultdict(list)
        for src, dst in edges:
            successors[src].append(dst)
        return {k: tuple(v) for k, v in successors.items()}

    @staticmethod
    def _build_predecessor_map(edges: RawEdgeIterable) -> Dict[str, Sequence[str]]:
        predecessors: Dict[str, list] = defaultdict(list)
        for src, dst in edges:
            predecessors[dst].append(src)
        return {k: tuple(v) for k, v in predecessors.items()}
