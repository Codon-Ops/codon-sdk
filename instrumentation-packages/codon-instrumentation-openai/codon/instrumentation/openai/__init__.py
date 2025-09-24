"""OpenAI instrumentation helpers for Codon agents."""
from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence

from codon_sdk.agents import Workload

__all__ = ["OpenAIWorkloadMixin"]


class OpenAIWorkloadMixin(ABC):
    """Mixin contract for workloads that orchestrate OpenAI-powered logic."""

    @classmethod
    @abstractmethod
    def from_openai(
        cls,
        client: Any,
        *,
        name: str,
        version: str,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> Workload:
        """Build a workload from OpenAI client configuration and metadata."""

# Concrete implementations should provide behaviour in future revisions.
