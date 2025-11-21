"""Generate API reference pages."""
import mkdocs_gen_files

# Generate content for api-reference.md
with mkdocs_gen_files.open("api-reference.md", "w") as f:
    f.write("""# API Reference

## Core SDK (`codon_sdk`)

### Agents

::: codon_sdk.agents.CodonWorkload

::: codon_sdk.agents.ExecutionReport

### Instrumentation Schemas

::: codon_sdk.instrumentation.schemas.nodespec.NodeSpec

::: codon_sdk.instrumentation.schemas.logic_id.LogicRequest

## Instrumentation Packages

### LangGraph Integration (`codon-instrumentation-langgraph`)

::: codon.instrumentation.langgraph.initialize_telemetry

::: codon.instrumentation.langgraph.LangGraphWorkloadAdapter
""")