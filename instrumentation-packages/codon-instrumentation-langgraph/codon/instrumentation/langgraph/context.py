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

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from codon_sdk.agents import Workload
from codon_sdk.instrumentation.schemas.nodespec import NodeSpec


@dataclass(frozen=True)
class GraphInvocationContext:
    workload: Workload
    node_specs: Mapping[str, NodeSpec]
    run_id: str
    deployment_id: Optional[str]
    organization_id: Optional[str]
    org_namespace: Optional[str]
    graph_definition: Optional[Dict[str, Any]]


_ACTIVE_GRAPH_CONTEXT: ContextVar[Optional[GraphInvocationContext]] = ContextVar(
    "codon_langgraph_active_graph_context", default=None
)

_ACTIVE_CONFIG: ContextVar[Optional[Mapping[str, Any]]] = ContextVar(
    "codon_langgraph_active_config", default=None
)


def current_graph_context() -> Optional[GraphInvocationContext]:
    return _ACTIVE_GRAPH_CONTEXT.get()


def current_langgraph_config() -> Optional[Mapping[str, Any]]:
    return _ACTIVE_CONFIG.get()

__all__ = [
    "GraphInvocationContext",
    "_ACTIVE_GRAPH_CONTEXT",
    "_ACTIVE_CONFIG",
    "current_graph_context",
    "current_langgraph_config",
]
