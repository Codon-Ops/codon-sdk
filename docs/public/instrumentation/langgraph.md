# For LangGraph Users

If you're already using LangGraph, the Codon SDK provides seamless integration through the `LangGraphWorkloadAdapter`. This allows you to wrap your existing StateGraphs with minimal code changes while gaining comprehensive telemetry and observability. See [Execution and Results](../building-from-scratch.md#execution-and-results) for the complete interface that becomes available.

## Deprecation Notice (LangGraph 0.3.x)
Support for LangGraph 0.3.x is deprecated and will be removed after the 0.1.0a5 release of codon-instrumentation-langgraph. If you need to stay on LangGraph 0.3.x, pin this package at <=0.1.0a5. Starting with 0.2.0a0, the adapter will support only LangChain/LangGraph v1.x.

### python-warnings
When running with LangGraph 0.3.x you will see a DeprecationWarning explaining the cutoff. To silence the warning, set:

CODON_LANGGRAPH_DEPRECATION_SILENCE=1

## Prerequisites

- Python 3.9 or higher
- LangChain 1.0 or higher
- LangGraph 1.0 or higher

**Note:** The instrumentation package assumes that invocations to an LLM are being done using a `LangChain` interface. Other LLM client interfaces are not currently supported at this time and will not yield token metadata on the [**Codon Optimization Platform**](https://optimization.codonops.ai).

## Understanding State Graph vs Compiled Graph

LangGraph has two distinct graph representations:

- **State Graph**: The graph you define and add nodes to during development
- **Compiled Graph**: The executable version created when you want to run the graph

The `LangGraphWorkloadAdapter` works with either your StateGraph or CompiledGraph. When wrapping your StateGraph, the adapter compiles it for you, allowing you to pass compile keyword arguments for features like checkpointers and long-term memory. When wrapping a CompiledGraph, the adapter automatically inherits any pre-compiled features of that graph.

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
    edge_overrides=[
        ("__start__", "planner"),
        ("planner", "agent"),
        ("agent", "__end__"),
    ],
)

result = graph.invoke({"input": "Summarize the latest updates."})
```

Notes:
- Compiled graphs can obscure callable signatures and schemas, so `node_overrides` is the easiest way to restore full NodeSpec metadata.
- If you only have the compiled graph, you can still list available node names via `graph.nodes.keys()` and use those keys in `node_overrides`.
- If compiled graphs do not expose edges, you can supply `edge_overrides` to populate the graph snapshot span.


### Automatic Node Inference

The adapter automatically infers nodes from your StateGraph, eliminating the need to manually instrument each node with decorators. This provides comprehensive telemetry out of the box.

**Note:** Only fired nodes are represented in a workload run, so the complete workload definition may not be present in the workload run summary. This is particularly relevant for LangGraph workflows with conditional edges and branching logic—your execution reports will show actual paths taken, not all possible paths.

### Compile Keyword Arguments

You can pass any LangGraph compile arguments through `compile_kwargs`:
- Checkpointers for persistence
- Memory configurations
- Custom compilation options

## Basic Usage Example

```python
from codon_sdk.instrumentation import initialize_telemetry
from codon.instrumentation.langgraph import LangGraphWorkloadAdapter
from langgraph.graph import StateGraph

# Initialize telemetry for Codon platform integration
initialize_telemetry(service_name="langgraph-codon-demo")

# Suppose you already have a LangGraph defined elsewhere
from myproject.langgraph import build_graph

langgraph = build_graph()  # returns StateGraph or compiled graph

workload = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="ResearchAgent",
    version="1.0.0",
    description="Wrapped LangGraph research workflow",
    tags=["langgraph", "codon"],
)

