"""LangChain callback handlers that enrich Codon telemetry."""
from __future__ import annotations

from typing import Any, Mapping, Optional

try:  # pragma: no cover - optional dependency
    from langchain.callbacks.base import BaseCallbackHandler
except Exception:  # pragma: no cover - fallback when LangChain is absent

    class BaseCallbackHandler:  # type: ignore
        """Minimal stand-in to keep instrumentation optional."""

        pass

from . import current_invocation


def _coerce_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) else None


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

        model_identifier = None
        model_vendor = None

        if params:
            model_identifier = _first(
                params.get("model"),
                params.get("model_name"),
                params.get("model_id"),
            )
            model_vendor = _first(
                params.get("provider"),
                params.get("vendor"),
                params.get("api_type"),
            )

        if isinstance(serialized, Mapping):
            model_vendor = _first(
                model_vendor,
                _coerce_mapping(serialized.get("id")) and serialized["id"].get("provider"),
                serialized.get("name"),
            )

        invocation.set_model_info(
            vendor=str(model_vendor) if model_vendor else None,
            identifier=str(model_identifier) if model_identifier else None,
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        invocation = current_invocation()
        if not invocation:
            return

        llm_output = _coerce_mapping(getattr(response, "llm_output", None))
        if llm_output:
            self._capture_payload(invocation, llm_output)

        generations = getattr(response, "generations", None)
        if generations:
            for generation_list in generations:
                for generation in generation_list:
                    metadata = getattr(generation, "generation_info", None)
                    if isinstance(metadata, Mapping):
                        self._capture_payload(invocation, metadata)

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

        model_identifier = _first(
            payload.get("model_name"),
            payload.get("model"),
            payload.get("model_id"),
        )
        model_vendor = _first(
            payload.get("model_vendor"),
            payload.get("provider"),
            payload.get("vendor"),
        )
        invocation.set_model_info(
            vendor=str(model_vendor) if model_vendor else None,
            identifier=str(model_identifier) if model_identifier else None,
        )

        response_metadata = _coerce_mapping(payload.get("response_metadata")) or _coerce_mapping(
            payload.get("metadata")
        )
        if response_metadata:
            invocation.add_network_call(dict(response_metadata))


__all__ = ["LangGraphTelemetryCallback"]
