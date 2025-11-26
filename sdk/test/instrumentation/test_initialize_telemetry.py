import pytest

from codon_sdk.instrumentation import DEFAULT_INGEST_ENDPOINT
from codon_sdk.instrumentation import config as instrumentation_config


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    for key in [
        "CODON_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
    ]:
        monkeypatch.delenv(key, raising=False)
    yield


def test_initialize_telemetry_uses_defaults(monkeypatch):
    captured = {}

    class DummyExporter:
        def __init__(self, *, endpoint=None, headers=None, **kwargs):
            captured["endpoint"] = endpoint
            captured["headers"] = headers

    provider_holder = {}

    monkeypatch.setattr(
        instrumentation_config,
        "OTLPSpanExporter",
        DummyExporter,
    )
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: provider_holder.setdefault("provider", provider),
    )

    instrumentation_config.initialize_telemetry()

    assert captured["endpoint"] == DEFAULT_INGEST_ENDPOINT
    assert captured["headers"] == {}
    provider = provider_holder["provider"]
    assert provider.resource.attributes["service.name"] == "unknown_codon_service"


def test_initialize_telemetry_prefers_arguments(monkeypatch):
    monkeypatch.setenv("CODON_API_KEY", "env-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "env-service")

    captured = {}

    class DummyExporter:
        def __init__(self, *, endpoint=None, headers=None, **kwargs):
            captured["endpoint"] = endpoint
            captured["headers"] = headers

    provider_holder = {}
    monkeypatch.setattr(
        instrumentation_config,
        "OTLPSpanExporter",
        DummyExporter,
    )
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: provider_holder.setdefault("provider", provider),
    )

    instrumentation_config.initialize_telemetry(
        api_key="arg-key",
        service_name="arg-service",
        endpoint="http://arg:4317",
    )

    assert captured["endpoint"] == "http://arg:4317"
    assert captured["headers"] == {"x-codon-api-key": "arg-key"}
    provider = provider_holder["provider"]
    assert provider.resource.attributes["service.name"] == "arg-service"


def test_initialize_telemetry_env_fallback(monkeypatch):
    monkeypatch.setenv("CODON_API_KEY", "env-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "env-service")

    captured = {}

    class DummyExporter:
        def __init__(self, *, endpoint=None, headers=None, **kwargs):
            captured["endpoint"] = endpoint
            captured["headers"] = headers

    provider_holder = {}
    monkeypatch.setattr(
        instrumentation_config,
        "OTLPSpanExporter",
        DummyExporter,
    )
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: provider_holder.setdefault("provider", provider),
    )

    instrumentation_config.initialize_telemetry()

    assert captured["endpoint"] == "http://env:4317"
    assert captured["headers"] == {"x-codon-api-key": "env-key"}
    provider = provider_holder["provider"]
    assert provider.resource.attributes["service.name"] == "env-service"
