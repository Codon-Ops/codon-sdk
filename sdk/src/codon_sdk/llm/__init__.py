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

"""Utilities for instrumenting LLM calls within Codon workloads."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from codon_sdk.instrumentation.telemetry import NodeTelemetryPayload
from codon_sdk.instrumentation.schemas.telemetry.spans import CodonSpanNames
from codon_sdk.agents import CodonWorkload  # noqa: F401  (export convenience)

try:  # pragma: no cover - make dependency optional
    from codon.instrumentation.langgraph import current_invocation
except Exception:  # pragma: no cover - defensive fallback

    def current_invocation() -> Optional[NodeTelemetryPayload]:  # type: ignore
        return None


__all__ = [
    "track_llm_async",
    "track_llm",
]


async def track_llm_async(
    func: Callable[..., Awaitable[Any]],
    *args: Any,
    config: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    usage_extractor: Optional[Callable[[Any, NodeTelemetryPayload], None]] = None,
    span_name: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Execute an async LLM call while capturing telemetry and spans.

    Parameters are forwarded to the callable after Codon instrumentation is
    applied. ``config`` is merged with the current node's runtime config when
    available (LangChain support).
    """

    payload = current_invocation()
    tracer = trace.get_tracer("codon.llm")
    span_name = span_name or CodonSpanNames.AgentLLM.value

    span_kwargs: dict[str, Any] = {}
    if metadata:
        span_kwargs.update(metadata)
    if payload:
        span_kwargs.setdefault("codon.nodespec.id", payload.nodespec_id)
        span_kwargs.setdefault("codon.workload.logic_id", payload.workload_logic_id)
        span_kwargs.setdefault("codon.workload.run_id", payload.workload_run_id)

    with tracer.start_as_current_span(span_name) as span:
        for key, value in span_kwargs.items():
            if value is not None:
                span.set_attribute(key, value)

        merged_config = _merge_config(config)

        try:
            if merged_config is not None:
                try:
                    result = await func(*args, config=merged_config, **kwargs)  # type: ignore[arg-type]
                except TypeError:
                    result = await func(*args, **kwargs)
            else:
                result = await func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - propagate original exceptions
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise

        _populate_telemetry(payload, result, metadata, usage_extractor)
        _apply_payload_to_span(payload, span)
        return result


def track_llm(
    func: Callable[..., Any],
    *args: Any,
    config: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    usage_extractor: Optional[Callable[[Any, NodeTelemetryPayload], None]] = None,
    span_name: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Synchronous counterpart to :func:`track_llm_async`."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    else:  # pragma: no cover - guard against misuse
        raise RuntimeError(
            "track_llm cannot be called from an async context; use track_llm_async"
        )

    if loop is None:

        async def runner() -> Any:
            return await track_llm_async(
                func,
                *args,
                config=config,
                metadata=metadata,
                usage_extractor=usage_extractor,
                span_name=span_name,
                **kwargs,
            )

        return asyncio.run(runner())

    raise RuntimeError("track_llm cannot determine event loop state")


def _merge_config(override: Optional[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if override is None:
        return None

    merged: dict[str, Any] = {}
    callbacks_list: list[Any] = []

    for key, value in override.items():
        if key == "callbacks":
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                callbacks_list.extend(value)
            else:
                callbacks_list.append(value)
        else:
            merged[key] = value

    if callbacks_list:
        merged["callbacks"] = callbacks_list

    return merged if merged else None


def _populate_telemetry(
    payload: Optional[NodeTelemetryPayload],
    response: Any,
    metadata: Optional[Mapping[str, Any]],
    usage_extractor: Optional[Callable[[Any, NodeTelemetryPayload], None]],
) -> None:
    if payload is None:
        return

    usage = _coerce_mapping(getattr(response, "usage", None))
    response_metadata = _coerce_mapping(getattr(response, "response_metadata", None))
    usage_metadata = _coerce_mapping(getattr(response, "usage_metadata", None))

    for candidate in filter(None, (usage, usage_metadata, response_metadata)):
        _apply_usage(payload, candidate)

    if usage_extractor:
        usage_extractor(response, payload)

    model_identifier = _first(
        getattr(response, "model", None),
        getattr(response, "model_name", None),
        getattr(response, "model_id", None),
    )
    if model_identifier:
        payload.set_model_info(identifier=str(model_identifier))

    provider = _first(
        getattr(response, "provider", None),
        getattr(response, "vendor", None),
    )
    if provider:
        payload.set_model_info(vendor=str(provider))

    if metadata and metadata.get("request_id"):
        payload.extra_attributes.setdefault("request_id", metadata["request_id"])


def _apply_payload_to_span(payload: Optional[NodeTelemetryPayload], span) -> None:
    if payload is None:
        return

    if payload.input_tokens is not None:
        span.set_attribute("codon.tokens.input", payload.input_tokens)
    if payload.output_tokens is not None:
        span.set_attribute("codon.tokens.output", payload.output_tokens)
    if payload.total_tokens is not None:
        span.set_attribute("codon.tokens.total", payload.total_tokens)
    if payload.model_name:
        span.set_attribute("codon.model.name", payload.model_name)
    if payload.model_vendor:
        span.set_attribute("codon.model.vendor", payload.model_vendor)
    if payload.model_identifier:
        span.set_attribute("codon.model.id", payload.model_identifier)


def _apply_usage(payload: NodeTelemetryPayload, usage: Mapping[str, Any]) -> None:
    prompt = _first(
        usage.get("prompt_tokens"),
        usage.get("input_tokens"),
        usage.get("prompt_token_count"),
        usage.get("input_token_count"),
        usage.get("promptTokenCount"),
        usage.get("inputTokenCount"),
    )
    completion = _first(
        usage.get("completion_tokens"),
        usage.get("output_tokens"),
        usage.get("completion_token_count"),
        usage.get("output_token_count"),
        usage.get("completionTokenCount"),
        usage.get("outputTokenCount"),
    )
    total = _first(
        usage.get("total_tokens"),
        usage.get("token_count"),
        usage.get("totalTokenCount"),
    )

    payload.record_tokens(
        input_tokens=prompt,
        output_tokens=completion,
        total_tokens=total,
        token_usage=dict(usage),
    )


def _coerce_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    for attr in ("to_dict", "dict", "model_dump"):
        method = getattr(value, attr, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return result
    if hasattr(value, "__dict__"):
        return {
            key: getattr(value, key)
            for key in vars(value)
            if not key.startswith("_")
        }
    return None


def _first(*values: Any) -> Optional[Any]:
    for value in values:
        if value:
            return value
    return None
