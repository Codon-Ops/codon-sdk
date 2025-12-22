# LangGraph Workload Adapter

This document explains how to convert an existing LangGraph `StateGraph` into a fully instrumented Codon `CodonWorkload`. The adapter preserves your LangGraph runtime behaviour while layering in NodeSpec generation, telemetry, audit logging, and logic ID management.

---

## Deprecation Notice (LangGraph 0.3.x)
- `codon-instrumentation-langgraph` `0.1.0a5` is the last release that supports LangGraph 0.3.x.
- Starting with `0.2.0a0`, the adapter targets LangChain/LangGraph v1.x only.
- A `DeprecationWarning` is emitted when LangGraph < 1.0 is detected (set `CODON_LANGGRAPH_DEPRECATION_SILENCE=1` to suppress).

---

## Why Wrap a LangGraph Graph?
- **Zero instrumentation boilerplate:** every LangGraph node is auto-wrapped with `track_node`, producing OpenTelemetry spans without manual decorators.
- **Stable identifiers:** nodes become `NodeSpec`s with deterministic SHA-256 IDs, and the overall graph gets a logic ID for caching, retries, and provenance.
- **Telemetry-first runtime:** executions use native LangGraph semantics while Codon emits spans for each node invocation and workload run metadata for downstream analysis.
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

graph = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="ResearchAgent",
    version="1.0.0",
    description="Wrapped LangGraph research workflow",
    tags=["langgraph", "codon"],
)

