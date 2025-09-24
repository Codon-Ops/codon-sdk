# LangGraph Instrumentation for Codon Agents

This guide documents how Codon’s LangGraph package decorates nodes and emits telemetry. It should evolve as we tighten contracts, add middleware, or expose new span attributes.

## What Exists Today
- `Workload` contract: LangGraph implementations must subclass `codon_sdk.agents.Workload` so the SDK can coordinate metadata, topology, and execution hooks across frameworks.
- `LangGraphWorkloadMixin`: defined in `codon.instrumentation.langgraph` and should be mixed into concrete workloads to expose `from_langgraph(...)` constructors consistent with the SDK guidelines.
- `initialize_telemetry` configures an OTLP exporter via OpenTelemetry SDK and reads `OTEL_SERVICE_NAME` if present.
- `track_node` wraps sync/async callables, materializes a `NodeSpec`, and records inputs, outputs, and latency.
- Span attributes combine Codon base keys (`org.namespace`, `agent.framework.name`) with LangGraph-specific fields defined in `attributes.py`.

## Usage Checklist
1. Install the package (`pip install -e instrumentation-packages/codon-instrumentation-langgraph`).
2. Set `ORG_NAMESPACE` and any OTEL exporter environment variables.
3. Call `initialize_telemetry(...)` once during startup.
4. Decorate LangGraph node functions with `@track_node(...)` and supply stable `node_name` / `role` values.
5. Validate that spans arrive in your collector with the expected Codon metadata.

## Integration Notes
- Ensure the wrapped function signatures stay consistent—`NodeSpec` hashes include the signature and annotations.
- For async nodes, the decorator uses `async def` wrappers; confirm any contextvars / tracing integrations remain compatible.
- Capture downstream IDs (workflow run IDs, user context) via additional span attributes if needed; document new keys here before adoption.

## Roadmap Topics
- Batch-friendly helpers for decorating entire LangGraph workflows.
- Support for configurable exporters (console, OTLP-http, custom processors).
- Error handling conventions (span status, exception events) and how they map to Codon telemetry.
- Flesh out `LangGraphWorkloadMixin.from_langgraph(...)` so it automatically translates LangGraph graphs into Codon workload instances.
- Cross-check your implementation against `docs/guides/workload-mixin-guidelines.md` for contract expectations.

Link back to [`../codon-instrumentation-openai/AGENTS.md`](../codon-instrumentation-openai/AGENTS.md) and [`../../sdk/AGENTS.md`](../../sdk/AGENTS.md) when cross-referencing shared concepts.
