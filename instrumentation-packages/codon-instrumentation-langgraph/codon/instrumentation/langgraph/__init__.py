import os
import inspect
from functools import wraps
from typing import Optional, Dict, Any, get_type_hints

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

from codon_sdk.schemas.nodespec import generate_nodespec

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME")
ORG_NAMESPACE = os.getenv("ORG_NAMESPACE")

def initialize_telemetry(service_name: str = SERVICE_NAME or "") -> None:
    # Set up service name
    resource = Resource(attributes = {
        "service.name": service_name
    })
    # Set up TracerProvider & Exporter
    provider = TracerProvider(resource=resource)
    otlp_exporter = OTLPSpanExporter()

    processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

def track_agent(
        node_name: str,
        role: str,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None
):

    def decorator(func):
        nodespec = generate_nodespec(
            name=node_name, 
            role=role,
            callable=func,
            model_name=model_name, 
            model_version=model_version
        )
        nodespec_id = nodespec.generate_nodespec_id(namespace=ORG_NAMESPACE)

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def awrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)

                with tracer.start_as_current_span(nodespec.name) as span:
                    span.set_attribute("codon.nodespec.id", nodespec_id)
                    span.set_attribute("codon.nodespec.version", nodespec.spec_version)
                    span.set_attribute("langgraph.node.name", nodespec.name)
                    span.set_attribute("langgraph.node.callable_signature", nodespec.callable_signature)
                    span.set_attribute("langgraph.node.input_schema", nodespec.input_schema)
                    span.set_attribute("langgraph.node.output_schema", nodespec.output_schema)
                    span.set_attribute("langgraph.node.inputs", str(args))
                    if nodespec.model_name:
                        span.set_attribute("langgraph.node.model_name", nodespec.model_name)
                    if nodespec.model_version:
                        span.set_attribute("langgraph.node.model_version", nodespec.model_version)

                    result = await func(*args, **kwargs)

                    span.set_attribute("langgraph.node.outputs", str(result))

                return result
        

            return awrapper

        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)

                with tracer.start_as_current_span(nodespec.name) as span:
                    span.set_attribute("codon.nodespec.id", nodespec_id)
                    span.set_attribute("codon.nodespec.version", nodespec.spec_version)
                    span.set_attribute("langgraph.node.name", nodespec.name)
                    span.set_attribute("langgraph.node.callable_signature", nodespec.callable_signature)
                    span.set_attribute("langgraph.node.input_schema", nodespec.input_schema)
                    span.set_attribute("langgraph.node.output_schema", nodespec.output_schema)
                    span.set_attribute("langgraph.node.inputs", str(args))
                    if nodespec.model_name:
                        span.set_attribute("langgraph.node.model_name", nodespec.model_name)
                    if nodespec.model_version:
                        span.set_attribute("langgraph.node.model_version", nodespec.model_version)

                    result = func(*args, **kwargs)

                    span.set_attribute("langgraph.node.outputs", str(result))

                    return result
        
            return wrapper
    
    return decorator    