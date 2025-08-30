from codon_sdk.instrumentation.schemas.telemetry.spans import (
    CodonBaseSpanAttributes,
    CodonSpanNames,
)


def test_codon_base_span_attributes():
    assert CodonBaseSpanAttributes.OrgNamespace.value == "org.namespace"
    assert CodonBaseSpanAttributes.AgentFramework.value == "agent.framework.name"


def test_codon_span_names():
    assert CodonSpanNames.AgentRun.value == "agent.run"
    assert CodonSpanNames.AgentTool.value == "agent.tool"
    # Add more assertions for all members of CodonSpanNames
    assert len(CodonSpanNames) == 116
