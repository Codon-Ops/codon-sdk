import os
import time
import inspect
from abc import ABC, abstractmethod
from functools import wraps
from typing import Optional, List, Any, Sequence

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

from .attributes import LangGraphSpanAttributes
from codon_sdk.instrumentation.schemas.nodespec import NodeSpec, NodeSpecSpanAttributes
from codon_sdk.agents import Workload
from codon_sdk.instrumentation.schemas.telemetry.spans import CodonBaseSpanAttributes

__all__ = [
    "LangGraphWorkloadMixin",
    "initialize_telemetry",
    "track_node",
]

SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME")
ORG_NAMESPACE: str = os.getenv("ORG_NAMESPACE")
__framework__ = "langgraph"

_instrumented_nodes: List[NodeSpec] = []


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


def initialize_telemetry(service_name: str = SERVICE_NAME or "") -> None:
    # Set up service name
    resource = Resource(attributes={"service.name": service_name})
    # Set up TracerProvider & Exporter
    provider = TracerProvider(resource=resource)
    otlp_exporter = OTLPSpanExporter()

    processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)


def track_node(
    node_name: str,
    role: str,
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
):
    def decorator(func):
        nodespec = NodeSpec(
            org_namespace=ORG_NAMESPACE,
            name=node_name,
            role=role,
            callable=func,
            model_name=model_name,
            model_version=model_version,
        )
        _instrumented_nodes.append(nodespec)

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def awrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)

                with tracer.start_as_current_span(nodespec.name) as span:
                    span.set_attribute(
                        CodonBaseSpanAttributes.OrgNamespace.value, ORG_NAMESPACE
                    )
                    span.set_attribute(
                        CodonBaseSpanAttributes.AgentFramework.value, __framework__
                    )
                    span.set_attribute(NodeSpecSpanAttributes.ID.value, nodespec.id)
                    span.set_attribute(
                        NodeSpecSpanAttributes.Version.value, nodespec.spec_version
                    )
                    span.set_attribute(NodeSpecSpanAttributes.Name.value, nodespec.name)
                    span.set_attribute(NodeSpecSpanAttributes.Role.value, nodespec.role)
                    span.set_attribute(
                        NodeSpecSpanAttributes.CallableSignature.value,
                        nodespec.callable_signature,
                    )
                    span.set_attribute(
                        NodeSpecSpanAttributes.InputSchema.value, nodespec.input_schema
                    )
                    span.set_attribute(
                        NodeSpecSpanAttributes.OutputSchema.value,
                        nodespec.output_schema,
                    )
                    if nodespec.model_name:
                        span.set_attribute(
                            NodeSpecSpanAttributes.ModelName.value, nodespec.model_name
                        )
                    if nodespec.model_version:
                        span.set_attribute(
                            NodeSpecSpanAttributes.ModelVersion.value,
                            nodespec.model_version,
                        )

                    span.set_attribute(LangGraphSpanAttributes.Inputs.value, str(args))

                    start = time.perf_counter()
                    result = await func(*args, **kwargs)
                    end = time.perf_counter()
                    elapsed = round(end - start, 3)
                    span.set_attribute(
                        LangGraphSpanAttributes.NodeLatency.value, str(elapsed)
                    )
                    span.set_attribute(
                        LangGraphSpanAttributes.Outputs.value, str(result)
                    )

                return result

            return awrapper

        else:

            @wraps(func)
            def wrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)

                with tracer.start_as_current_span(nodespec.name) as span:
                    span.set_attribute(
                        CodonBaseSpanAttributes.OrgNamespace.value, ORG_NAMESPACE
                    )
                    span.set_attribute(
                        CodonBaseSpanAttributes.AgentFramework.value, "langgraph"
                    )
                    span.set_attribute(NodeSpecSpanAttributes.ID.value, nodespec.id)
                    span.set_attribute(
                        NodeSpecSpanAttributes.Version.value, nodespec.spec_version
                    )
                    span.set_attribute(NodeSpecSpanAttributes.Name.value, nodespec.name)
                    span.set_attribute(NodeSpecSpanAttributes.Role.value, nodespec.role)
                    span.set_attribute(
                        NodeSpecSpanAttributes.CallableSignature.value,
                        nodespec.callable_signature,
                    )
                    span.set_attribute(
                        NodeSpecSpanAttributes.InputSchema.value, nodespec.input_schema
                    )
                    span.set_attribute(
                        NodeSpecSpanAttributes.OutputSchema.value,
                        nodespec.output_schema,
                    )
                    if nodespec.model_name:
                        span.set_attribute(
                            NodeSpecSpanAttributes.ModelName.value, nodespec.model_name
                        )
                    if nodespec.model_version:
                        span.set_attribute(
                            NodeSpecSpanAttributes.ModelVersion.value,
                            nodespec.model_version,
                        )

                    span.set_attribute(LangGraphSpanAttributes.Inputs.value, str(args))

                    start = time.perf_counter()
                    result = func(*args, **kwargs)
                    end = time.perf_counter()
                    elapsed = round(end - start, 3)
                    span.set_attribute(
                        LangGraphSpanAttributes.NodeLatency.value, str(elapsed)
                    )
                    span.set_attribute(
                        LangGraphSpanAttributes.Outputs.value, str(result)
                    )

                    return result

            return wrapper

    return decorator
