import pytest
from types import SimpleNamespace
import logging

from codon_sdk.instrumentation import DEFAULT_INGEST_ENDPOINT
from codon_sdk.instrumentation import config as instrumentation_config


class DummyResource:
    def __init__(self, *, attributes):
        self.attributes = attributes


class DummyExporter:
    def __init__(self, *, endpoint=None, headers=None, **kwargs):
        self.endpoint = endpoint
        self.headers = headers or {}


class DummyProcessor:
    def __init__(self, exporter):
        self.span_exporter = exporter


class DummyProvider:
    def __init__(self, resource=None):
        self.resource = resource or DummyResource(attributes={})
        self.processors = []
        self._active_span_processor = SimpleNamespace(processors=self.processors)

    def add_span_processor(self, processor):
        self.processors.append(processor)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    for key in [
        "CODON_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "CODON_ATTACH_TO_EXISTING_OTEL_PROVIDER",
        "CODON_ORG_LOOKUP_URL",
        "CODON_ORG_LOOKUP_TIMEOUT",
    ]:
        monkeypatch.delenv(key, raising=False)
    instrumentation_config.set_default_org_namespace(None)
    yield


def _patch_base(monkeypatch, existing_provider=None):
    monkeypatch.setattr(instrumentation_config, "OTLPSpanExporter", DummyExporter)
    monkeypatch.setattr(instrumentation_config, "BatchSpanProcessor", DummyProcessor)
    monkeypatch.setattr(instrumentation_config, "TracerProvider", DummyProvider)
    monkeypatch.setattr(instrumentation_config, "Resource", DummyResource)
    monkeypatch.setattr(
        instrumentation_config.trace,
        "get_tracer_provider",
        lambda: existing_provider,
    )
    # Ensure warnings are captured
    monkeypatch.setattr(instrumentation_config, "logger", logging.getLogger("codon_test_logger"))


def test_initialize_telemetry_uses_defaults(monkeypatch):
    captured = {}
    warnings = []

    def capture_provider(provider):
        captured["provider"] = provider

    def capture_warning(msg):
        warnings.append(msg)

    _patch_base(monkeypatch, existing_provider=object())
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        capture_provider,
    )
    monkeypatch.setattr(instrumentation_config.logger, "warning", lambda msg: warnings.append(msg))

    instrumentation_config.initialize_telemetry()

    provider = captured["provider"]
    assert provider.processors  # processor added
    exporter = provider.processors[0].span_exporter
    assert exporter.endpoint == DEFAULT_INGEST_ENDPOINT
    assert exporter.headers == {}
    assert provider.resource.attributes["service.name"] == "unknown_codon_service"
    assert warnings  # warning about missing API key


def test_initialize_telemetry_prefers_arguments(monkeypatch):
    monkeypatch.setenv("CODON_API_KEY", "env-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "env-service")

    captured = {}
    _patch_base(monkeypatch, existing_provider=object())
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: captured.setdefault("provider", provider),
    )

    instrumentation_config.initialize_telemetry(
        api_key="arg-key",
        service_name="arg-service",
        endpoint="http://arg:4317",
    )

    provider = captured["provider"]
    exporter = provider.processors[0].span_exporter
    assert exporter.endpoint == "http://arg:4317"
    assert exporter.headers == {"x-codon-api-key": "arg-key"}
    assert provider.resource.attributes["service.name"] == "arg-service"


def test_initialize_telemetry_env_fallback(monkeypatch):
    monkeypatch.setenv("CODON_API_KEY", "env-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "env-service")

    captured = {}
    _patch_base(monkeypatch, existing_provider=object())
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: captured.setdefault("provider", provider),
    )

    instrumentation_config.initialize_telemetry()

    provider = captured["provider"]
    exporter = provider.processors[0].span_exporter
    assert exporter.endpoint == "http://env:4317"
    assert exporter.headers == {"x-codon-api-key": "env-key"}
    assert provider.resource.attributes["service.name"] == "env-service"


def test_initialize_attach_to_existing_provider(monkeypatch):
    existing = DummyProvider(resource=DummyResource(attributes={"service.name": "existing"}))

    _patch_base(monkeypatch, existing_provider=existing)
    monkeypatch.setenv("CODON_ATTACH_TO_EXISTING_OTEL_PROVIDER", "true")

    set_called = {"called": False}
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: set_called.__setitem__("called", True),
    )

    instrumentation_config.initialize_telemetry(api_key="attach-key", endpoint="http://arg:4317")
    assert set_called["called"] is False
    assert len(existing.processors) == 1
    exporter = existing.processors[0].span_exporter
    assert exporter.headers == {"x-codon-api-key": "attach-key"}
    assert exporter.endpoint == "http://arg:4317"

    # Calling again should not duplicate processors
    instrumentation_config.initialize_telemetry(api_key="attach-key", endpoint="http://arg:4317", attach_to_existing=True)
    assert len(existing.processors) == 1


def test_attach_flag_argument_overrides_env(monkeypatch):
    existing = DummyProvider(resource=DummyResource(attributes={}))
    _patch_base(monkeypatch, existing_provider=existing)
    monkeypatch.setenv("CODON_ATTACH_TO_EXISTING_OTEL_PROVIDER", "true")

    captured = {}
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: captured.setdefault("provider", provider),
    )

    instrumentation_config.initialize_telemetry(attach_to_existing=False)
    # attach disabled -> new provider set
    assert "provider" in captured
    assert captured["provider"] is not existing


def test_org_lookup_success(monkeypatch):
    monkeypatch.setenv("CODON_API_KEY", "env-key")
    monkeypatch.setenv("CODON_ORG_LOOKUP_URL", "http://lookup")

    captured = {}

    class DummyExporter:
        def __init__(self, *, endpoint=None, headers=None, **kwargs):
            captured["endpoint"] = endpoint
            captured["headers"] = headers

    class DummyResource:
        def __init__(self, *, attributes):
            self.attributes = attributes

        def merge(self, other):
            merged = dict(self.attributes)
            merged.update(other.attributes)
            return DummyResource(attributes=merged)

    def fake_lookup(*args, **kwargs):
        return ("ORG-1", "ns-1")

    _patch_base(monkeypatch, existing_provider=object())
    monkeypatch.setattr(
        instrumentation_config,
        "OTLPSpanExporter",
        DummyExporter,
    )
    monkeypatch.setattr(
        instrumentation_config,
        "Resource",
        DummyResource,
    )
    monkeypatch.setattr(
        instrumentation_config,
        "_resolve_org_metadata",
        lambda **kwargs: fake_lookup(),
    )
    provider_holder = {}
    monkeypatch.setattr(
        instrumentation_config.trace,
        "set_tracer_provider",
        lambda provider: provider_holder.setdefault("provider", provider),
    )

    instrumentation_config.initialize_telemetry()
    provider = provider_holder["provider"]
    attrs = provider.resource.attributes
    assert attrs["codon.organization.id"] == "ORG-1"
    assert attrs["org.namespace"] == "ns-1"
