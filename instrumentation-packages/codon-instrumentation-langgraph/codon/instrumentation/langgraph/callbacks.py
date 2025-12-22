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

"""LangChain callback handlers that enrich Codon telemetry."""
from __future__ import annotations

import dataclasses
import json
import time
from typing import Any, Mapping, Optional

import logging
import os
import threading
from dataclasses import dataclass

try:  # pragma: no cover - optional dependency
    from langchain_core.callbacks.base import BaseCallbackHandler
except Exception:  # pragma: no cover - fallback when LangChain is absent

    class BaseCallbackHandler:  # type: ignore
        """Minimal stand-in to keep instrumentation optional."""

        pass

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from codon_sdk.instrumentation.schemas.nodespec import NodeSpecSpanAttributes
from codon_sdk.instrumentation.schemas.telemetry.spans import CodonBaseSpanAttributes
from codon_sdk.instrumentation.telemetry import NodeTelemetryPayload

from .context import current_graph_context, current_langgraph_config
from . import current_invocation, _ACTIVE_INVOCATION


def _coerce_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if dataclasses.is_dataclass(value):  # pragma: no cover - defensive fallbacks
        return dataclasses.asdict(value)
    for attr in ("to_dict", "dict", "model_dump"):
        method = getattr(value, attr, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return result
    if hasattr(value, "__dict__"):
        data = {
            key: getattr(value, key)
            for key in vars(value)
            if not key.startswith("_")
        }
        return data
    return None


def _first(*values: Any) -> Optional[Any]:
    for value in values:
        if value:
            return value
    return None


def _normalise_usage(payload: Mapping[str, Any]) -> tuple[dict[str, Any], Optional[int], Optional[int], Optional[int]]:
    usage = {}
    for key in ("token_usage", "usage", "token_counts"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            usage = dict(candidate)
            break

    # Some providers nest counts under token_count
    token_count = payload.get("token_count")
    if isinstance(token_count, Mapping):
        usage = usage or dict(token_count)

    # Provider-specific fallbacks
    for k in (
        "prompt_tokens",
        "input_tokens",
        "prompt_token_count",
        "input_token_count",
        "promptTokenCount",
        "inputTokenCount",
    ):
        if k in payload and k not in usage:
            usage[k] = payload[k]
    for k in (
        "completion_tokens",
        "output_tokens",
        "completion_token_count",
        "output_token_count",
        "completionTokenCount",
        "outputTokenCount",
    ):
        if k in payload and k not in usage:
            usage[k] = payload[k]
    if "total_tokens" not in usage and "totalTokenCount" in payload:
        usage["total_tokens"] = payload["totalTokenCount"]

    prompt_tokens = _first(usage.get("prompt_tokens"), usage.get("input_tokens"))
    completion_tokens = _first(
        usage.get("completion_tokens"), usage.get("output_tokens")
    )
    total_tokens = usage.get("total_tokens")
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    return usage, prompt_tokens, completion_tokens, total_tokens


def _safe_repr(value: Any, *, max_length: int = 2048) -> str:
    try:
        rendered = repr(value)
    except Exception as exc:  # pragma: no cover - defensive path
        rendered = f"<unrepresentable {type(value).__name__}: {exc}>"
    if len(rendered) > max_length:
        return rendered[: max_length - 3] + "..."
    return rendered


def _ensure_callback_list(callbacks: Any) -> list[Any]:
    if callbacks is None:
        return []
    handlers = getattr(callbacks, "handlers", None)
    if handlers is not None:
        return list(handlers)
    if isinstance(callbacks, (list, tuple)):
        return list(callbacks)
    return [callbacks]


def _attach_bound_callback(config: Mapping[str, Any], invocation: "NodeTelemetryPayload") -> None:
    if not isinstance(config, dict):
        return
    callbacks = _ensure_callback_list(config.get("callbacks"))
    callbacks = [
        cb for cb in callbacks if not isinstance(cb, BoundInvocationTelemetryCallback)
    ]
    invocation.extra_attributes.setdefault("codon_span_defer", True)
    callbacks.append(BoundInvocationTelemetryCallback(invocation))
    config["callbacks"] = callbacks


def _extract_node_name(serialized: Mapping[str, Any], kwargs: Mapping[str, Any]) -> Optional[str]:
    for key in ("name", "run_name"):
        value = kwargs.get(key)
        if isinstance(value, str):
            return value
    name = serialized.get("name")
    if isinstance(name, str):
        return name
    identifier = serialized.get("id")
    if isinstance(identifier, (list, tuple)) and identifier:
        candidate = identifier[-1]
        if isinstance(candidate, str):
            return candidate
    return None


class _ActiveSpan:
    def __init__(
        self,
        span,
        telemetry,
        started_at,
        run_id: str,
    ):
        self.span = span
        self.telemetry = telemetry
        self.started_at = started_at
        self.run_id = run_id


_ACTIVE_BY_TELEMETRY: dict[int, _ActiveSpan] = {}


def _resource_org_id() -> Optional[str]:
    provider = trace.get_tracer_provider()
    resource = getattr(provider, "resource", None)
    if not resource:
        return None
    attributes = getattr(resource, "attributes", None)
    if not isinstance(attributes, Mapping):
        return None
    candidate = attributes.get(CodonBaseSpanAttributes.OrganizationId.value) or attributes.get(
        "codon.organization.id"
    )
    if isinstance(candidate, str) and candidate.startswith("ORG_"):
        return candidate
    return None


def _ensure_org_id(telemetry: NodeTelemetryPayload) -> Optional[str]:
    candidate = telemetry.organization_id
    if isinstance(candidate, str) and candidate.startswith("ORG_"):
        return candidate
    fallback = _resource_org_id()
    if fallback:
        telemetry.organization_id = fallback
        return fallback
    return None


def _infer_tokens_from_usage(usage: Mapping[str, Any]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    prompt = usage.get("prompt_tokens")
    if prompt is None:
        prompt = usage.get("input_tokens")
    completion = usage.get("completion_tokens")
    if completion is None:
        completion = usage.get("output_tokens")
    total = usage.get("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return prompt, completion, total


def _finalize_node_span(active: _ActiveSpan) -> None:
    telemetry = active.telemetry
    span = active.span
    telemetry.extra_attributes["codon_span_finalized"] = True

    _ensure_org_id(telemetry)

    if telemetry.node_output:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeOutput.value,
            telemetry.node_output,
        )
    if telemetry.duration_ms is not None:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeLatencyMs.value,
            telemetry.duration_ms,
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
    if telemetry.token_usage and (
        telemetry.input_tokens is None
        or telemetry.output_tokens is None
        or telemetry.total_tokens is None
    ):
        prompt, completion, total = _infer_tokens_from_usage(telemetry.token_usage)
        if telemetry.input_tokens is None:
            telemetry.input_tokens = prompt
        if telemetry.output_tokens is None:
            telemetry.output_tokens = completion
        if telemetry.total_tokens is None:
            telemetry.total_tokens = total
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
    if telemetry.organization_id:
        span.set_attribute(
            CodonBaseSpanAttributes.OrganizationId.value,
            telemetry.organization_id,
        )
    raw_json = telemetry.to_raw_attributes_json()
    if raw_json:
        span.set_attribute(
            CodonBaseSpanAttributes.NodeRawAttributes.value,
            raw_json,
        )

    if telemetry.status_code != "OK":
        span.set_status(Status(StatusCode.ERROR, telemetry.error_message or "error"))

    span.end()
    _ACTIVE_INVOCATION.set(None)


def _resolve_config(kwargs: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    config = kwargs.get("config")
    if isinstance(config, Mapping):
        return config
    config = current_langgraph_config()
    if isinstance(config, Mapping):
        return config
    return None


def _resolve_metadata(kwargs: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    metadata = kwargs.get("metadata")
    if isinstance(metadata, Mapping):
        return metadata
    return None


def _resolve_invocation(kwargs: Mapping[str, Any]) -> Optional["NodeTelemetryPayload"]:
    invocation = current_invocation()
    if invocation is not None:
        return invocation
    config = _resolve_config(kwargs)
    if not isinstance(config, Mapping):
        return None
    metadata = config.get("metadata")
    if isinstance(metadata, Mapping):
        candidate = metadata.get("codon_invocation")
        if isinstance(candidate, NodeTelemetryPayload):
            return candidate
    return _lookup_invocation_metadata(config)


def _attach_invocation_to_config(config: Mapping[str, Any], invocation: NodeTelemetryPayload) -> bool:
    if not isinstance(config, dict):
        return False
    metadata = config.get("metadata")
    if not isinstance(metadata, dict):
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        config["metadata"] = metadata
    metadata["codon_invocation"] = invocation
    return True


class LangGraphNodeSpanCallback(BaseCallbackHandler):
    """Emit node spans from LangChain callback events."""

    run_inline = False

    def __init__(self) -> None:
        self._active: dict[str, _ActiveSpan] = {}
        self._logger = logging.getLogger(__name__)
        self._debug_usage_enabled = os.getenv("CODON_LANGGRAPH_DEBUG_USAGE") == "1"

    def on_chain_start(self, serialized: Mapping[str, Any], inputs: Mapping[str, Any], **kwargs: Any) -> None:
        graph_context = current_graph_context()
        if not graph_context:
            return
        node_name = _extract_node_name(serialized, kwargs)
        if not node_name:
            return
        nodespec = graph_context.node_specs.get(node_name)
        if nodespec is None:
            return

        run_id = kwargs.get("run_id")
        if run_id is None:
            run_id = f"node-{id(nodespec)}-{time.time_ns()}"
        run_id = str(run_id)

        telemetry = current_invocation() or NodeTelemetryPayload()
        telemetry.node_name = telemetry.node_name or nodespec.name
        telemetry.node_role = telemetry.node_role or nodespec.role
        telemetry.nodespec_id = telemetry.nodespec_id or nodespec.id
        telemetry.node_input = telemetry.node_input or _safe_repr(inputs)

        telemetry.workload_id = telemetry.workload_id or graph_context.workload.agent_class_id
        telemetry.workload_logic_id = telemetry.workload_logic_id or graph_context.workload.logic_id
        telemetry.workload_run_id = telemetry.workload_run_id or graph_context.run_id
        telemetry.workload_name = telemetry.workload_name or graph_context.workload.metadata.name
        telemetry.workload_version = (
            telemetry.workload_version or graph_context.workload.metadata.version
        )
        telemetry.deployment_id = telemetry.deployment_id or graph_context.deployment_id
        if graph_context.organization_id and graph_context.organization_id.startswith("ORG_"):
            if not isinstance(telemetry.organization_id, str) or not telemetry.organization_id.startswith("ORG_"):
                telemetry.organization_id = graph_context.organization_id
        if not telemetry.organization_id or not telemetry.organization_id.startswith("ORG_"):
            _ensure_org_id(telemetry)
        telemetry.org_namespace = telemetry.org_namespace or graph_context.org_namespace

        tracer = trace.get_tracer(__name__)
        span = tracer.start_span(nodespec.name)
        _ACTIVE_INVOCATION.set(telemetry)
        config = _resolve_config(kwargs)
        if isinstance(config, dict):
            metadata = config.get("metadata")
            if not isinstance(metadata, dict):
                metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
                config["metadata"] = metadata
            metadata.setdefault("codon_run_id", graph_context.run_id)
        registry_config = config
        kwargs_metadata = _resolve_metadata(kwargs)
        if (
            (registry_config is None or not isinstance(registry_config.get("metadata"), Mapping))
            and kwargs_metadata is not None
        ):
            registry_config = {"metadata": dict(kwargs_metadata)}
            if self._debug_usage_enabled:
                self._logger.info(
                    "codon.langgraph usage debug: using kwargs metadata for registry keys=%s",
                    sorted(kwargs_metadata.keys()),
                )
        if config is not None:
            attached = _attach_invocation_to_config(config, telemetry)
            _attach_bound_callback(config, telemetry)
            registered = _register_invocation_metadata(registry_config or config, nodespec.name, telemetry)
            if self._debug_usage_enabled:
                self._logger.info(
                    "codon.langgraph usage debug: attached codon_invocation=%s registered=%s",
                    attached,
                    registered,
                )
        elif self._debug_usage_enabled:
            self._logger.info(
                "codon.langgraph usage debug: missing config for codon_invocation",
            )

        span.set_attribute(NodeSpecSpanAttributes.ID.value, nodespec.id)
        span.set_attribute(NodeSpecSpanAttributes.Version.value, nodespec.spec_version)
        span.set_attribute(NodeSpecSpanAttributes.Name.value, nodespec.name)
        span.set_attribute(NodeSpecSpanAttributes.Role.value, nodespec.role)
        span.set_attribute(
            NodeSpecSpanAttributes.CallableSignature.value,
            nodespec.callable_signature,
        )
        span.set_attribute(NodeSpecSpanAttributes.InputSchema.value, nodespec.input_schema)
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

        span.set_attribute(CodonBaseSpanAttributes.AgentFramework.value, "langgraph")
        if telemetry.organization_id:
            span.set_attribute(
                CodonBaseSpanAttributes.OrganizationId.value,
                telemetry.organization_id,
            )
        if telemetry.org_namespace:
            span.set_attribute(
                CodonBaseSpanAttributes.OrgNamespace.value,
                telemetry.org_namespace,
            )
        span.set_attribute(CodonBaseSpanAttributes.WorkloadId.value, telemetry.workload_id)
        span.set_attribute(
            CodonBaseSpanAttributes.WorkloadLogicId.value,
            telemetry.workload_logic_id,
        )
        span.set_attribute(CodonBaseSpanAttributes.WorkloadRunId.value, telemetry.workload_run_id)
        span.set_attribute(CodonBaseSpanAttributes.WorkloadName.value, telemetry.workload_name)
        span.set_attribute(
            CodonBaseSpanAttributes.WorkloadVersion.value,
            telemetry.workload_version,
        )
        if telemetry.deployment_id:
            span.set_attribute(
                CodonBaseSpanAttributes.DeploymentId.value,
                telemetry.deployment_id,
            )
        span.set_attribute(
            CodonBaseSpanAttributes.NodeInput.value,
            telemetry.node_input,
        )

        self._active[run_id] = _ActiveSpan(
            span=span,
            telemetry=telemetry,
            started_at=time.perf_counter(),
            run_id=run_id,
        )
        _ACTIVE_BY_TELEMETRY[id(telemetry)] = self._active[run_id]

    def on_chain_end(self, outputs: Mapping[str, Any], **kwargs: Any) -> None:
        run_id = kwargs.get("run_id")
        active = None
        if run_id is not None:
            active = self._active.pop(str(run_id), None)
        if active is None and len(self._active) == 1:
            active = self._active.pop(next(iter(self._active.keys())), None)
        if not active:
            return

        telemetry = active.telemetry
        telemetry.node_output = telemetry.node_output or _safe_repr(outputs)
        telemetry.duration_ms = int((time.perf_counter() - active.started_at) * 1000)
        if self._debug_usage_enabled:
            self._logger.info(
                "codon.langgraph usage debug: on_chain_end tokens input=%s output=%s total=%s usage_present=%s",
                telemetry.input_tokens,
                telemetry.output_tokens,
                telemetry.total_tokens,
                telemetry.token_usage is not None,
            )
        if telemetry.extra_attributes.get("codon_span_defer") and not telemetry.extra_attributes.get(
            "codon_span_finalized"
        ):
            if (
                telemetry.input_tokens is None
                and telemetry.output_tokens is None
                and telemetry.total_tokens is None
            ):
                telemetry.extra_attributes["codon_span_deferred"] = True
                if self._debug_usage_enabled:
                    self._logger.info("codon.langgraph usage debug: deferring span finalization")
                return

        _ACTIVE_BY_TELEMETRY.pop(id(telemetry), None)
        _finalize_node_span(active)
        config = _resolve_config(kwargs)
        if config is not None:
            _unregister_invocation_metadata(config, telemetry.node_name or "")

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        run_id = kwargs.get("run_id")
        active = None
        if run_id is not None:
            active = self._active.pop(str(run_id), None)
        if active is None and len(self._active) == 1:
            active = self._active.pop(next(iter(self._active.keys())), None)
        if not active:
            return
        telemetry = active.telemetry
        telemetry.status_code = "ERROR"
        telemetry.error_message = repr(error)
        active.span.record_exception(error)
        active.span.set_status(Status(StatusCode.ERROR, str(error)))

        telemetry.duration_ms = int((time.perf_counter() - active.started_at) * 1000)
        active.span.set_attribute(
            CodonBaseSpanAttributes.NodeLatencyMs.value,
            telemetry.duration_ms,
        )
        active.span.set_attribute(
            CodonBaseSpanAttributes.NodeStatusCode.value,
            telemetry.status_code,
        )
        if telemetry.error_message:
            active.span.set_attribute(
                CodonBaseSpanAttributes.NodeErrorMessage.value,
                telemetry.error_message,
            )

        raw_json = telemetry.to_raw_attributes_json()
        if raw_json:
            active.span.set_attribute(
                CodonBaseSpanAttributes.NodeRawAttributes.value,
                raw_json,
            )

        active.span.end()
        _ACTIVE_INVOCATION.set(None)
        _ACTIVE_BY_TELEMETRY.pop(id(telemetry), None)
        config = _resolve_config(kwargs)
        if config is not None:
            _unregister_invocation_metadata(config, telemetry.node_name or "")


class LangGraphTelemetryCallback(BaseCallbackHandler):
    """Captures model metadata and token usage from LangChain callbacks."""

    run_inline = False
    _logger = logging.getLogger(__name__)

    def __init__(self) -> None:
        if self._debug_usage_enabled():
            self._logger.info("codon.langgraph usage debug: LangGraphTelemetryCallback initialized")

    @staticmethod
    def _debug_usage_enabled() -> bool:
        return os.getenv("CODON_LANGGRAPH_DEBUG_USAGE") == "1"

    def on_llm_start(self, serialized: Mapping[str, Any], prompts: list[str], **kwargs: Any) -> None:
        invocation = _resolve_invocation(kwargs)
        if self._debug_usage_enabled():
            self._logger.info(
                "codon.langgraph usage debug: on_llm_start fired invocation_present=%s",
                bool(invocation),
            )
        if not invocation:
            return
        self._capture_llm_start(invocation, serialized, kwargs)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        invocation = _resolve_invocation(kwargs)
        if self._debug_usage_enabled():
            self._logger.info(
                "codon.langgraph usage debug: on_llm_end fired invocation_present=%s",
                bool(invocation),
            )
        if not invocation:
            return
        self._capture_llm_end(invocation, response)

    def _capture_message(self, invocation, message: Any) -> None:
        for attr in ("usage_metadata", "response_metadata", "metadata"):
            payload = getattr(message, attr, None)
            if isinstance(payload, Mapping):
                self._capture_payload(invocation, payload)

        additional = getattr(message, "additional_kwargs", None)
        if isinstance(additional, Mapping):
            for key in ("usage_metadata", "response_metadata", "usageMetadata"):
                data = additional.get(key)
                if isinstance(data, Mapping):
                    self._capture_payload(invocation, data)
        if self._debug_usage_enabled():
            usage = getattr(message, "usage_metadata", None)
            response_meta = getattr(message, "response_metadata", None)
            self._logger.info(
                "codon.langgraph usage debug: message usage_metadata=%s response_metadata=%s additional_keys=%s",
                isinstance(usage, Mapping),
                isinstance(response_meta, Mapping),
                sorted(additional.keys()) if isinstance(additional, Mapping) else None,
            )

    def _capture_payload(
        self,
        invocation,
        payload: Mapping[str, Any],
    ) -> None:
        usage, prompt_tokens, completion_tokens, total_tokens = _normalise_usage(payload)
        if usage:
            invocation.record_tokens(
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                total_tokens=total_tokens,
                token_usage=usage,
            )
        if self._debug_usage_enabled():
            self._logger.info(
                "codon.langgraph usage debug: payload_keys=%s usage_keys=%s prompt=%s completion=%s total=%s",
                sorted(payload.keys()),
                sorted(usage.keys()) if usage else None,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )

        model_identifier, model_vendor = _extract_model_info(payload)
        invocation.set_model_info(
            vendor=str(model_vendor) if model_vendor else None,
            identifier=str(model_identifier) if model_identifier else None,
        )

        response_metadata = _coerce_mapping(payload.get("response_metadata")) or _coerce_mapping(
            payload.get("metadata")
        )
        if response_metadata:
            invocation.add_network_call(dict(response_metadata))

    def _capture_llm_start(
        self,
        invocation: NodeTelemetryPayload,
        serialized: Mapping[str, Any],
        kwargs: Mapping[str, Any],
    ) -> None:
        params = _coerce_mapping(kwargs.get("invocation_params")) or _coerce_mapping(
            serialized.get("kwargs") if isinstance(serialized, Mapping) else None
        )

        identifier, vendor = _extract_model_info(params or {})

        if isinstance(serialized, Mapping):
            meta = _coerce_mapping(serialized.get("id"))
            serial_identifier, serial_vendor = _extract_model_info(serialized)
            identifier = identifier or serial_identifier
            vendor = vendor or _first(serial_vendor, meta.get("provider") if meta else None, serialized.get("name"))

        invocation.set_model_info(
            vendor=str(vendor) if vendor else None,
            identifier=str(identifier) if identifier else None,
        )

        if self._debug_usage_enabled():
            self._logger.info(
                "codon.langgraph usage debug: on_llm_start model=%s vendor=%s invocation_params_keys=%s",
                identifier,
                vendor,
                sorted(params.keys()) if isinstance(params, Mapping) else None,
            )

    def _capture_llm_end(self, invocation: NodeTelemetryPayload, response: Any) -> None:
        llm_output = _coerce_mapping(getattr(response, "llm_output", None))
        if llm_output:
            self._capture_payload(invocation, llm_output)
        if self._debug_usage_enabled():
            self._logger.info(
                "codon.langgraph usage debug: on_llm_end has_llm_output=%s has_response_metadata=%s has_usage_metadata=%s",
                bool(llm_output),
                bool(getattr(response, "response_metadata", None)),
                bool(getattr(response, "usage_metadata", None)),
            )

        response_metadata = _coerce_mapping(getattr(response, "response_metadata", None))
        if response_metadata:
            self._capture_payload(invocation, response_metadata)

        usage_metadata = _coerce_mapping(getattr(response, "usage_metadata", None))
        if usage_metadata:
            self._capture_payload(invocation, usage_metadata)

        generations = getattr(response, "generations", None)
        if generations:
            for generation_list in generations:
                for generation in generation_list:
                    metadata = getattr(generation, "generation_info", None)
                    if isinstance(metadata, Mapping):
                        self._capture_payload(invocation, metadata)

                    message = getattr(generation, "message", None)
                    if message is not None:
                        self._capture_message(invocation, message)
        if self._debug_usage_enabled() and generations:
            self._logger.info(
                "codon.langgraph usage debug: on_llm_end generations=%s",
                sum(len(g) for g in generations if g is not None),
            )


class BoundInvocationTelemetryCallback(LangGraphTelemetryCallback):
    """Telemetry callback bound to a specific node invocation."""

    def __init__(self, invocation: NodeTelemetryPayload) -> None:
        self._invocation = invocation
        super().__init__()

    def on_llm_start(self, serialized: Mapping[str, Any], prompts: list[str], **kwargs: Any) -> None:
        if self._debug_usage_enabled():
            self._logger.info("codon.langgraph usage debug: bound on_llm_start fired")
        self._capture_llm_start(self._invocation, serialized, kwargs)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        if self._debug_usage_enabled():
            self._logger.info("codon.langgraph usage debug: bound on_llm_end fired")
        self._capture_llm_end(self._invocation, response)
        if self._invocation.extra_attributes.get("codon_span_finalized"):
            return
        if self._invocation.extra_attributes.get("codon_span_deferred"):
            self._invocation.extra_attributes["codon_span_finalized"] = True
            active = _ACTIVE_BY_TELEMETRY.pop(id(self._invocation), None)
            if active is not None:
                _finalize_node_span(active)


def _extract_model_info(payload: Mapping[str, Any]) -> tuple[Optional[Any], Optional[Any]]:
    identifiers = (
        payload.get("model"),
        payload.get("model_name"),
        payload.get("model_id"),
        payload.get("modelName"),
    )
    vendors = (
        payload.get("model_vendor"),
        payload.get("provider"),
        payload.get("vendor"),
        payload.get("api_type"),
    )
    identifier = _first(*identifiers)
    vendor = _first(*vendors)
    if not identifier:
        meta = payload.get("response_metadata")
        if isinstance(meta, Mapping):
            identifier = _first(
                meta.get("model"),
                meta.get("model_name"),
                meta.get("model_id"),
            )
            vendor = _first(vendor, meta.get("model_vendor"), meta.get("provider"))
    return identifier, vendor


__all__ = ["LangGraphTelemetryCallback", "BoundInvocationTelemetryCallback"]
@dataclass(frozen=True)
class _MetadataKey:
    thread_id: str
    node_name: str


_METADATA_REGISTRY: dict[_MetadataKey, NodeTelemetryPayload] = {}
_METADATA_REGISTRY_LOCK = threading.Lock()


def _metadata_key_from_config(config: Mapping[str, Any], node_name: str) -> Optional[_MetadataKey]:
    metadata = config.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    codon_run_id = metadata.get("codon_run_id")
    if codon_run_id and node_name:
        return _MetadataKey(f"run:{codon_run_id}", str(node_name))
    thread_id = metadata.get("thread_id")
    langgraph_node = metadata.get("langgraph_node") or metadata.get("langgraph_node_name")
    node = langgraph_node or node_name
    scope_id = str(thread_id) if thread_id else None
    if not scope_id:
        checkpoint_ns = metadata.get("langgraph_checkpoint_ns")
        path = metadata.get("langgraph_path")
        step = metadata.get("langgraph_step")
        if checkpoint_ns is not None or path is not None or step is not None:
            scope_id = f"fallback:{checkpoint_ns}:{path}:{step}"
    if not scope_id or not node:
        if os.getenv("CODON_LANGGRAPH_DEBUG_USAGE") == "1":
            logger = logging.getLogger(__name__)
            logger.info(
                "codon.langgraph usage debug: metadata key missing scope_id=%s node=%s thread_id=%s checkpoint_ns=%s path=%s step=%s",
                scope_id,
                node,
                thread_id,
                metadata.get("langgraph_checkpoint_ns"),
                metadata.get("langgraph_path"),
                metadata.get("langgraph_step"),
            )
        return None
    return _MetadataKey(str(scope_id), str(node))


def _register_invocation_metadata(config: Mapping[str, Any], node_name: str, telemetry: NodeTelemetryPayload) -> bool:
    key = _metadata_key_from_config(config, node_name)
    if not key:
        return False
    with _METADATA_REGISTRY_LOCK:
        _METADATA_REGISTRY[key] = telemetry
    return True


def _unregister_invocation_metadata(config: Mapping[str, Any], node_name: str) -> None:
    key = _metadata_key_from_config(config, node_name)
    if not key:
        return
    with _METADATA_REGISTRY_LOCK:
        _METADATA_REGISTRY.pop(key, None)


def _lookup_invocation_metadata(config: Mapping[str, Any]) -> Optional[NodeTelemetryPayload]:
    metadata = config.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    codon_run_id = metadata.get("codon_run_id")
    node = metadata.get("langgraph_node") or metadata.get("langgraph_node_name")
    if codon_run_id and node:
        key = _MetadataKey(f"run:{codon_run_id}", str(node))
        with _METADATA_REGISTRY_LOCK:
            return _METADATA_REGISTRY.get(key)
    thread_id = metadata.get("thread_id")
    if not thread_id or not node:
        return None
    key = _MetadataKey(str(thread_id), str(node))
    with _METADATA_REGISTRY_LOCK:
        return _METADATA_REGISTRY.get(key)
