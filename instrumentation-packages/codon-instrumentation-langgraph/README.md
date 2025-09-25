# Codon LangGraph Adapter

This adapter lets you wrap an existing LangGraph `StateGraph` inside Codon’s `CodonWorkload`. By doing so you inherit:

- automatic `NodeSpec` creation and logic ID generation
- OpenTelemetry spans through `track_node`
- the token-based runtime with audit ledger

## Quick Start
```python
from codon.instrumentation.langgraph import LangGraphWorkloadAdapter
from myproject.langgraph import graph

workload = LangGraphWorkloadAdapter.from_langgraph(
    graph,
    name="LangGraphAgent",
    version="1.0.0",
)

result = workload.execute({"state": initial_state}, deployment_id="dev")
```

See `AGENTS.md` for more detailed instructions and advanced usage.
