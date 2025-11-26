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

**Note:** Only fired nodes are represented in a workload run, so the complete workload definition may not be present in the workload run summary. This is particularly relevant for LangGraph workflows with conditional edges and branching logic—your execution reports will show actual paths taken, not all possible paths.

### Compile Keyword Arguments

You can pass any LangGraph compile arguments through `compile_kwargs`:
- Checkpointers for persistence
- Memory configurations
- Custom compilation options

## Basic Usage Example

```python
from codon.instrumentation.langgraph import LangGraphWorkloadAdapter, initialize_telemetry
from langgraph.graph import StateGraph

# Optional: configure telemetry export once at startup
def bootstrap():
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
report = workload.execute({"state": initial_state}, deployment_id="dev")
print(report.node_results("writer")[-1])
print(f"Ledger entries: {len(report.ledger)}")
```

### What Happened?
1. Every LangGraph node was registered as a Codon node via `add_node`, producing a `NodeSpec`.
2. Edges in the LangGraph became workload edges, so `runtime.emit` drives execution.
3. `execute` seeded tokens with the provided state, ran the graph in token order, and captured telemetry & audit logs.
4. You can inspect `report.ledger` for compliance, or `report.node_results(...)` for business outputs.

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

## Handling State

- The adapter expects your token payload to contain a dictionary under the `"state"` key.
- Each LangGraph node receives that state, invokes the original runnable, and emits updated state to successors.
- Shared run-level data lives in `runtime.state`; you can read it from within nodes for cross-node coordination.

Example node signature inside your LangGraph graph:
```python
async def researcher(state):
    # state is whatever was previously emitted
    plan = state["plan"]
    insights = await fetch_insights(plan)
    return {"insights": insights}
```
When wrapped by the adapter, the Codon node sees `message["state"]` and merges the returned dict with the existing state.

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
At execution time you can still override entry nodes via `workload.execute(..., entry_nodes=[...])` if needed.

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
result = workload.execute({"state": {"topic": "urban gardens"}}, deployment_id="demo")
print(result.node_results("finalize")[-1])
```
The ledger records each iteration through the loop, and `runtime.state` tracks iteration counts for auditing.

## Telemetry & Observability Benefits

- Each node span carries workload metadata (`codon.workload.id`, `codon.workload.run_id`, `codon.workload.logic_id`, `codon.workload.deployment_id`, `codon.organization.id`) so traces can be rolled up by workload, deployment, or organization without joins.
- `LangGraphTelemetryCallback` is attached automatically when invoking LangChain runnables; it captures model vendor/identifier, token usage (prompt, completion, total), and response metadata, all of which is emitted as span attributes (`codon.tokens.*`, `codon.model.*`, `codon.node.raw_attributes_json`).
- Node inputs/outputs and latency are recorded alongside status codes, enabling comprehensive observability.
- The audit ledger covers token enqueue/dequeue, node completions, custom events (`runtime.record_event`), and stop requests for replay and compliance workflows.

## Adapter Options & Artifacts

- Use `compile_kwargs={...}` when calling `LangGraphWorkloadAdapter.from_langgraph(...)` to compile your graph with checkpointers, memory stores, or any other LangGraph runtime extras. The adapter still inspects the pre-compiled graph for node metadata while compiling with the provided extras so the runtime is ready to go.
- Set `return_artifacts=True` to receive a `LangGraphAdapterResult` containing the `CodonWorkload`, the original state graph, and the compiled graph. This makes it easy to hand both artifacts to downstream systems (e.g., background runners) without re-compiling.
- Provide `runtime_config={...}` during adaptation to establish default invocation options (e.g., base callbacks, tracing settings). At execution time, pass `langgraph_config={...}` to `workload.execute(...)` to layer per-run overrides; both configs are merged and supplied alongside Codon's telemetry callback.
- Regardless of the return value, the resulting workload exposes `langgraph_state_graph`, `langgraph_compiled_graph`, `langgraph_compile_kwargs`, and `langgraph_runtime_config` for quick access to the underlying LangGraph objects.