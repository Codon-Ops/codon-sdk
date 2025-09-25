# Workload Mixin Implementation Guidelines

This guide documents how instrumentation packages should expose framework-specific mixins that extend the core `codon_sdk.agents.Workload` contract.

## Goals
- Keep the SDK’s base `Workload` class stable and framework-agnostic.
- Allow each instrumentation package to ship its own constructor helpers (`from_*` classmethods) without forcing SDK releases.
- Provide a consistent developer experience across frameworks so agents can be built programmatically from third-party artifacts (LangGraph graphs, OpenAI clients, etc.).

## Required Structure
1. **Define the mixin inside the instrumentation package** (e.g. `codon.instrumentation.langgraph.LangGraphWorkloadMixin`).
2. **Subclass `abc.ABC`** and declare abstract classmethods (`from_langgraph`, `from_openai`, …) that translate framework objects into a concrete `Workload`.
3. **Return `codon_sdk.agents.Workload`** (or a subclass) from the factory method. Use precise type hints so downstream tooling understands the contract.
4. **Document expectations in the package’s `AGENTS.md`**, linking back to this guide and cross-referencing `CodonWorkload` when relevant.
5. **Keep the mixin minimal**—do not assume specific orchestration logic beyond creating or configuring the workload. The `CodonWorkload` implementation in the SDK can be reused if it aligns with the framework’s execution semantics.

## Example Skeleton
```python
from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence

from codon_sdk.agents import Workload

class LangGraphWorkloadMixin(ABC):
    """Mixin contract for workloads built from LangGraph graphs."""

    @classmethod
    @abstractmethod
    def from_langgraph(
        cls,
        graph: Any,
        *,
        name: str,
        version: str,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> Workload:
        """Translate a LangGraph graph into a concrete Codon workload."""
```

## Implementation Checklist
- [ ] Ensure the underlying workload subclass calls `Workload.__init__` so metadata and registration happen immediately.
- [ ] Produce `NodeSpec` objects for every node introduced by the framework artifact.
- [ ] Wire up auto-instrumentation (decorators, context managers) within the mixin or helper utilities.
- [ ] Emit telemetry consistent with `codon_sdk.instrumentation.schemas.telemetry.spans`.
- [ ] Add tests that exercise `from_*` constructors, confirming logic IDs and topology expected values.

## Versioning Guidance
- Mixins should follow the instrumentation package’s versioning. Breaking changes do not require simultaneous SDK releases as long as the base `Workload` API remains intact.
- Maintain a changelog noting new or deprecated factory methods so downstream consumers can track compatibility.

For further architectural context, see `docs/design/Workload builder spec - Codon SDK.txt`.

### Reference Implementation
- The LangGraph instrumentation package ships `LangGraphWorkloadAdapter.from_langgraph(...)`, which converts a LangGraph `StateGraph` into a `CodonWorkload`, auto-registering nodes, edges, and telemetry. Use it as a template when building adapters for other ecosystems.
