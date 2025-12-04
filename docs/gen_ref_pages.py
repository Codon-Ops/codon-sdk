"""Generate API reference pages."""
import mkdocs_gen_files

# Generate content for api-reference.md
with mkdocs_gen_files.open("api-reference.md", "w") as f:
    f.write("""# API Reference

[View source on GitHub](https://github.com/Codon-Ops/codon-sdk)

## Core SDK (`codon_sdk`)

### Agents

::: codon_sdk.agents.CodonWorkload

::: codon_sdk.agents.ExecutionReport

### Instrumentation

::: codon_sdk.instrumentation.initialize_telemetry

### Instrumentation Schemas

::: codon_sdk.instrumentation.schemas.nodespec.NodeSpec

::: codon_sdk.instrumentation.schemas.logic_id.LogicRequest

## Instrumentation Packages

### LangGraph Integration (`codon-instrumentation-langgraph`)

::: codon.instrumentation.langgraph.initialize_telemetry

::: codon.instrumentation.langgraph.LangGraphWorkloadAdapter
""")