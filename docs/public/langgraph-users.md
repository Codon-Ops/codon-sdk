# For LangGraph Users

If you're already using LangGraph, the Codon SDK provides seamless integration through the `LangGraphWorkloadAdapter`. This allows you to wrap your existing StateGraphs with minimal code changes while gaining comprehensive telemetry and observability.

## Understanding State Graph vs Compiled Graph

LangGraph has two distinct graph representations:
- **State Graph**: The graph you define and add nodes to during development
- **Compiled Graph**: The executable version created when you want to run the graph

The `LangGraphWorkloadAdapter` works by wrapping your StateGraph and compiling it for you, allowing you to pass compile keyword arguments for features like checkpointers and long-term memory.

## Using LangGraphWorkloadAdapter

The primary way to integrate LangGraph with Codon is through the `LangGraphWorkloadAdapter.from_langgraph()` method:

```python
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver
from codon.instrumentation.langgraph import LangGraphWorkloadAdapter

# Your existing StateGraph
db_agent_graph = StateGraph(SQLAnalysisState)
db_agent_graph.add_node("query_resolver_node", self.query_resolver_node)
db_agent_graph.add_node("query_executor_node", self.query_executor_node)
# ... add more nodes and edges

# Wrap with Codon adapter
self._graph = LangGraphWorkloadAdapter.from_langgraph(
    db_agent_graph,
    name="LangGraphSQLAgentDemo",
    version="0.1.0",
    description="A SQL agent created using the LangGraph framework",
    tags=["langgraph", "demo", "sql"],
    compile_kwargs={"checkpointer": MemorySaver()}
)
```

### Automatic Node Inference

The adapter automatically infers nodes from your StateGraph, eliminating the need to manually instrument each node with decorators. This provides comprehensive telemetry out of the box.

### Compile Keyword Arguments

You can pass any LangGraph compile arguments through `compile_kwargs`:
- Checkpointers for persistence
- Memory configurations  
- Custom compilation options

## Manual Instrumentation with @track_node

If you need more granular control over specific nodes, you can still use the `@track_node` decorator:

```python
from codon.instrumentation.langgraph import initialize_telemetry, track_node

initialize_telemetry(service_name="codon-langgraph-demo")

@track_node("retrieve_docs", role="retriever")
def retrieve_docs(query: str) -> List[str]:
    ...
```

When the decorated function executes, the LangGraph package:
- materializes a `NodeSpec` and captures its ID, signature, and schemas
- wraps execution in an OpenTelemetry span (async and sync supported)
- records inputs, outputs, and wall-clock latency via standardized span attributes

Spans are exported with `org.namespace`, `agent.framework.name`, and the Codon span names defined in `codon_sdk.instrumentation.schemas.telemetry.spans`.

## Best Practices

1. **Use the adapter first**: Start with `LangGraphWorkloadAdapter.from_langgraph()` for automatic instrumentation
2. **Add manual decorators sparingly**: Only use `@track_node` when you need specific control over certain nodes
3. **Initialize telemetry early**: Call `initialize_telemetry()` before creating your workloads