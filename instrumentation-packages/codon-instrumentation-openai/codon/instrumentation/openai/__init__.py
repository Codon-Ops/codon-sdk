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
