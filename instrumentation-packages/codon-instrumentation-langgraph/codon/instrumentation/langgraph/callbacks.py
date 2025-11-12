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
from typing import Any, Mapping, Optional

try:  # pragma: no cover - optional dependency
    from langchain.callbacks.base import BaseCallbackHandler
except Exception:  # pragma: no cover - fallback when LangChain is absent

    class BaseCallbackHandler:  # type: ignore
        """Minimal stand-in to keep instrumentation optional."""

        pass

from . import current_invocation


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


class LangGraphTelemetryCallback(BaseCallbackHandler):
    """Captures model metadata and token usage from LangChain callbacks."""

    def on_llm_start(self, serialized: Mapping[str, Any], prompts: list[str], **kwargs: Any) -> None:
        invocation = current_invocation()
        if not invocation:
            return

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

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        invocation = current_invocation()
        if not invocation:
            return

        llm_output = _coerce_mapping(getattr(response, "llm_output", None))
        if llm_output:
            self._capture_payload(invocation, llm_output)

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


__all__ = ["LangGraphTelemetryCallback"]
