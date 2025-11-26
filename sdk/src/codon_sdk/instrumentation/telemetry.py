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

"""Framework-agnostic telemetry payload helpers for node executions."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional


@dataclass
class NodeTelemetryPayload:
    """Normalized telemetry for a single node invocation.

    Mirrors the MVP analytics schema so instrumentation packages can export
    spans, logs, or metrics without redefining attribute names.
    """

    # Workload/organization context
    workload_id: Optional[str] = None
    workload_name: Optional[str] = None
    workload_version: Optional[str] = None
    workload_logic_id: Optional[str] = None
    workload_run_id: Optional[str] = None
    deployment_id: Optional[str] = None
    organization_id: Optional[str] = None
    org_namespace: Optional[str] = None

    # Node identification
    nodespec_id: Optional[str] = None
    node_name: Optional[str] = None
    node_role: Optional[str] = None

    # Model metadata
    model_name: Optional[str] = None
    model_vendor: Optional[str] = None
    model_identifier: Optional[str] = None

    # Token usage
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    token_usage: Dict[str, Any] = field(default_factory=dict)

    # Payloads and results
    node_input: Optional[str] = None
    node_output: Optional[str] = None
    duration_ms: Optional[int] = None
    status_code: str = "OK"
    error_message: Optional[str] = None

    # Miscellaneous metadata
    network_calls: list[dict[str, Any]] = field(default_factory=list)
    extra_attributes: Dict[str, Any] = field(default_factory=dict)

    def record_tokens(
        self,
        *,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        token_usage: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if input_tokens is not None:
            self.input_tokens = input_tokens
        if output_tokens is not None:
            self.output_tokens = output_tokens
        if total_tokens is not None:
            self.total_tokens = total_tokens
        if token_usage:
            self.token_usage.update(dict(token_usage))

    def set_model_info(
        self,
        *,
        model_name: Optional[str] = None,
        vendor: Optional[str] = None,
        identifier: Optional[str] = None,
    ) -> None:
        if model_name is not None:
            self.model_name = model_name
        if vendor is not None:
            self.model_vendor = vendor
        if identifier is not None:
            self.model_identifier = identifier

    def add_network_call(self, details: Mapping[str, Any]) -> None:
        self.network_calls.append(dict(details))

    def to_raw_attributes_json(self) -> Optional[str]:
        """Serialize supplementary telemetry for the analytics raw column."""

        payload: Dict[str, Any] = {}
        if self.token_usage:
            payload["token_usage"] = self.token_usage
        if self.network_calls:
            payload["network_calls"] = self.network_calls
        if self.extra_attributes:
            payload["extra"] = self.extra_attributes
        if not payload:
            return None
        return json.dumps(payload, default=str)

    def as_span_attributes(self) -> Dict[str, Any]:
        """Flatten relevant fields into span attributes."""

        data = asdict(self)
        data.pop("network_calls", None)
        data.pop("extra_attributes", None)
        data.pop("token_usage", None)
        return {k: v for k, v in data.items() if v is not None}


__all__ = ["NodeTelemetryPayload"]