initial_state = {"topic": "Sustainable cities"}
result = graph.invoke({"topic": "Sustainable cities"})
print(result)
```

### What Happened?
1. Every LangGraph node was registered as a Codon `NodeSpec` for deterministic IDs.
2. The adapter returned an instrumented graph that preserves native LangGraph execution semantics.
3. Telemetry spans are emitted via callbacks during normal LangGraph invocation (no `execute` call required).

---

## Mapping LangGraph Nodes to Codon Nodes
The adapter inspects your graph to extract:
- **Name:** from the LangGraph node key.
- **Callable:** the runnable/function associated with the node.
- **Role:** derived from node metadata or the node name.

Need finer control? Provide a `node_overrides` mapping where each entry is either a plain dict or `NodeOverride` object. You can specify the role, callable used for `NodeSpec` introspection, model metadata, and explicit schemas:
```python
graph = LangGraphWorkloadAdapter.from_langgraph(
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

---

## Handling State
- The adapter does not alter LangGraph state semantics. Nodes receive the same state and return the same updates they would without Codon instrumentation.

Example node signature inside your LangGraph graph:
```python
async def researcher(state):
    # state is whatever was previously emitted
    plan = state["plan"]
    insights = await fetch_insights(plan)
    return {"insights": insights}
```
When wrapped by the adapter, the original LangGraph node callable is preserved and invoked as usual.

---

## Entry Nodes
By default the adapter infers entry nodes as those with no incoming edges. You can override this by supplying `entry_nodes`:
```python
graph = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="OpsAgent",
    version="0.4.1",
    entry_nodes=["bootstrap"],
)
```
Entry nodes are still inferred from the LangGraph structure; override them by changing the graph itself before compilation.

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

graph = LangGraphWorkloadAdapter.from_langgraph(
    langgraph,
    name="ReflectiveAgent",
    version="0.1.0",
)
result = graph.invoke({"topic": "urban gardens"})
print(result)
```
Each iteration is reflected in node spans and the graph snapshot span ties the run to the full graph definition.

---

## Adapter Options & Artifacts
- Use `compile_kwargs={...}` when calling `LangGraphWorkloadAdapter.from_langgraph(...)` to compile your graph with checkpointers, memory stores, or any other LangGraph runtime extras. The adapter still inspects the pre-compiled graph for node metadata while compiling with the provided extras so the runtime is ready to go.
- Set `return_artifacts=True` to receive a `LangGraphAdapterResult` containing the `CodonWorkload`, the original state graph, the compiled graph, and the instrumented graph wrapper. This makes it easy to hand both artifacts to downstream systems (e.g., background runners) without re-compiling.
- Provide `runtime_config={...}` during adaptation to establish default invocation options (e.g., base callbacks, tracing settings). At invocation time, pass `config={...}` to `graph.invoke(...)` (or `graph.ainvoke(...)`) to layer per-run overrides; both configs are merged and supplied alongside Codon’s telemetry callbacks.
- The returned graph exposes `workload`, `langgraph_state_graph`, `langgraph_compiled_graph`, `langgraph_compile_kwargs`, and `langgraph_runtime_config` for quick access to the underlying LangGraph objects and metadata.

---

## Telemetry & Audit Integration
- Call `initialize_telemetry(service_name=...)` once during process startup to export spans via OTLP. The initializer now lives in the core SDK (`codon_sdk.instrumentation.initialize_telemetry`) and is re-exported here. It defaults the endpoint to `https://ingest.codonops.ai:4317`, injects `x-codon-api-key` from the argument or `CODON_API_KEY` env, and respects `OTEL_EXPORTER_OTLP_ENDPOINT`/`OTEL_SERVICE_NAME` overrides. If you already have an OTEL tracer provider (e.g., via auto-instrumentation), set `CODON_ATTACH_TO_EXISTING_OTEL_PROVIDER=true` or pass `attach_to_existing=True` to add Codon’s exporter to the existing provider instead of replacing it.
- Each node span now carries workload metadata (`codon.workload.id`, `codon.workload.run_id`, `codon.workload.logic_id`, `codon.workload.deployment_id`, `codon.organization.id`) so traces can be rolled up by workload, deployment, or organization without joins.
- Each graph invocation emits a single graph snapshot span (`agent.graph`) with node/edge structure serialized in `codon.graph.definition_json` for full topology visibility.
- `LangGraphTelemetryCallback` is attached automatically when invoking LangChain runnables; it captures model vendor/identifier, token usage (prompt, completion, total), and response metadata, all of which is emitted as span attributes (`codon.tokens.*`, `codon.model.*`, `codon.node.raw_attributes_json`).
- Instrumentation writes into the shared `NodeTelemetryPayload` (`runtime.telemetry`) defined by the SDK so future mixins collect the same schema-aligned fields without reimplementing bookkeeping.
- Node inputs/outputs and latency are recorded alongside status codes, enabling the `trace_events` schema to be populated directly from exported span data.
- Telemetry spans cover node inputs/outputs, latency, model usage, and workload/run identifiers without altering LangGraph execution.

### Analytics Alignment
- The span attribute set is designed to satisfy the MVP telemetry tables in `docs/design/Codon Telemetry Data Schema - MVP Version.txt`. You can aggregate by `nodespec_id` or `logic_id` to compute token totals, error rates, or latency buckets per node.
- `codon.node.raw_attributes_json` serialises token usage and provider metadata so downstream ETL jobs can populate `raw_attributes_json` in the Iceberg schema without additional enrichment jobs.

---

## Limitations & Roadmap
- Conditional edges: telemetry spans are emitted only for nodes actually executed; the graph snapshot span provides the full topology for downstream analysis.
- Streaming tokens: relies on LangGraph/LangChain streaming support; Codon captures model usage when providers expose usage metadata.
- Persistence: execution remains native to LangGraph; persistence is governed by your graph checkpointers and stores.
- Direct SDK calls: if a node bypasses LangChain runnables and calls provider SDKs directly, token usage callbacks are not emitted.
- Custom runnables: objects that do not implement `invoke/ainvoke` cannot be auto-wrapped for config injection.
- Async context boundaries: background tasks may lose ContextVar state, preventing automatic config propagation.

---

## Further Reading
- [`docs/guides/workload-mixin-guidelines.md`](../../../../docs/guides/workload-mixin-guidelines.md) – general guidance for framework adapters.
- [`docs/vision/codon-workload-design-philosophy.md`](../../../../docs/vision/codon-workload-design-philosophy.md) – broader roadmap, including persistence and compliance.
- [`../../sdk/AGENTS.md`](../../sdk/AGENTS.md) – core SDK primitives (`Workload`, `CodonWorkload`, logic IDs, telemetry schema).

Feel free to extend the adapter with custom node metadata, additional audit hooks, or alternative execution semantics as your LangGraph usage grows.
