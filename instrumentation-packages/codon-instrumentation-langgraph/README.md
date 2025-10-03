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

# Adding compile-time extras (e.g., checkpointer)
from langgraph.checkpoint.memory import InMemorySaver

workload_with_ckpt = LangGraphWorkloadAdapter.from_langgraph(
    graph,
    name="LangGraphAgent",
    version="1.0.0",
    compile_kwargs={"checkpointer": InMemorySaver()},
)

# Override or extend at invocation time if needed
run = workload_with_ckpt.execute(
    {"state": initial_state},
    deployment_id="dev",
    langgraph_config={"metadata": "run-123"},
)
```

See `AGENTS.md` for more detailed instructions and advanced usage.
