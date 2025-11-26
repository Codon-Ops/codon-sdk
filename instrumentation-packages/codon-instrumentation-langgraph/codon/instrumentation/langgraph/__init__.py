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

import inspect
import json
import os
import time
from abc import ABC, abstractmethod
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .attributes import LangGraphSpanAttributes
from codon_sdk.instrumentation.schemas.nodespec import NodeSpec, NodeSpecSpanAttributes
from codon_sdk.agents import Workload
from codon_sdk.instrumentation.schemas.telemetry.spans import CodonBaseSpanAttributes
from codon_sdk.instrumentation.telemetry import NodeTelemetryPayload
from codon_sdk.instrumentation import initialize_telemetry

__all__ = [
    "LangGraphWorkloadMixin",
    "initialize_telemetry",
    "track_node",
    "LangGraphWorkloadAdapter",
    "LangGraphAdapterResult",
    "NodeOverride",
    "current_invocation",
    "LangGraphTelemetryCallback",
]

ORG_NAMESPACE: str = os.getenv("ORG_NAMESPACE")
__framework__ = "langgraph"

_instrumented_nodes: List[NodeSpec] = []


_ACTIVE_INVOCATION: ContextVar[Optional[NodeTelemetryPayload]] = ContextVar(
    "codon_langgraph_active_invocation", default=None
)


