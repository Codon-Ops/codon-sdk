# What is the Codon SDK?

Codon SDK provides common building blocks for Codon agents, including immutable node specifications, logic ID generation, and a shared telemetry vocabulary. This repository also houses framework-specific instrumentation packages that emit OpenTelemetry spans enriched with Codon metadata.

## Key Features
- Immutable `NodeSpec` records that introspect Python callables and generate stable SHA-256 identifiers tied to organization, role, and model metadata.
- Canonical logic request hashing that deduplicates workloads by agent class, participating nodes, and topology.
- OpenTelemetry span attribute catalog for agent runs, tools, LLMs, and vector database interactions.
- Pluggable instrumentation packages (e.g., LangGraph) that decorate nodes, capture latency, and forward spans to OTLP endpoints.

## Design Philosophy

Codon Workload is the heart of our emerging agentic framework. The principles that guide its design:

### Guiding Principles

1. **Portability Over Infrastructure Lock-In**  
   Workloads must remain portable across environments. The same logic graph should run locally, in CI, or in production without re-authoring code. Runtime concerns (telemetry, persistence, scaling) should be injectable, not baked into agents.

2. **Audit First**  
   Every agent run should be replayable. Provenancewho emitted a token, when, with which payloadneeds to be preserved. This is not just a compliance checkbox; it is foundational for trust, debugging, and postmortems.

3. **Composable Runtime**  
   The framework provides a default execution engine, but its components (token queues, state store, audit sink) are intended to be swappable. Teams should be able to plug in bespoke back-ends without rewriting agent logic.

4. **Graph Flexibility**  
   Agents are not restricted to DAGs. Feedback loops, streaming, and reactive behaviours are first-class. The runtime must therefore handle cycles and long-lived flows gracefully.

5. **Low Cognitive Load for Developers**  
   Authoring an agent should feel familiar: define functions, register them as nodes, wire edges. The runtime handles orchestration, tokens, and logging behind the scenes.

## What We Have Today

### Token-Based Execution
- Each node receives a token `message`, operates on it, and can emit new tokens to downstream nodes via `runtime.emit(...)`.
- Tokens carry immutable provenance: unique ID, lineage, parent link, timestamps, and origin node.
- Shared per-run state (`runtime.state`) allows nodes to coordinate while keeping logic in regular Python functions.

### Auditable Ledger
- Every enqueue, dequeue, node completion, custom event, and stop request is recorded as an `AuditEvent`.
- `ExecutionReport` bundles node results, the audit ledger, runtime context (`deployment_id`, `logic_id`, `run_id`), and helper methods for quick inspection.
- Developers can insert their own audit entries using `runtime.record_event(...)` to add business-specific metadata.

### Compliance-Focused Errors and Guardrails
- `WorkloadRegistrationError` highlights graph definition issues (duplicate nodes, missing edges).
- `WorkloadRuntimeError` covers invalid routing (emitting to unregistered nodes), step limit breaches, and unexpected node failures.
- `max_steps` can cap execution cycles to prevent runaway loops.

## Why This Matters

- **Transparency**: By default we capture the entire "tape" of an agent run. Teams can replay what happened, not just infer from logs.
- **Flexibility**: Agent authors are not boxed into DAG-only workflows. Loops, streaming, branching, and concurrent patterns are all viable.
- **Extensibility**: The framework is not tied to a single broker or storage engine. You can start with an in-memory runtime and graduate to production-grade infrastructure without refactoring agent logic.
- **Compliance Readiness**: We treat audit as a first-class feature, not an afterthought. As persistence lands, the logs will remain provable and verifiable across environments.