initial_state = {"topic": "Sustainable cities"}
# Execute workload (also available: ainvoke() for async contexts)
report = workload.invoke({"state": initial_state})
print(report.get("writer")[-1])
```

### What Happened?
1. **LangGraph → CodonWorkload**: Your LangGraph was converted into a standard CodonWorkload while maintaining the same invocation interface that LangGraph uses (`invoke`, `ainvoke`, `stream`, `astream`) -- this way you only need to change your code in one place and everything else will just work.
2. **Node Registration**: Every LangGraph node was registered as a Codon node via `add_node`, producing a `NodeSpec`

3. **Token Execution**: `invoke` ran the graph and captured telemetry & audit logs


## Platform Integration

The `initialize_telemetry()` function in the example above connects your LangGraph workflow to the [**Codon Optimization Platform**](https://optimization.codonops.ai). This transforms your local OpenTelemetry spans into rich telemetry data visible in your Codon dashboard.

**Platform Setup Required**: Before initializing telemetry, you need a Codon API key. Follow the [Platform Setup guide](../getting-started.md#platform-setup) to:
1. Create your Codon account
2. Obtain your API key
3. Set the `CODON_API_KEY` environment variable

**What gets sent to the platform:**
- Every LangGraph node execution becomes an OpenTelemetry span with Codon metadata
- Node inputs, outputs, and performance metrics are captured automatically
- Workload-level tracing shows complete execution flow in your dashboard
- Cost attribution tracks token usage across different deployment environments

When you call `initialize_telemetry()`, the SDK configures OpenTelemetry to export these enriched spans directly to the configured endpoint. See configuration options below.

**Configuration:** See [Getting Started - Initializing Telemetry](../getting-started.md#initializing-telemetry) for configuration options.

## Node Overrides

Need finer control? Provide a `node_overrides` mapping where each entry is either a plain dict or `NodeOverride` object. You can specify the role, callable used for `NodeSpec` introspection, model metadata, and explicit schemas:
```python
workload = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="SupportBot",
    version="2.3.0",
    node_overrides={
        "plan": {
            "role": "planner",
            "callable": plan_node,
            "model_name": "gpt-4.1-mini",
        },
        "write": {"role": "author"},
        "critique": {"role": "qa", "output_schema": "CritiqueResult"},
    },
)
```
Any fields you omit fall back to the adapter defaults. Overrides propagate to telemetry span attributes (e.g., `codon.nodespec.role`, `codon.nodespec.model_name`) and the generated `NodeSpec` entries.

## Entry Nodes

By default the adapter infers entry nodes as those with no incoming edges. You can override this by supplying `entry_nodes`:
```python
workload = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="OpsAgent",
    version="0.4.1",
    entry_nodes=["bootstrap"],
)
```

## Advanced Example: Reflection Loop

Here's a minimal LangGraph snippet demonstrating fan-out/fan-in with reflection. We reuse it through the adapter to gain structured telemetry and audit logs.

```python
from langgraph.graph import StateGraph

async def planner(state):
    topic = state["topic"]
    return {"plan": f"Research plan for {topic}"}

async def writer(state):
    draft = f"Summary draft based on: {state['plan']}"
    return {"draft": draft}

async def critic(state):
    draft = state["draft"]
    if "community" in draft:
        return {"verdict": "ACCEPT"}
    return {"verdict": "REVISION: mention community."}

async def finalize(state):
    return {"summary": state["draft"], "verdict": state["verdict"]}

langgraph = StateGraph()
langgraph.add_node("planner", planner)
langgraph.add_node("writer", writer)
langgraph.add_node("critic", critic)
langgraph.add_node("finalize", finalize)
langgraph.add_edge("planner", "writer")
langgraph.add_edge("writer", "critic")
langgraph.add_edge("critic", "writer")  # feedback loop
langgraph.add_edge("critic", "finalize")

workload = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="ReflectiveAgent",
    version="0.1.0",
)
# Execute workload (also available: ainvoke() for async contexts)
result = workload.invoke({"state": {"topic": "urban gardens"}})
print(result.get("finalize")[-1])
```

## Telemetry & Observability Benefits

- Each node span carries workload metadata (`codon.workload.id`, `codon.workload.run_id`, `codon.workload.logic_id`, `codon.workload.deployment_id`, `codon.organization.id`) so traces can be rolled up by workload, deployment, or organization.
- `LangGraphTelemetryCallback` is attached automatically when invoking LangChain runnables; it captures model vendor/identifier, token usage (prompt, completion, total), and response metadata, all of which is emitted as span attributes (`codon.tokens.*`, `codon.model.*`, `codon.node.raw_attributes_json`).
- Node inputs/outputs and latency are recorded alongside status codes, enabling comprehensive observability.

## Adapter Options & Artifacts

- Use `compile_kwargs={...}` when calling `LangGraphWorkloadAdapter.from_langgraph(...)` to compile your graph with checkpointers, memory stores, or any other LangGraph runtime extras. The adapter still inspects the pre-compiled graph for node metadata while compiling with the provided extras so the runtime is ready to go.
- Provide `runtime_config={...}` during adaptation to establish default invocation options (e.g., base callbacks, tracing settings). At execution time, pass `langgraph_config={...}` to `workload.execute(...)` to layer per-run overrides; both configs are merged and supplied alongside Codon's telemetry callback.
- Regardless of the return value, the resulting workload exposes `langgraph_state_graph`, `langgraph_compiled_graph`, `langgraph_compile_kwargs`, and `langgraph_runtime_config` for quick access to the underlying LangGraph objects.