class LangGraphWorkloadMixin(ABC):
    """Mixin contract for workloads built from LangGraph graphs.

    Concrete implementations should inherit from this mixin *and* a concrete
    ``Workload`` subclass to reuse instrumentation helpers exposed here.
    """

    @classmethod
    @abstractmethod
    def from_langgraph(
        cls,
        graph: Any,
        *,
        name: str,
        version: str,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> Workload:
        """Translate a LangGraph graph into a concrete Codon workload."""


def current_invocation() -> Optional[NodeTelemetryPayload]:
    """Return the currently active node invocation telemetry (if any)."""

    return _ACTIVE_INVOCATION.get()


def _safe_repr(value: Any, *, max_length: int = 2048) -> str:
    try:
        rendered = repr(value)
    except Exception as exc:  # pragma: no cover - defensive path
        rendered = f"<unrepresentable {type(value).__name__}: {exc}>"
    if len(rendered) > max_length:
        return rendered[: max_length - 3] + "..."
    return rendered


def _initial_input_payload(
    args: Sequence[Any], kwargs: Mapping[str, Any]
) -> Optional[str]:
    if args:
        return _safe_repr(args[0])
    if "message" in kwargs:
        return _safe_repr(kwargs["message"])
    if kwargs:
        return _safe_repr(dict(kwargs))
    return None


def _coerce_context(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


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
    span,
    *,
    telemetry: NodeTelemetryPayload,
    runtime: Any,
    nodespec: NodeSpec,
    context: Mapping[str, Any],
) -> None:
    workload = getattr(runtime, "_workload", None)

    organization = (
        telemetry.organization_id
        or telemetry.org_namespace
        or context.get("organization_id")
        or context.get("org_namespace")
        or (workload.organization_id if workload else None)
        or nodespec.org_namespace
        or ORG_NAMESPACE
    )

    span.set_attribute(
        CodonBaseSpanAttributes.AgentFramework.value,
        __framework__,
    )
    if organization:
        span.set_attribute(CodonBaseSpanAttributes.OrganizationId.value, organization)
        span.set_attribute(CodonBaseSpanAttributes.OrgNamespace.value, organization)
        telemetry.organization_id = telemetry.organization_id or organization
        telemetry.org_namespace = telemetry.org_namespace or organization

    workload_id = telemetry.workload_id or context.get("workload_id") or (
        workload.agent_class_id if workload else None
    )
    logic_id = (
        telemetry.workload_logic_id
        or context.get("logic_id")
        or context.get("workload_logic_id")
        or (workload.logic_id if workload else None)
    )
    run_id = (
        telemetry.workload_run_id
        or context.get("workload_run_id")
        or context.get("run_id")
    )
    deployment_id = telemetry.deployment_id or context.get("deployment_id")

    if workload_id:
        span.set_attribute(CodonBaseSpanAttributes.WorkloadId.value, workload_id)
        telemetry.workload_id = workload_id
    if logic_id:
        span.set_attribute(CodonBaseSpanAttributes.WorkloadLogicId.value, logic_id)
        telemetry.workload_logic_id = logic_id
    if run_id:
        span.set_attribute(CodonBaseSpanAttributes.WorkloadRunId.value, run_id)
        telemetry.workload_run_id = run_id
    if deployment_id:
        span.set_attribute(CodonBaseSpanAttributes.DeploymentId.value, deployment_id)
        telemetry.deployment_id = deployment_id

    workload_name = (
        telemetry.workload_name
        or context.get("workload_name")
        or (workload.metadata.name if workload else None)
    )
    workload_version = (
        telemetry.workload_version
        or context.get("workload_version")
        or (workload.metadata.version if workload else None)
    )

    if workload_name:
        span.set_attribute(
            CodonBaseSpanAttributes.WorkloadName.value,
            workload_name,
        )
        telemetry.workload_name = workload_name
    if workload_version:
        span.set_attribute(
            CodonBaseSpanAttributes.WorkloadVersion.value,
            workload_version,
        )
        telemetry.workload_version = workload_version


def _finalise_span(span, telemetry: NodeTelemetryPayload) -> None:
    if telemetry.node_input is not None:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeInput.value,
            telemetry.node_input,
        )
        span.set_attribute(
            LangGraphSpanAttributes.Inputs.value,
            telemetry.node_input,
        )

    if telemetry.duration_ms is not None:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeLatencyMs.value,
            telemetry.duration_ms,
        )
        span.set_attribute(
            LangGraphSpanAttributes.NodeLatency.value,
            f"{telemetry.duration_ms / 1000:.3f}",
        )

    if telemetry.node_output is not None:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeOutput.value,
            telemetry.node_output,
        )
        span.set_attribute(
            LangGraphSpanAttributes.Outputs.value,
            telemetry.node_output,
        )

    span.set_attribute(
        CodonBaseSpanAttributes.NodeStatusCode.value,
        telemetry.status_code,
    )

    if telemetry.error_message:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeErrorMessage.value,
            telemetry.error_message,
        )

    if telemetry.model_vendor:
        span.set_attribute(
            CodonBaseSpanAttributes.ModelVendor.value,
            telemetry.model_vendor,
        )

    if telemetry.model_identifier:
        span.set_attribute(
            CodonBaseSpanAttributes.ModelIdentifier.value,
            telemetry.model_identifier,
        )

    if telemetry.input_tokens is not None:
        span.set_attribute(
            CodonBaseSpanAttributes.TokenInput.value,
            telemetry.input_tokens,
        )

    if telemetry.output_tokens is not None:
        span.set_attribute(
            CodonBaseSpanAttributes.TokenOutput.value,
            telemetry.output_tokens,
        )

    if telemetry.total_tokens is not None:
        span.set_attribute(
            CodonBaseSpanAttributes.TokenTotal.value,
            telemetry.total_tokens,
        )

    if telemetry.token_usage:
        span.set_attribute(
            CodonBaseSpanAttributes.TokenUsageJson.value,
            json.dumps(telemetry.token_usage, default=str),
        )

    if telemetry.network_calls:
        span.set_attribute(
            CodonBaseSpanAttributes.NetworkCallsJson.value,
            json.dumps(telemetry.network_calls, default=str),
        )

    raw_json = telemetry.to_raw_attributes_json()
    if raw_json:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeRawAttributes.value,
            raw_json,
        )


