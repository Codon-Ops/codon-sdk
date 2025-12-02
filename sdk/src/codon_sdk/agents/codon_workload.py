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

"""Concrete Workload implementation for Codon's opinionated agent framework."""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import threading
import queue
from collections import defaultdict, deque
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Deque,
    DefaultDict,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from codon_sdk.instrumentation.schemas.logic_id import (
    AgentClass,
    LogicRequest,
    NodeEdge,
    Topology,
    generate_logic_id,
)
from codon_sdk.instrumentation.schemas.nodespec import NodeSpec, NodeSpecSpanAttributes
from codon_sdk.instrumentation.telemetry import NodeTelemetryPayload
from codon_sdk.instrumentation.schemas.telemetry.spans import CodonBaseSpanAttributes

from .workload import Workload

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _render_payload(value: Any, *, max_length: int = 2048) -> str:
    try:
        rendered = repr(value)
    except Exception as exc:  # pragma: no cover - defensive path
        rendered = f"<unrepresentable {type(value).__name__}: {exc}>"
    if len(rendered) > max_length:
        return rendered[: max_length - 3] + "..."
    return rendered


def _apply_nodespec_attributes(span, nodespec: NodeSpec) -> None:
    span.set_attribute(NodeSpecSpanAttributes.ID.value, nodespec.id)
    span.set_attribute(NodeSpecSpanAttributes.Version.value, nodespec.spec_version)
    span.set_attribute(NodeSpecSpanAttributes.Name.value, nodespec.name)
    span.set_attribute(NodeSpecSpanAttributes.Role.value, nodespec.role)
    span.set_attribute(
        NodeSpecSpanAttributes.CallableSignature.value,
        nodespec.callable_signature,
    )
    span.set_attribute(
        NodeSpecSpanAttributes.InputSchema.value,
        nodespec.input_schema,
    )
    if nodespec.output_schema is not None:
        span.set_attribute(
            NodeSpecSpanAttributes.OutputSchema.value,
            nodespec.output_schema,
        )
    if nodespec.model_name:
        span.set_attribute(NodeSpecSpanAttributes.ModelName.value, nodespec.model_name)
    if nodespec.model_version:
        span.set_attribute(
            NodeSpecSpanAttributes.ModelVersion.value,
            nodespec.model_version,
        )


def _apply_workload_attributes(
    span, *, telemetry: NodeTelemetryPayload, nodespec: NodeSpec, context: Dict[str, Any]
) -> None:
    span.set_attribute(CodonBaseSpanAttributes.AgentFramework.value, "codon")
    organization = (
        telemetry.organization_id
        or telemetry.org_namespace
        or context.get("organization_id")
        or context.get("org_namespace")
        or nodespec.org_namespace
        or os.getenv("ORG_NAMESPACE")
    )
    if organization:
        span.set_attribute(CodonBaseSpanAttributes.OrganizationId.value, organization)
        span.set_attribute(CodonBaseSpanAttributes.OrgNamespace.value, organization)

    workload_id = telemetry.workload_id or context.get("workload_id")
    logic_id = telemetry.workload_logic_id or context.get("logic_id")
    run_id = telemetry.workload_run_id or context.get("workload_run_id")
    deployment_id = telemetry.deployment_id or context.get("deployment_id")

    if workload_id:
        span.set_attribute(CodonBaseSpanAttributes.WorkloadId.value, workload_id)
    if logic_id:
        span.set_attribute(CodonBaseSpanAttributes.WorkloadLogicId.value, logic_id)
    if run_id:
        span.set_attribute(CodonBaseSpanAttributes.WorkloadRunId.value, run_id)
    if deployment_id:
        span.set_attribute(CodonBaseSpanAttributes.DeploymentId.value, deployment_id)

    if telemetry.workload_name or context.get("workload_name"):
        span.set_attribute(
            CodonBaseSpanAttributes.WorkloadName.value,
            telemetry.workload_name or context.get("workload_name"),
        )
    if telemetry.workload_version or context.get("workload_version"):
        span.set_attribute(
            CodonBaseSpanAttributes.WorkloadVersion.value,
            telemetry.workload_version or context.get("workload_version"),
        )

    span.set_attribute(CodonBaseSpanAttributes.NodeStatusCode.value, telemetry.status_code)
    if telemetry.error_message:
        span.set_attribute(CodonBaseSpanAttributes.NodeErrorMessage.value, telemetry.error_message)

    if telemetry.node_input is not None:
        span.set_attribute(CodonBaseSpanAttributes.NodeInput.value, telemetry.node_input)
    if telemetry.node_output is not None:
        span.set_attribute(CodonBaseSpanAttributes.NodeOutput.value, telemetry.node_output)
    if telemetry.duration_ms is not None:
        span.set_attribute(CodonBaseSpanAttributes.NodeLatencyMs.value, telemetry.duration_ms)

    if telemetry.model_vendor:
        span.set_attribute(CodonBaseSpanAttributes.ModelVendor.value, telemetry.model_vendor)
    if telemetry.model_identifier:
        span.set_attribute(CodonBaseSpanAttributes.ModelIdentifier.value, telemetry.model_identifier)

    if telemetry.input_tokens is not None:
        span.set_attribute(CodonBaseSpanAttributes.TokenInput.value, telemetry.input_tokens)
    if telemetry.output_tokens is not None:
        span.set_attribute(CodonBaseSpanAttributes.TokenOutput.value, telemetry.output_tokens)
    if telemetry.total_tokens is not None:
        span.set_attribute(CodonBaseSpanAttributes.TokenTotal.value, telemetry.total_tokens)


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


