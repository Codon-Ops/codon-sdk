import pytest

core_module = pytest.importorskip("codon_sdk.instrumentation.config")
langgraph_module = pytest.importorskip("codon.instrumentation.langgraph")


def test_initialize_telemetry_reexported():
    assert langgraph_module.initialize_telemetry is core_module.initialize_telemetry