def track_node(
    node_name: str,
    role: str,
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
    introspection_target: Optional[Callable[..., Any]] = None,
    nodespec_kwargs: Optional[Mapping[str, Any]] = None,
):
    """Decorator to add telemetry instrumentation to a function.

    When the decorated function executes, this decorator:
    - Materializes a NodeSpec and captures its ID, signature, and schemas
    - Wraps execution in an OpenTelemetry span (async and sync supported)
    - Records inputs, outputs, and wall-clock latency via standardized span attributes

    Args:
        node_name: Unique identifier for this node.
        role: The node's role in the workflow.
        model_name: Optional model identifier if this node uses an AI model.
        model_version: Optional model version if this node uses an AI model.
        introspection_target: Optional callable to introspect instead of decorated function.
        nodespec_kwargs: Optional additional kwargs passed to NodeSpec constructor.

    Returns:
        The decorated function with telemetry instrumentation added.

    Example:
        >>> @track_node("retrieve_docs", role="retriever")
        ... def retrieve_docs(query: str) -> List[str]:
        ...     return ["doc1", "doc2"]

    TODO: Document what 'role' parameter specifically represents
    TODO: Clarify introspection_target use case and when to use it
    """
    def decorator(func):
        spec_callable = introspection_target or func
        spec_kwargs = dict(nodespec_kwargs or {})
        nodespec = NodeSpec(
            org_namespace=ORG_NAMESPACE,
            name=node_name,
            role=role,
            callable=spec_callable,
            model_name=model_name,
            model_version=model_version,
            **spec_kwargs,
        )
        _instrumented_nodes.append(nodespec)

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def awrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)
                invocation_context = _coerce_context(kwargs.get("context"))
                runtime = kwargs.get("runtime")
                telemetry = getattr(runtime, "telemetry", None)
                if telemetry is None:
                    telemetry = NodeTelemetryPayload()
                if telemetry.node_input is None:
                    telemetry.node_input = _initial_input_payload(args, kwargs)
                telemetry.node_name = telemetry.node_name or nodespec.name
                telemetry.node_role = telemetry.node_role or nodespec.role
                telemetry.nodespec_id = telemetry.nodespec_id or nodespec.id
                token = _ACTIVE_INVOCATION.set(telemetry)

                try:
                    with tracer.start_as_current_span(nodespec.name) as span:
                        _apply_nodespec_attributes(span, nodespec)
                        _apply_workload_attributes(
                            span,
                            telemetry=telemetry,
                            runtime=runtime,
                            nodespec=nodespec,
                            context=invocation_context,
                        )

                        start = time.perf_counter()
                        try:
                            result = await func(*args, **kwargs)
                        except Exception as exc:  # pragma: no cover - surfacing telemetry
                            telemetry.status_code = "ERROR"
                            telemetry.error_message = repr(exc)
                            span.record_exception(exc)
                            span.set_status(Status(StatusCode.ERROR, str(exc)))
                            raise
                        else:
                            telemetry.node_output = _safe_repr(result)
                            return result
                        finally:
                            telemetry.duration_ms = int(
                                (time.perf_counter() - start) * 1000
                            )
                            _finalise_span(span, telemetry)
                finally:
                    _ACTIVE_INVOCATION.reset(token)

            return awrapper

        else:

            @wraps(func)
            def wrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)
                invocation_context = _coerce_context(kwargs.get("context"))
                runtime = kwargs.get("runtime")
                telemetry = getattr(runtime, "telemetry", None)
                if telemetry is None:
                    telemetry = NodeTelemetryPayload()
                if telemetry.node_input is None:
                    telemetry.node_input = _initial_input_payload(args, kwargs)
                telemetry.node_name = telemetry.node_name or nodespec.name
                telemetry.node_role = telemetry.node_role or nodespec.role
                telemetry.nodespec_id = telemetry.nodespec_id or nodespec.id
                token = _ACTIVE_INVOCATION.set(telemetry)

                try:
                    with tracer.start_as_current_span(nodespec.name) as span:
                        _apply_nodespec_attributes(span, nodespec)
                        _apply_workload_attributes(
                            span,
                            telemetry=telemetry,
                            runtime=runtime,
                            nodespec=nodespec,
                            context=invocation_context,
                        )

                        start = time.perf_counter()
                        try:
                            result = func(*args, **kwargs)
                        except Exception as exc:  # pragma: no cover - surfacing telemetry
                            telemetry.status_code = "ERROR"
                            telemetry.error_message = repr(exc)
                            span.record_exception(exc)
                            span.set_status(Status(StatusCode.ERROR, str(exc)))
                            raise
                        else:
                            telemetry.node_output = _safe_repr(result)
                            return result
                        finally:
                            telemetry.duration_ms = int(
                                (time.perf_counter() - start) * 1000
                            )
                            _finalise_span(span, telemetry)
                finally:
                    _ACTIVE_INVOCATION.reset(token)

            return wrapper

    return decorator


from .adapter import (  # noqa: E402  # isort: skip
    LangGraphAdapterResult,
    LangGraphWorkloadAdapter,
    NodeOverride,
)
from .callbacks import LangGraphTelemetryCallback  # noqa: E402  # isort: skip
