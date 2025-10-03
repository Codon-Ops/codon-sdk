# LangGraph Workload Adapter

This document explains how to convert an existing LangGraph `StateGraph` into a fully instrumented Codon `CodonWorkload`. The adapter preserves your LangGraph runtime behaviour while layering in NodeSpec generation, telemetry, audit logging, and logic ID management.

---

## Why Wrap a LangGraph Graph?
- **Zero instrumentation boilerplate:** every LangGraph node is auto-wrapped with `track_node`, producing OpenTelemetry spans without manual decorators.
- **Stable identifiers:** nodes become `NodeSpec`s with deterministic SHA-256 IDs, and the overall graph gets a logic ID for caching, retries, and provenance.
- **Audit-first runtime:** executions use Codon’s token scheduler, producing a detailed ledger (token enqueue/dequeue, node completions, custom events) for compliance.
- **Drop-in ergonomics:** call `LangGraphWorkloadAdapter.from_langgraph(graph, ...)` and keep your existing LangGraph code unchanged.

---

## Basic Usage
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

---

## Mapping LangGraph Nodes to Codon Nodes
The adapter inspects your graph to extract:
- **Name:** from the LangGraph node key.
- **Callable:** the runnable/function associated with the node.
- **Role:** derived from node metadata or the node name (can be overridden).

You can influence roles by passing a `role_overrides` dictionary:
```python
workload = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="SupportBot",
    version="2.3.0",
    role_overrides={
        "plan": "planner",
        "write": "author",
        "critique": "qa",
    },
)
```
These roles propagate to telemetry span attributes (e.g., `codon.nodespec.role`).

---

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

---

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

---

## Advanced Example: Reflection Loop
Here’s a minimal LangGraph snippet demonstrating fan-out/fan-in with reflection. We reuse it through the adapter to gain structured telemetry and audit logs.

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

---

## Telemetry & Audit Integration
- Call `initialize_telemetry(service_name=...)` once during process startup to export spans via OTLP.
- Each node span now carries workload metadata (`codon.workload.id`, `codon.workload.run_id`, `codon.workload.logic_id`, `codon.workload.deployment_id`, `codon.organization.id`) so traces can be rolled up by workload, deployment, or organization without joins.
- `LangGraphTelemetryCallback` is attached automatically when invoking LangChain runnables; it captures model vendor/identifier, token usage (prompt, completion, total), and response metadata, all of which is emitted as span attributes (`codon.tokens.*`, `codon.model.*`, `codon.node.raw_attributes_json`).
- Instrumentation writes into the shared `NodeTelemetryPayload` (`runtime.telemetry`) defined by the SDK so future mixins collect the same schema-aligned fields without reimplementing bookkeeping.
- Node inputs/outputs and latency are recorded alongside status codes, enabling the `trace_events` schema to be populated directly from exported span data.
- The audit ledger still covers token enqueue/dequeue, node completions, custom events (`runtime.record_event`), and stop requests for replay and compliance workflows.

### Analytics Alignment
- The span attribute set is designed to satisfy the MVP telemetry tables in `docs/design/Codon Telemetry Data Schema - MVP Version.txt`. You can aggregate by `nodespec_id` or `logic_id` to compute token totals, error rates, or latency buckets per node.
- `codon.node.raw_attributes_json` serialises token usage and provider metadata so downstream ETL jobs can populate `raw_attributes_json` in the Iceberg schema without additional enrichment jobs.

---

## Limitations & Roadmap
- Conditional edges: currently you emit along every registered edge; to mimic conditionals, have your node wrapper decide which edges receive tokens. Future versions aim to map LangGraph’s conditional constructs directly.
- Streaming tokens / concurrency: not yet supported; the adapter processes tokens sequentially (though you can extend it for concurrency).
- Persistence: the workload runtime is in-memory today. Roadmap includes pluggable stores for tokens/state/audit (see `docs/vision/codon-workload-design-philosophy.md`).

---

## Further Reading
- [`docs/guides/workload-mixin-guidelines.md`](../../../../docs/guides/workload-mixin-guidelines.md) – general guidance for framework adapters.
- [`docs/vision/codon-workload-design-philosophy.md`](../../../../docs/vision/codon-workload-design-philosophy.md) – broader roadmap, including persistence and compliance.
- [`../../sdk/AGENTS.md`](../../sdk/AGENTS.md) – core SDK primitives (`Workload`, `CodonWorkload`, logic IDs, telemetry schema).

Feel free to extend the adapter with custom node metadata, additional audit hooks, or alternative execution semantics as your LangGraph usage grows.