@dataclass(frozen=True)
class StreamEvent:
    """Event emitted while a workload is executing."""

    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class ExecutionReport:
    """Execution summary returned by :meth:`CodonWorkload.execute`."""

    results: Dict[str, List[NodeExecutionRecord]]
    ledger: List[AuditEvent]
    run_id: str
    context: Dict[str, Any]

    def node_results(self, node: str) -> List[Any]:
        return [record.result for record in self.results.get(node, [])]


def _run_coroutine_sync(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run a coroutine and return its result, regardless of active event loop."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    result_box: Dict[str, Any] = {}
    exc_box: Dict[str, BaseException] = {}

    def runner() -> None:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            result_box["result"] = new_loop.run_until_complete(coro_factory())
        except BaseException as exc:  # propagate original exception
            exc_box["exc"] = exc
        finally:
            new_loop.close()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "exc" in exc_box:
        raise exc_box["exc"]

    return result_box.get("result")


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
        telemetry: NodeTelemetryPayload,
        schedule_event: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        self._workload = workload
        self._current_node = current_node
        self._token = token
        self._enqueue = enqueue
        self._ledger = ledger
        self._state = state
        self._stop_requested = False
        self._emissions = 0
        self._telemetry = telemetry
        self._schedule_event = schedule_event

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
        self._schedule_event(
            "runtime_event",
            {
                "node": self._current_node,
                "token_id": self._token.id,
                "event_type": event_type,
                "metadata": metadata or {},
            },
        )

    def stop(self) -> None:
        self._stop_requested = True

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def emissions(self) -> int:
        return self._emissions

    @property
    def telemetry(self) -> NodeTelemetryPayload:
        """Mutable telemetry payload for the current node invocation."""

        return self._telemetry


class CodonWorkload(Workload):
    """Default Workload implementation for authoring agents from scratch."""

    def __init__(
        self,
        *,
        name: str,
        version: str,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        enable_tracing: bool = False,
    ) -> None:
        """Initialize workload with metadata.

        Args:
            name: Unique identifier for the workload type.
            version: Semantic version (e.g., "1.2.0").
            description: Human-readable purpose description.
            tags: Categorization tags.
            enable_tracing: When True, emit OpenTelemetry spans directly from the
                CodonWorkload runtime. Defaults to False to avoid double
                instrumentation when external wrappers (e.g., LangGraph) are used.
        """
        self._node_specs: Dict[str, NodeSpec] = {}
        self._node_functions: Dict[str, Callable[..., Any]] = {}
        self._edges: Set[Tuple[str, str]] = set()
        self._predecessors: DefaultDict[str, Set[str]] = defaultdict(set)
        self._successors: DefaultDict[str, Set[str]] = defaultdict(set)
        self._agent_class_id: Optional[str] = None
        self._logic_id: Optional[str] = None
        self._entry_nodes: Optional[List[str]] = None
        self._organization_id: Optional[str] = os.getenv("ORG_NAMESPACE")
        self._enable_tracing = enable_tracing
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
    def organization_id(self) -> Optional[str]:
        if self._organization_id:
            return self._organization_id
        if self._node_specs:
            return next(iter(self._node_specs.values())).org_namespace
        return os.getenv("ORG_NAMESPACE")

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
        """Add a node (computational step) to the workload.

        Args:
            function: The Python function to execute for this node.
            name: Unique identifier for this node within the workload.
            role: The node's role in the workflow (e.g., "processor", "validator").
            org_namespace: Organization namespace for scoping. Defaults to ORG_NAMESPACE env var.
            model_name: Optional model identifier if this node uses an AI model.
            model_version: Optional model version if this node uses an AI model.

        Returns:
            The generated NodeSpec with a unique ID.

        Raises:
            WorkloadRegistrationError: If a node with this name already exists.
        """
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
        self._organization_id = nodespec.org_namespace
        self._update_logic_identity()
        return nodespec

    def add_edge(self, source_name: str, destination_name: str) -> None:
        """Add an edge between two nodes in the workload.

        Args:
            source_name: Name of the source node.
            destination_name: Name of the destination node.

        Raises:
            WorkloadRegistrationError: If either node name doesn't exist.

        TODO: Clarify what source_name and destination_name semantically represent
        TODO: Document whether this creates directed edges and how token flow works
        """
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

    async def execute_async(
        self,
        payload: Any,
        *,
        deployment_id: str,
        entry_nodes: Optional[Sequence[str]] = None,
        max_steps: int = 1000,
        event_handler: Optional[Callable[[StreamEvent], Awaitable[None]]] = None,
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
            "logic_id": self.logic_id,
            "workload_id": self.agent_class_id,
            "workload_run_id": run_id,
            "run_id": run_id,
            "workload_name": self.metadata.name,
            "organization_id": self.organization_id,
            "org_namespace": self.organization_id,
            "workload_version": self.metadata.version,
            **kwargs,
        }

        ledger: List[AuditEvent] = []
        records: DefaultDict[str, List[NodeExecutionRecord]] = defaultdict(list)
        queue_deque: Deque[Tuple[str, Token]] = deque()
        state: Dict[str, Any] = {}

        loop = asyncio.get_running_loop()
        tracer = trace.get_tracer(__name__) if self._enable_tracing else None

        async def publish_event(event_type: str, **data: Any) -> None:
            if event_handler is None:
                return
            await event_handler(StreamEvent(event_type=event_type, data=data))

        def schedule_event(event_type: str, data: Dict[str, Any]) -> None:
            if event_handler is None:
                return
            loop.create_task(event_handler(StreamEvent(event_type=event_type, data=data)))

        def enqueue(
            source_node: Optional[str],
            target_node: str,
            token: Token,
            *,
            audit_metadata: Dict[str, Any],
        ) -> None:
            queue_deque.append((target_node, token))
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
            schedule_event(
                "token_enqueued",
                {
                    "source_node": source_node,
                    "target_node": target_node,
                    "token_id": token.id,
                    "payload": token.payload,
                    "metadata": {"payload_repr": repr(token.payload), **audit_metadata},
                },
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

        while queue_deque:
            node_name, token = queue_deque.popleft()
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
            await publish_event(
                "token_dequeued",
                source_node=token.origin,
                target_node=node_name,
                token_id=token.id,
                payload=token.payload,
            )

            if steps >= max_steps:
                raise WorkloadRuntimeError(
                    f"Maximum step count {max_steps} reached; possible infinite loop"
                )
            steps += 1

            nodespec = self._node_specs[node_name]
            telemetry = NodeTelemetryPayload(
                workload_id=self.agent_class_id,
                workload_name=self.metadata.name,
                workload_version=self.metadata.version,
                workload_logic_id=self.logic_id,
                workload_run_id=run_id,
                deployment_id=deployment_id,
                organization_id=self.organization_id,
                org_namespace=self.organization_id,
                nodespec_id=nodespec.id,
                node_name=nodespec.name,
                node_role=nodespec.role,
                model_name=nodespec.model_name,
            )
            telemetry.node_input = _render_payload(token.payload)

            node_callable = self._node_functions[node_name]
            handle = _RuntimeHandle(
                workload=self,
                current_node=node_name,
                token=token,
                enqueue=enqueue,
                ledger=ledger,
                state=state,
                telemetry=telemetry,
                schedule_event=schedule_event,
            )

            started_at = _utcnow()
            span_ctx = (
                tracer.start_as_current_span(f"codon.node.{node_name}")
                if tracer
                else contextlib.nullcontext()
            )
            await publish_event(
                "node_started",
                node=node_name,
                token_id=token.id,
                payload=token.payload,
            )
            with span_ctx as span:
                if span is not None:
                    _apply_nodespec_attributes(span, nodespec)
                    _apply_workload_attributes(span, telemetry=telemetry, nodespec=nodespec, context=context)
                try:
                    result = node_callable(token.payload, runtime=handle, context=context)
                    if inspect.isawaitable(result):
                        result = await result  # type: ignore[assignment]
                except Exception as exc:  # pragma: no cover
                    telemetry.status_code = "ERROR"
                    telemetry.error_message = repr(exc)
                    if span is not None:
                        _apply_workload_attributes(span, telemetry=telemetry, nodespec=nodespec, context=context)
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
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
                    schedule_event(
                        "node_failed",
                        {
                            "node": node_name,
                            "token_id": token.id,
                            "exception": repr(exc),
                        },
                    )
                    raise WorkloadRuntimeError(
                        f"Node '{node_name}' execution failed"
                    ) from exc
                finished_at = _utcnow()
                telemetry.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
                telemetry.status_code = "OK"
                telemetry.node_output = _render_payload(result)
                if span is not None:
                    _apply_workload_attributes(span, telemetry=telemetry, nodespec=nodespec, context=context)
                    span.set_status(Status(StatusCode.OK))

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
                        "result_repr": telemetry.node_output,
                        "emissions": handle.emissions,
                    },
                )
            )
            await publish_event(
                "node_completed",
                node=node_name,
                token_id=token.id,
                result=result,
                emissions=handle.emissions,
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
                schedule_event(
                    "runtime_stopped",
                    {
                        "node": node_name,
                        "token_id": token.id,
                        "reason": "stop_requested",
                    },
                )
                break

        report = ExecutionReport(
            results=dict(records),
            ledger=ledger,
            run_id=run_id,
            context=context,
        )
        await publish_event("workflow_finished", report=report)
        return report

    def execute(
        self,
        payload: Any,
        *,
        deployment_id: str,
        entry_nodes: Optional[Sequence[str]] = None,
        max_steps: int = 1000,
        **kwargs: Any,
    ) -> ExecutionReport:
        return _run_coroutine_sync(
            lambda: self.execute_async(
                payload,
                deployment_id=deployment_id,
                entry_nodes=entry_nodes,
                max_steps=max_steps,
                **kwargs,
            )
        )

    async def execute_streaming_async(
        self,
        payload: Any,
        *,
        deployment_id: str,
        entry_nodes: Optional[Sequence[str]] = None,
        max_steps: int = 1000,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        queue_async: asyncio.Queue[Any] = asyncio.Queue()
        sentinel = object()
        error: List[BaseException] = []

        async def handler(event: StreamEvent) -> None:
            await queue_async.put(event)

        async def runner() -> None:
            try:
                await self.execute_async(
                    payload,
                    deployment_id=deployment_id,
                    entry_nodes=entry_nodes,
                    max_steps=max_steps,
                    event_handler=handler,
                    **kwargs,
                )
            except Exception as exc:  # pragma: no cover - surfaced to consumer
                error.append(exc)
            finally:
                await queue_async.put(sentinel)

        task = asyncio.create_task(runner())

        try:
            while True:
                item = await queue_async.get()
                if item is sentinel:
                    break
                yield item
            if error:
                raise error[0]
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(Exception):
                    await task

    def execute_streaming(
        self,
        payload: Any,
        *,
        deployment_id: str,
        entry_nodes: Optional[Sequence[str]] = None,
        max_steps: int = 1000,
        **kwargs: Any,
    ) -> Iterator[StreamEvent]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "execute_streaming cannot be called from an active event loop; "
                "use execute_streaming_async instead"
            )

        q: "queue.Queue[Any]" = queue.Queue()
        sentinel = object()
        error: List[BaseException] = []

        async def producer() -> None:
            try:
                async for event in self.execute_streaming_async(
                    payload,
                    deployment_id=deployment_id,
                    entry_nodes=entry_nodes,
                    max_steps=max_steps,
                    **kwargs,
                ):
                    q.put(event)
            except Exception as exc:  # pragma: no cover - surfaced to consumer
                error.append(exc)
            finally:
                q.put(sentinel)

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(producer())
            finally:
                loop.close()

        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        try:
            while True:
                item = q.get()
                if item is sentinel:
                    break
                yield item
            if error:
                raise error[0]
        finally:
            thread.join()

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
