# Copyright 2025 Codon, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Primary interface for defining and executing Codon workloads.

The ``Workload`` base class captures the responsibilities described in the
"Workload builder spec" design note. Instrumentation packages should subclass or
conform to this interface to provide framework-specific behavior while keeping
agent logic portable across execution environments.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence

from codon_sdk.instrumentation.schemas.nodespec import NodeSpec


@dataclass(frozen=True)
class WorkloadMetadata:
    """Immutable descriptor for a workload's portable identity."""

    name: str
    version: str
    description: Optional[str] = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", tuple(self.tags))


class Workload(ABC):
    """Template class for building, registering, and executing agent workloads.

    Subclasses are expected to:
      * register the *Logic Group* (Agent Class ID, NodeSpecs, Logic ID) during
        initialization,
      * provide auto-instrumented ``add_node`` helpers that wrap raw callables,
      * bind executions to a Deployment ID inside :meth:`execute` and emit
        telemetry, and
      * coordinate with framework-specific mixins (defined in instrumentation
        packages) that expose convenience constructors such as ``from_langgraph``
        or ``from_openai``.
    """

    def __init__(
        self,
        *,
        name: str,
        version: str,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> None:
        self._metadata = WorkloadMetadata(
            name=name,
            version=version,
            description=description,
            tags=tuple(tags or ()),
        )
        self._register_logic_group()

    @property
    def metadata(self) -> WorkloadMetadata:
        """Portable workload descriptor (name, version, description, tags)."""

        return self._metadata

    @property
    @abstractmethod
    def agent_class_id(self) -> str:
        """Human-readable identifier that groups versions of the workload."""

    @property
    @abstractmethod
    def logic_id(self) -> str:
        """Stable hash representing the full logical structure of the workload."""

    @property
    @abstractmethod
    def nodes(self) -> Sequence[NodeSpec]:
        """Ordered collection of NodeSpecs that define the workload graph."""

    @property
    @abstractmethod
    def topology(self) -> Iterable[tuple[str, str]]:
        """Iterable of ``(source_name, destination_name)`` graph edges."""

    @abstractmethod
    def _register_logic_group(self) -> None:
        """Register Agent Class, NodeSpecs, and Logic ID.

        Implementations should:
          * derive an Agent Class ID from :attr:`metadata`,
          * materialize NodeSpecs for any eagerly declared nodes, and
          * compute the Logic ID for the current graph configuration.
        """

    @abstractmethod
    def add_node(
        self,
        function: Callable[..., Any],
        name: str,
        role: str,
        *,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> NodeSpec:
        """Register and instrument a node as part of the workload graph."""

    @abstractmethod
    def add_edge(self, source_name: str, destination_name: str) -> None:
        """Declare an ordering dependency between two registered nodes."""

    @abstractmethod
    def execute(self, payload: Any, *, deployment_id: str, **kwargs: Any) -> Any:
        """Execute the workload logic bound to a specific deployment context."""
