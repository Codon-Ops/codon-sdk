# Codon LangGraph Adapter

If you're already using LangGraph, the Codon SDK provides seamless integration through the `LangGraphWorkloadAdapter`. This allows you to wrap your existing StateGraphs with minimal code changes while gaining comprehensive telemetry and observability.

## Deprecation Notice (LangGraph 0.3.x)

Support for LangGraph 0.3.x is deprecated and will be removed after the `0.1.0a5` release of `codon-instrumentation-langgraph`. If you need to stay on LangGraph 0.3.x, pin this package at `<=0.1.0a5`. Starting with `0.2.0a0`, the adapter will support only LangChain/LangGraph v1.x.

### python-warnings

When running with LangGraph 0.3.x you will see a `DeprecationWarning` explaining the cutoff. To silence the warning, set:

```
CODON_LANGGRAPH_DEPRECATION_SILENCE=1
```

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

# Wrap with Codon adapter (returns an instrumented graph)
self._graph = LangGraphWorkloadAdapter.from_langgraph(
    db_agent_graph,
    name="LangGraphSQLAgentDemo",
    version="0.1.0",
    description="A SQL agent created using the LangGraph framework",
    tags=["langgraph", "demo", "sql"],
    compile_kwargs={"checkpointer": MemorySaver()}
)

# Invoke the graph as usual
result = self._graph.invoke({"question": "Which locations pay data engineers the most?"})

# Access workload metadata if needed
workload = self._graph.workload
```

## Instrumenting Prebuilt Graphs (create_agent)

LangChain v1's `create_agent` returns a compiled LangGraph graph, which means you can wrap it directly without rebuilding a `StateGraph`. (See the LangChain Studio docs: https://docs.langchain.com/oss/python/langchain/studio.)

```python
from langchain.agents import create_agent
from codon.instrumentation.langgraph import LangGraphWorkloadAdapter

agent_graph = create_agent(
    model=model,
    tools=tools,
    system_prompt="You are a helpful assistant.",
)

graph = LangGraphWorkloadAdapter.from_langgraph(
    agent_graph,
    name="PrebuiltAgent",
    version="1.0.0",
    node_overrides={
        # Optional: restore NodeSpec fidelity when wrapping compiled graphs
        "planner": {"role": "planner", "callable": planner_fn},
        "agent": {"role": "agent", "model_name": "gpt-4o"},
    },
)

result = graph.invoke({"input": "Summarize the latest updates."})
```

Notes:
- Compiled graphs can obscure callable signatures and schemas, so `node_overrides` is the easiest way to restore full NodeSpec metadata.
- If you only have the compiled graph, you can still list available node names via `graph.nodes.keys()` and use those keys in `node_overrides`.

### Automatic Node Inference

The adapter automatically infers nodes from your StateGraph, eliminating the need to manually instrument each node with decorators. This provides comprehensive telemetry out of the box.

**Note:** Only fired nodes are represented in a workload run, so the complete workload definition may not be present in the workload run summary. This is particularly relevant for LangGraph workflows with conditional edges and branching logic—your execution reports will show actual paths taken, not all possible paths.

### Compile Keyword Arguments

You can pass any LangGraph compile arguments through `compile_kwargs`:
- Checkpointers for persistence
- Memory configurations
- Custom compilation options

## Graph Snapshot Span

Each graph invocation emits a single graph snapshot span (one per run) that captures the full node/edge structure. This lets downstream analysis understand the full graph shape even when only a subset of nodes executed.

## Edge Cases & Limitations

- **Direct SDK calls:** If a node calls a provider SDK directly (not via a LangChain runnable), callbacks will not fire and token usage metadata will be missing.
- **Custom runnables:** Runnables that do not expose `invoke/ainvoke` cannot be auto-wrapped with config injection.
- **Async context boundaries:** Background tasks can drop ContextVar state, which may prevent config propagation into LLM calls.
- **Provider usage metadata:** Some providers only return token usage when explicitly enabled (especially in streaming).

## Best Practices

1. **Use the adapter**: `LangGraphWorkloadAdapter.from_langgraph()` provides comprehensive instrumentation with just a few lines of code
2. **Initialize telemetry early**: Call `initialize_telemetry()` before creating your workloads
3. **Leverage compile_kwargs**: Pass checkpointers and memory configurations through the adapter
