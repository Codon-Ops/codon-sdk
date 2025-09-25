"""Concrete Workload implementation for Codon's opinionated agent framework."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from uuid import uuid4

from codon_sdk.instrumentation.schemas.logic_id import (
    AgentClass,
    LogicRequest,
    NodeEdge,
    Topology,
    generate_logic_id,
)
from codon_sdk.instrumentation.schemas.nodespec import NodeSpec

from .workload import Workload

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Token:
    """A unit of work travelling between nodes."""

    id: str
    payload: Any
    origin: str
    parent_id: Optional[str]
    lineage: Tuple[str, ...]
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class AuditEvent:
    """Structured record for audit and provenance."""

    event_type: str
    timestamp: datetime
    token_id: str
    source_node: Optional[str]
    target_node: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeExecutionRecord:
    """Captures a single node activation."""

    node: str
    token_id: str
    result: Any
    started_at: datetime
    finished_at: datetime


@dataclass
class ExecutionReport:
    """Execution summary returned by :meth:`CodonWorkload.execute`."""

    results: Dict[str, List[NodeExecutionRecord]]
    ledger: List[AuditEvent]
    run_id: str
    context: Dict[str, Any]

    def node_results(self, node: str) -> List[Any]:
        return [record.result for record in self.results.get(node, [])]


class WorkloadRegistrationError(RuntimeError):
    """Raised when workload registration or graph mutations are invalid."""


class WorkloadRuntimeError(RuntimeError):
    """Raised when runtime execution fails."""


class _RuntimeHandle:
    """Utility handed to node functions for dispatch and audit hooks."""

    def __init__(
        self,
        *,
        workload: "CodonWorkload",
        current_node: str,
        token: Token,
        enqueue,
        ledger: List[AuditEvent],
        state: Dict[str, Any],
    ) -> None:
        self._workload = workload
        self._current_node = current_node
        self._token = token
        self._enqueue = enqueue
        self._ledger = ledger
        self._state = state
        self._stop_requested = False
        self._emissions = 0

    @property
    def state(self) -> Dict[str, Any]:
        """Shared mutable state for the current workload run."""

        return self._state

    def emit(
        self,
        target_node: str,
        payload: Any,
        *,
        audit_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        if target_node not in self._workload._node_specs:
            raise WorkloadRuntimeError(f"Unknown target node '{target_node}'")

        allowed_targets = self._workload._successors[self._current_node]
        if target_node not in allowed_targets:
            raise WorkloadRuntimeError(
                f"Edge '{self._current_node}->{target_node}' is not registered"
            )

        child_token = Token(
            id=str(uuid4()),
            payload=payload,
            origin=self._current_node,
            parent_id=self._token.id,
            lineage=self._token.lineage + (self._current_node,),
        )
        self._enqueue(
            self._current_node,
            target_node,
            child_token,
            audit_metadata=audit_metadata or {},
        )
        self._emissions += 1
        return child_token.id

    def record_event(
        self,
        event_type: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._ledger.append(
            AuditEvent(
                event_type=event_type,
                timestamp=_utcnow(),
                token_id=self._token.id,
                source_node=self._current_node,
                target_node=None,
                metadata=metadata or {},
            )
        )

    def stop(self) -> None:
        self._stop_requested = True

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def emissions(self) -> int:
        return self._emissions


class CodonWorkload(Workload):
    """Default Workload implementation for authoring agents from scratch."""

    def __init__(
        self,
        *,
        name: str,
        version: str,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> None:
        self._node_specs: Dict[str, NodeSpec] = {}
        self._node_functions: Dict[str, Callable[..., Any]] = {}
        self._edges: Set[Tuple[str, str]] = set()
        self._predecessors: DefaultDict[str, Set[str]] = defaultdict(set)
        self._successors: DefaultDict[str, Set[str]] = defaultdict(set)
        self._agent_class_id: Optional[str] = None
        self._logic_id: Optional[str] = None
        self._entry_nodes: Optional[List[str]] = None
        super().__init__(
            name=name,
            version=version,
            description=description,
            tags=tags,
        )

    @property
    def agent_class_id(self) -> str:
        if self._agent_class_id is None:
            raise WorkloadRegistrationError("Agent class ID has not been computed")
        return self._agent_class_id

    @property
    def logic_id(self) -> str:
        if self._logic_id is None:
            raise WorkloadRegistrationError("Logic ID has not been computed")
        return self._logic_id

    @property
    def nodes(self) -> Sequence[NodeSpec]:
        return tuple(self._node_specs.values())

    @property
    def topology(self) -> Iterable[Tuple[str, str]]:
        return tuple(sorted(self._edges))

    def _register_logic_group(self) -> None:
        self._agent_class_id = self._compute_agent_class_id()
        self._update_logic_identity()

    def add_node(
        self,
        function: Callable[..., Any],
        name: str,
        role: str,
        *,
        org_namespace: Optional[str] = None,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> NodeSpec:
        if name in self._node_specs:
            raise WorkloadRegistrationError(f"Node '{name}' already registered")

        nodespec = NodeSpec(
            name=name,
            role=role,
            callable=function,
            org_namespace=org_namespace,
            model_name=model_name,
            model_version=model_version,
        )
        self._node_specs[name] = nodespec
        self._node_functions[name] = function
        self._predecessors.setdefault(name, set())
        self._successors.setdefault(name, set())
        self._update_logic_identity()
        return nodespec

    def add_edge(self, source_name: str, destination_name: str) -> None:
        if source_name not in self._node_specs:
            raise WorkloadRegistrationError(f"Unknown source node '{source_name}'")
        if destination_name not in self._node_specs:
            raise WorkloadRegistrationError(
                f"Unknown destination node '{destination_name}'"
            )

        edge = (source_name, destination_name)
        if edge in self._edges:
            return

        self._edges.add(edge)
        self._successors[source_name].add(destination_name)
        self._predecessors[destination_name].add(source_name)
        self._update_logic_identity()

    def execute(
        self,
        payload: Any,
        *,
        deployment_id: str,
        entry_nodes: Optional[Sequence[str]] = None,
        max_steps: int = 1000,
        **kwargs: Any,
    ) -> ExecutionReport:
        if not deployment_id:
            raise ValueError("deployment_id is required when executing a workload")
        if not self._node_specs:
            raise WorkloadRuntimeError("No nodes have been registered")

        if entry_nodes is not None:
            active_entry_nodes = list(entry_nodes)
        elif self._entry_nodes:
            active_entry_nodes = list(self._entry_nodes)
        else:
            entry_candidates = [
                name for name, preds in self._predecessors.items() if not preds
            ]
            active_entry_nodes = entry_candidates or list(self._node_specs.keys())
        for node in active_entry_nodes:
            if node not in self._node_specs:
                raise WorkloadRuntimeError(f"Entry node '{node}' is not registered")

        run_id = str(uuid4())
        context: Dict[str, Any] = {
            "deployment_id": deployment_id,
            "workload_logic_id": self.logic_id,
            "run_id": run_id,
            **kwargs,
        }

        ledger: List[AuditEvent] = []
        records: DefaultDict[str, List[NodeExecutionRecord]] = defaultdict(list)
        queue: Deque[Tuple[str, Token]] = deque()
        state: Dict[str, Any] = {}

        def enqueue(
            source_node: Optional[str],
            target_node: str,
            token: Token,
            *,
            audit_metadata: Dict[str, Any],
        ) -> None:
            queue.append((target_node, token))
            ledger.append(
                AuditEvent(
                    event_type="token_enqueued",
                    timestamp=_utcnow(),
                    token_id=token.id,
                    source_node=source_node,
                    target_node=target_node,
                    metadata={
                        "payload_repr": repr(token.payload),
                        **audit_metadata,
                    },
                )
            )

        for node in active_entry_nodes:
            seed_token = Token(
                id=str(uuid4()),
                payload=payload,
                origin="__entry__",
                parent_id=None,
                lineage=(),
            )
            enqueue("__entry__", node, seed_token, audit_metadata={"seed": True})

        steps = 0

        while queue:
            node_name, token = queue.popleft()
            ledger.append(
                AuditEvent(
                    event_type="token_dequeued",
                    timestamp=_utcnow(),
                    token_id=token.id,
                    source_node=token.origin,
                    target_node=node_name,
                    metadata={"payload_repr": repr(token.payload)},
                )
            )

            if steps >= max_steps:
                raise WorkloadRuntimeError(
                    f"Maximum step count {max_steps} reached; possible infinite loop"
                )
            steps += 1

            node_callable = self._node_functions[node_name]
            handle = _RuntimeHandle(
                workload=self,
                current_node=node_name,
                token=token,
                enqueue=enqueue,
                ledger=ledger,
                state=state,
            )

            started_at = _utcnow()
            try:
                result = node_callable(token.payload, runtime=handle, context=context)
            except Exception as exc:  # pragma: no cover
                ledger.append(
                    AuditEvent(
                        event_type="node_failed",
                        timestamp=_utcnow(),
                        token_id=token.id,
                        source_node=node_name,
                        target_node=None,
                        metadata={"exception": repr(exc)},
                    )
                )
                raise WorkloadRuntimeError(
                    f"Node '{node_name}' execution failed"
                ) from exc
            finished_at = _utcnow()

            records[node_name].append(
                NodeExecutionRecord(
                    node=node_name,
                    token_id=token.id,
                    result=result,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )

            ledger.append(
                AuditEvent(
                    event_type="node_completed",
                    timestamp=_utcnow(),
                    token_id=token.id,
                    source_node=node_name,
                    target_node=None,
                    metadata={
                        "result_repr": repr(result),
                        "emissions": handle.emissions,
                    },
                )
            )

            if handle.stop_requested:
                ledger.append(
                    AuditEvent(
                        event_type="runtime_stopped",
                        timestamp=_utcnow(),
                        token_id=token.id,
                        source_node=node_name,
                        target_node=None,
                        metadata={"reason": "stop_requested"},
                    )
                )
                break

        return ExecutionReport(
            results=dict(records),
            ledger=ledger,
            run_id=run_id,
            context=context,
        )

    def _compute_agent_class_id(self) -> str:
        meta = self.metadata
        slug = meta.name.strip().lower().replace(" ", "-")
        return f"{slug}:{meta.version}"

    def _update_logic_identity(self) -> None:
        agent_class = AgentClass(
            name=self.metadata.name,
            version=self.metadata.version,
            description=self.metadata.description or "",
        )
        topology = Topology(
            edges=[
                NodeEdge(
                    source_nodespec_id=self._node_specs[src].id,
                    target_nodespec_id=self._node_specs[dest].id,
                )
                for src, dest in sorted(self._edges)
            ]
        )
        request = LogicRequest(
            agent_class=agent_class,
            nodes=list(self._node_specs.values()),
            topology=topology,
        )
        self._logic_id = generate_logic_id(request)
