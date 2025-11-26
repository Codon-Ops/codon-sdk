# Codon SDK Agent Primitives

This scaffold explains the agent-facing contracts provided by `codon_sdk`. Flesh it out as APIs mature and new helper modules appear.

## Workload Interface
- **Module:** `codon_sdk.agents.workload`
- **Class:** `Workload`
- **Purpose:** Defines the portable workload contract that framework adapters must implement. Captures metadata (name, version, description, tags), registers Agent Class / Logic IDs, and exposes graph-building plus execution hooks.
- **Expectations:** Subclasses auto-register logic in `_register_logic_group`, wrap callables in `add_node`, manage topology via `add_edge`, and bind a run to `deployment_id` inside `execute` while emitting telemetry.
- **Instrumentation mixins:** Framework packages ship their own mixins (see `docs/guides/workload-mixin-guidelines.md`) to expose `from_*` constructors while keeping the core SDK agnostic.
- **Reference implementation:** Each instrumentation package should define mixins inside its own namespace (e.g., `codon.instrumentation.langgraph.LangGraphWorkloadMixin`).
- **Adapters:** `LangGraphWorkloadAdapter.from_langgraph(...)` demonstrates how to wrap existing LangGraph graphs with `CodonWorkload` automatically; use it as a model for future adapters.

## CodonWorkload (Opinionated Implementation)
- **Module:** `codon_sdk.agents.codon_workload`
- **Class:** `CodonWorkload`
- **Purpose:** Provide a token-based runtime for bespoke agents, including audit-ready provenance capture.
- **Execution model:** Nodes receive a token `message`, interact with a runtime handle to emit downstream tokens, record custom events, share per-run state, and optionally halt execution.
- **Execution context:** Every node also receives a `context` mapping containing `workload_id`, `logic_id`, `workload_run_id`, `deployment_id`, and organisation metadata so instrumentation layers can stamp spans and logs with the identifiers required by the Codon telemetry schema.
- **Telemetry payload:** `runtime.telemetry` exposes a shared `NodeTelemetryPayload` (`codon_sdk.instrumentation.telemetry`) that instrumentation mixins use to enrich spans/logs/metrics with token usage, model metadata, network calls, and rollout identifiers.
- **Streaming:** `execute_streaming_async(...)` exposes an async generator of `StreamEvent`s (`token_enqueued`, `node_completed`, `workflow_finished`, etc.). `execute_streaming(...)` wraps it for synchronous code, making it a drop-in replacement for frameworks that already use `stream`/`astream` patterns.
- **Audit trail:** `execute(...)` returns an `ExecutionReport` with node results plus an immutable ledger of all enqueue/dequeue and completion events.
- **Error handling:** Raises `WorkloadRegistrationError` for registration issues and `WorkloadRuntimeError` for runtime violations (unknown routes, step limits, etc.).
- **Async support:** Run `await workload.execute_async(...)` inside event loops; the synchronous `execute(...)` delegates to the async implementation for convenience.

### Minimal Example
```python
from codon_sdk.agents import CodonWorkload


def ingest(message, *, runtime, context):
    lines = message["document"].splitlines()
    runtime.emit("summarize", {"lines": lines})
    return {"line_count": len(lines)}


def summarize(message, *, runtime, context):
    runtime.record_event("summary_started", {"lines": len(message["lines"])})
    return {
        "title": message["lines"][0] if message["lines"] else "",
        "line_count": len(message["lines"]),
        "deployment": context["deployment_id"],
    }


workload = CodonWorkload(name="ReportAgent", version="0.2.0")
workload.add_node(ingest, name="ingest", role="parser")
workload.add_node(summarize, name="summarize", role="responder")
workload.add_edge("ingest", "summarize")

report = workload.execute(
    {"document": "Status Update\nWeek 42"},
    deployment_id="dev-cluster-1",
    invoked_by="cli",
)

# In async contexts (e.g., notebooks) prefer:
# report = await workload.execute_async(...)

print(report.node_results("summarize")[-1]["line_count"])  # -> 2
print(len(report.ledger))  # -> auditable event stream
```

For a full walkthrough, see `docs/guides/codon-workload-quickstart.md`.

## NodeSpec Lifecycle
- **Purpose:** Provide immutable, hashed descriptors for agent nodes so telemetry, caching, and orchestration can agree on identity.
- **Current usage:** `NodeSpec` introspects Python callables, requires `ORG_NAMESPACE`, and produces span attributes defined in `NodeSpecSpanAttributes`.
- **To document:** Validation rules, strategies for functions without type hints, and migration guidance when schema versions bump.

### Quickstart Checklist
1. Ensure `ORG_NAMESPACE` is set in the environment (or pass `org_namespace` explicitly).
2. Annotate callable inputs/outputs—schemas are derived from type hints.
3. Initialize `NodeSpec` during module import so IDs stay stable.
4. Surface `nodespec.id` and related metadata in your agent’s telemetry or persistence layer.

## Logic ID Canonicalization
- **Purpose:** Detect duplicate workloads and support idempotent scheduling.
- **Key classes:** `AgentClass`, `Topology`, `LogicRequest`, and helpers in `logic_id`.
- **To expand:** Examples involving multiple nodes, topology edges, and how logic IDs interact with retries or cache stores.

## Telemetry Vocabulary
- `codon_sdk.instrumentation.schemas.telemetry.spans` defines span names and base attributes shared across frameworks.
- Document additions here before using them in instrumentation packages to keep alignment.
- Telemetry initialization is centralized in `codon_sdk.instrumentation.initialize_telemetry`, with default endpoint `https://ingest.codonops.ai:4317` and `x-codon-api-key` header support (args override env; env vars `OTEL_EXPORTER_OTLP_ENDPOINT`, `CODON_API_KEY`, `OTEL_SERVICE_NAME` remain valid). Optional attach mode (`attach_to_existing` arg or `CODON_ATTACH_TO_EXISTING_OTEL_PROVIDER` env) lets you add Codon’s exporter to an existing tracer provider instead of replacing it—useful when OTEL auto-instrumentation is already active.

## Extending the SDK
- Capture requirements for new schema fields inside each class docstring and mirror them here.
- Outline testing expectations (e.g., `pytest` targets) as they are established.
- Note backward-compatibility policies once releases begin.

## Open Questions
- How will version negotiation work between agents and orchestration layers?
- Do we standardize error reporting alongside spans?
- Should helper utilities exist for agents that are not framework-backed?

> Update this file every time you introduce a new agent contract or refine the public API. Treat it as the canonical reference for downstream instrumentation packages.
