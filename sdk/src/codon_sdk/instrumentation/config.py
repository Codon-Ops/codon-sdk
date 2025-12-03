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

import os
from typing import Dict, Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

import logging

# Avoid configuring root logger; module-level logger only.
logger = logging.getLogger(__name__)

# Hardcoded production ingest endpoint; can be overridden via argument or env.
DEFAULT_INGEST_ENDPOINT = "https://ingest.codonops.ai:4317"


_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}


def _coerce_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in _TRUE_VALUES


def initialize_telemetry(
    api_key: Optional[str] = None,
    service_name: Optional[str] = None,
    endpoint: Optional[str] = None,
    attach_to_existing: Optional[bool] = None,
) -> None:
    """Initialize OpenTelemetry tracing for Codon.

    Endpoint precedence: explicit argument, ``OTEL_EXPORTER_OTLP_ENDPOINT``, then
    production default. API key precedence: explicit argument, then
    ``CODON_API_KEY`` environment variable. When provided, the API key is sent
    as ``x-codon-api-key`` on OTLP requests.
    """

    attach = (
        attach_to_existing
        if attach_to_existing is not None
        else _coerce_bool(os.getenv("CODON_ATTACH_TO_EXISTING_OTEL_PROVIDER"))
    ) or False

    existing_provider = trace.get_tracer_provider()

    final_api_key = api_key or os.getenv("CODON_API_KEY")
    final_service_name = (
        service_name
        or os.getenv("OTEL_SERVICE_NAME")
        or "unknown_codon_service"
    )
    final_endpoint = (
        endpoint
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or DEFAULT_INGEST_ENDPOINT
    )

    headers: Dict[str, str] = {}
    if final_api_key:
        headers["x-codon-api-key"] = final_api_key
    else:
        logger.warning(
            "CODON telemetry initialized without an API key; spans may be rejected by the gateway"
        )

    resource = Resource(attributes={"service.name": final_service_name})
    exporter = OTLPSpanExporter(endpoint=final_endpoint, headers=headers)

    if attach and isinstance(existing_provider, TracerProvider):
        processor = BatchSpanProcessor(exporter)
        # Avoid double-adding an equivalent processor if initialise is called repeatedly.
        if not _has_equivalent_processor(existing_provider, exporter):
            existing_provider.add_span_processor(processor)
        return

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)


def _has_equivalent_processor(provider: TracerProvider, exporter: OTLPSpanExporter) -> bool:
    """Return True if provider already has a processor targeting the same exporter endpoint/headers."""
    processors = getattr(getattr(provider, "_active_span_processor", None), "processors", None)
    if not processors:
        return False
    for processor in processors:
        existing_exporter = getattr(processor, "span_exporter", None)
        if existing_exporter is exporter:
            return True
        same_endpoint = getattr(existing_exporter, "endpoint", None) == getattr(exporter, "endpoint", None)
        same_headers = getattr(existing_exporter, "headers", None) == getattr(exporter, "headers", None)
        if same_endpoint and same_headers:
            return True
    return False
