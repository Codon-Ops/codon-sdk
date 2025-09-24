# OpenAI Instrumentation Plan for Codon Agents

This package is currently a placeholder. Use this document to coordinate the requirements and design for OpenAI-powered agent telemetry.

## Current Status
- Directory contains only a `.gitkeep` file; no instrumentation code is present yet.
- Dependency expectations, span schemas, and integration APIs still need to be defined.

## Proposed Scope
- Adopt the `codon_sdk.agents.Workload` interface so OpenAI integrations follow the same lifecycle (metadata, logic registration, execution binding).
- Implement the local `OpenAIWorkloadMixin` (see `codon.instrumentation.openai`) to expose `from_openai(...)` constructors without impacting other frameworks.
- Follow the shared mixin guidance in `docs/guides/workload-mixin-guidelines.md` when evolving the contract.
- Wrap OpenAI SDK calls (chat completions, assistants, vector stores) with Codon span attributes.
- Reuse `NodeSpec` or introduce a complementary descriptor for third-party API calls.
- Provide helpers for logging prompt/response metadata with safeguards for PII and token usage metrics.

## Immediate Next Steps
1. Decide on the primary OpenAI client(s) we support (official SDK, LangChain wrappers, etc.).
2. Define the minimal span schema—reference `codon_sdk.instrumentation.schemas.telemetry.spans` and extend as necessary.
3. Draft the `OpenAIWorkloadMixin.from_openai(...)` API surface (decorators, context managers, middleware) and sketch examples.
4. Implement tracer initialization that aligns with the LangGraph package for consistency.

## Coordination
- Keep this file updated as design decisions land. Link to ADRs or design docs if they live elsewhere.
- When implementation begins, summarize module layout and usage patterns here.
- Ensure the root [`AGENTS.md`](../../AGENTS.md) references remain accurate.

## Open Questions
- How do we capture streaming responses while respecting token limits and privacy constraints?
- Should we integrate retry/backoff instrumentation alongside telemetry?
- What testing strategy (unit vs. integration with mocked OpenAI endpoints) will we adopt?

Mark updates with dates or changelog entries once work starts so contributors can track progress.
