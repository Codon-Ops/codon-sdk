# What is the Codon SDK?

## Why Codon SDK?

Building AI agents is one thing. Operating them reliably in production is another. Most frameworks help you create agents, but leave critical gaps when it comes to audit trails, observability, and deployment portability. How do you debug a [multi-step agent workflow](building-from-scratch.md)? How do you track costs and performance across different models and API calls? How do you ensure compliance in regulated environments? How do you deploy the same agent logic across different environments without rewriting code?

## What It Does

Codon SDK bridges this gap by providing production-ready infrastructure for AI agents. It wraps your existing framework code with [comprehensive observability](instrumentation/), audit trails, and deployment flexibility—without forcing you to abandon the tools you already know.

The SDK provides common building blocks including immutable node specifications, logic ID generation, and a shared telemetry vocabulary. [Framework-specific instrumentation packages](instrumentation/) emit OpenTelemetry spans enriched with Codon metadata.

## Core Capabilities

**Audit-First Architecture**
- Every agent run generates a complete, replayable audit trail
- Immutable provenance tracking for every decision and data transformation
- Built for environments where you need to explain AI behavior

**Framework-Agnostic Observability**
- Instrument existing [LangGraph](instrumentation/langgraph.md), OpenAI, and other framework code with minimal changes
- Standardized OpenTelemetry output works with any monitoring stack
- [Pluggable instrumentation packages](instrumentation/) adapt to your current tools

**Deterministic Identity System**
- Stable SHA-256 identifiers for functions, workflows, and deployments
- Enables reliable caching, deduplication, and version tracking
- Same logic produces same identifiers across environments

**Production-Ready Execution**
- Portable logic that runs consistently from development to production
- Flexible graph patterns supporting cycles, feedback loops, and streaming
- Separation of agent logic from deployment-specific configurations

[Get started with the core concepts →](getting-started.md)

## Design Philosophy

Codon Workload is the heart of our emerging agentic framework. The principles that guide its design:

### Guiding Principles

1. **Portability Over Infrastructure Lock-In**  
   Workloads must remain portable across environments. The same logic graph should run locally, in CI, or in production without re-authoring code. Runtime concerns (telemetry, persistence, scaling) should be injectable, not baked into agents.

2. **Audit First**  
   Every agent run should be replayable. Provenance—who emitted a token, when, with which payload—needs to be preserved. This is not just a compliance checkbox; it is foundational for trust, debugging, and postmortems.

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

**For Development Teams:**
- **Faster debugging**: Complete visibility into multi-step agent workflows eliminates guesswork
- **Framework flexibility**: Keep using [LangGraph](instrumentation/langgraph.md), OpenAI, or other tools you know—just add observability
- **Reliable deployments**: Same agent logic runs consistently across development, staging, and production

**For Operations Teams:**
- **Production confidence**: Comprehensive monitoring and alerting for AI agent behavior
- **Audit compliance**: Built-in provenance tracking meets regulatory requirements
- **Infrastructure independence**: Standard OpenTelemetry output works with your existing monitoring stack

[Explore detailed API documentation →](api-reference.md)

**For Organizations:**
- **Risk mitigation**: Full transparency into AI decision-making processes  
- **Operational excellence**: Treat AI agents with the same rigor as traditional software systems
- **Strategic flexibility**: Evolve your AI stack without being locked into specific vendors or frameworks