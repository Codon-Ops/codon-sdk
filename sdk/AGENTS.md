# Codon SDK Agent Primitives

This scaffold explains the agent-facing contracts provided by `codon_sdk`. Flesh it out as APIs mature and new helper modules appear.

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

## Extending the SDK
- Capture requirements for new schema fields inside each class docstring and mirror them here.
- Outline testing expectations (e.g., `pytest` targets) as they are established.
- Note backward-compatibility policies once releases begin.

## Open Questions
- How will version negotiation work between agents and orchestration layers?
- Do we standardize error reporting alongside spans?
- Should helper utilities exist for agents that are not framework-backed?

> Update this file every time you introduce a new agent contract or refine the public API. Treat it as the canonical reference for downstream instrumentation packages.
