# Codon Agents Guide

This document is a living map for developers building agents in the Codon ecosystem. It tracks how the shared SDK and the instrumentation packages work together, what guarantees exist today, and where the roadmap is headed. Update it as patterns solidify.

## How the Pieces Fit
- [`sdk/AGENTS.md`](sdk/AGENTS.md) describes the core primitives—`Workload` interface, the opinionated `CodonWorkload` implementation, instrumentation mixin guidelines, `NodeSpec`, logic ID hashing, and telemetry vocab—that every agent or framework integration should rely on.
- `docs/guides/codon-workload-quickstart.md` shows an end-to-end example of composing and running a workload directly with the SDK.
- [`instrumentation-packages/codon-instrumentation-langgraph/AGENTS.md`](instrumentation-packages/codon-instrumentation-langgraph/AGENTS.md) covers the LangGraph decorators, the `LangGraphWorkloadAdapter`, and how to inherit telemetry automatically.
- [`instrumentation-packages/codon-instrumentation-openai/AGENTS.md`](instrumentation-packages/codon-instrumentation-openai/AGENTS.md) will track OpenAI-specific instrumentation work. It currently outlines expectations and open tasks.

If you are introducing a new framework integration, create an `AGENTS.md` alongside it and link back here.

## Building Agents with Codon Today
1. Model your callable units with `NodeSpec` so they have deterministic IDs and schemas.
2. Canonicalize workloads with logic IDs to gain idempotency and consistent metrics.
3. Wrap execution using a framework-specific instrumentation module to emit spans enriched with Codon metadata.

Telemetry defaults to OpenTelemetry OTLP exporters; align your environment variables before running agents.

## Work in Progress
- The OpenAI instrumentation package is still a stub—see its `AGENTS.md` for the punch list.
- SDK testing and documentation are light; expect breaking changes as the contracts tighten.
- Additional frameworks (e.g., LangChain, LiteLLM) may join this layout. Document them here when they land.

## Contribution Guidelines
- Keep the `AGENTS.md` files in sync with code changes that alter agent-facing behavior.
- When introducing new span attributes or schema fields, document the rationale and adoption plan in the relevant file.
- Raise cross-cutting decisions here so downstream integrations stay aligned.
- Reference `docs/guides/workload-mixin-guidelines.md` when adding new framework adapters.
- Keep mixin definitions inside their respective instrumentation packages so they can evolve independently of the SDK.

## Next Steps for Authors
- Decide on shared conventions for tracing, logging, and error surfaces.
- Expand SDK examples showing NodeSpec usage within end-to-end agent flows.
- Set up continuous documentation review so these guides evolve with the project.
