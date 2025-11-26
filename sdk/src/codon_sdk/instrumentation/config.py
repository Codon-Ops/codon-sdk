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

# Hardcoded production ingest endpoint; can be overridden via argument or env.
DEFAULT_INGEST_ENDPOINT = "https://ingest.codonops.ai:4317"


def initialize_telemetry(
    api_key: Optional[str] = None,
    service_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> None:
    """Initialize OpenTelemetry tracing for Codon.

    Endpoint precedence: explicit argument, ``OTEL_EXPORTER_OTLP_ENDPOINT``, then
    production default. API key precedence: explicit argument, then
    ``CODON_API_KEY`` environment variable. When provided, the API key is sent
    as ``x-codon-api-key`` on OTLP requests.
    """

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

    resource = Resource(attributes={"service.name": final_service_name})
    exporter = OTLPSpanExporter(endpoint=final_endpoint, headers=headers)

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
