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

from .version import __version__
from enum import Enum
from pydantic import BaseModel, Field, field_validator, PrivateAttr, ConfigDict
from typing import Optional, Callable, Any, Dict, Literal, get_type_hints
from typing_extensions import override
import hashlib
import inspect
import json
import os
import logging

logger = logging.getLogger(__name__)

class FunctionAnalysisResult(BaseModel):
    name: str = Field(description="The name of the function.")
    callable_signature: str = Field(
        description="The callable signature of the function."
    )
    input_schema: str = Field(description="The input schema of the function.")
    output_schema: Optional[str] = Field(
        default=None, description="The output schema of the function."
    )


class NodeSpecValidationError(Exception):
    pass


class NodeSpecEnv(BaseModel):
    OrgNamespace: str = Field(
        default="ORG_NAMESPACE",
        description="The namespace of the calling organization.",
    )
    OrgNamespaceDefault: str = Field(
        default="unknown",
        description="The default ORG_NAMESPACE value used when none is provided."
    )


nodespec_env = NodeSpecEnv()
_RESOLVED_ORG_NAMESPACE: Optional[str] = None


def set_default_org_namespace(namespace: Optional[str]) -> None:
    """Set a process-wide default org namespace, typically from API-key lookup."""

    global _RESOLVED_ORG_NAMESPACE
    _RESOLVED_ORG_NAMESPACE = namespace


class NodeSpec(BaseModel):
    """Immutable specification that introspects Python callables and generates stable SHA-256 identifiers.

    NodeSpec inspects Python callables to capture the function signature, type hints, and optional
    model metadata. It emits a deterministic SHA-256 ID that downstream systems can rely on.

    NodeSpec requires type annotations to build JSON schemas for inputs and outputs. If annotations
    are missing, the generated schemas may be empty.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(
        default=None, description="The NodeSpec ID generated from the NodeSpec."
    )
    spec_version: str = Field(
        default=__version__,
        description="The current version of the NodeSpec specification.",
    )
    org_namespace: str = Field(
        default=os.getenv(
            nodespec_env.OrgNamespace,
            nodespec_env.OrgNamespaceDefault
        ),
        description="The namespace of the calling organization.",
    )
    name: str = Field(description="The name of the node.")
    role: str = Field(description="The role of the node.")
    callable_signature: str = Field(description="The callable signature of the node.")
    input_schema: Optional[str] = Field(
        default=None, description="The input schema of the node."
    )
    output_schema: Optional[str] = Field(
        default=None, description="The output schema of the node."
    )
    model_name: Optional[str] = Field(
        default=None, description="The name of the model used in the node."
    )
    model_version: Optional[str] = Field(
        default=None, description="The version of the model currently used."
    )

    @override
    def __init__(
        self,
        name: str,
        role: str,
        callable: Callable[..., Any],
        org_namespace: Optional[str] = None,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        **kwargs,
    ):
        """Create a NodeSpec by introspecting a Python callable.

        Args:
            name: The name of the node.
            role: The role of the node.
            callable: The Python function to introspect.
            org_namespace: The namespace of the calling organization. Defaults to ORG_NAMESPACE env var.
            model_name: The name of the model used in the node.
            model_version: The version of the model currently used.
            **kwargs: Additional fields for the NodeSpec.

        Raises:
            NodeSpecValidationError: If ORG_NAMESPACE environment variable not set.

        Example:
            >>> nodespec = NodeSpec(
            ...     org_namespace="acme",
            ...     name="summarize",
            ...     role="processor",
            ...     callable=summarize_function,
            ...     model_name="gpt-4o",
            ...     model_version="2024-05-13"
            ... )
            >>> print(nodespec.id)
        """

        callable_attrs = analyze_function(callable)
        # Precedence: resolved default (e.g., from API-key lookup) > explicit arg/env > default placeholder
        namespace = _RESOLVED_ORG_NAMESPACE or org_namespace or os.getenv(nodespec_env.OrgNamespace)
        if not namespace:
            namespace = nodespec_env.OrgNamespaceDefault
            logger.warning(
                "NodeSpec created without org namespace; defaulting to '%s'. "
                "Provide an API key or set ORG_NAMESPACE to avoid shared identifiers.",
                namespace,
            )

        nodespec_id = self._generate_nodespec_id(
            callable_attrs=callable_attrs,
            org_namespace=namespace,
            name=name,
            role=role,
            model_name=model_name,
            model_version=model_version,
        )

        super().__init__(
            id=nodespec_id,
            org_namespace=namespace,
            name=name,
            role=role,
            callable_signature=callable_attrs.callable_signature,
            input_schema=callable_attrs.input_schema,
            output_schema=callable_attrs.output_schema,
            model_name=model_name,
            model_version=model_version,
            **kwargs,
        )

    @field_validator("spec_version", mode="before")
    @classmethod
    def _enforce_current_spec_version(cls, v: Any, info: Any) -> str:
        """This validator ensures that the spec_version used is the official one and won't be overridden."""
        if "spec_version" in info.data:
            raise NodeSpecValidationError("spec_version cannot be changed.")

        return __version__

    def _generate_nodespec_id(
        self,
        callable_attrs: FunctionAnalysisResult,
        org_namespace: str,
        name: str,
        role: str,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> str:
        """
        Generates a unique identifier for the node specification.
        """
        callable_attrs: Dict[str, str] = callable_attrs.model_dump(
            mode="json", exclude_none=True
        )
        nodespec_meta_attrs: Dict[str, str] = {
            "org_namespace": org_namespace,
            "name": name,
            "role": role,
        }
        if model_name:
            nodespec_meta_attrs["model_name"] = model_name
        if model_version:
            nodespec_meta_attrs["model_version"] = model_version

        canonical_spec: str = json.dumps(
            {**callable_attrs, **nodespec_meta_attrs},
            sort_keys=True,
            separators=(",", ":"),
        )

        to_hash: str = canonical_spec.strip()
        nodespec_id: str = nodespec_hash_method(hashable_string=to_hash)

        return nodespec_id


def nodespec_hash_method(hashable_string: str) -> str:
    """The method used to create the hash for the nodespec_id"""
    hasher = hashlib.sha256()
    hasher.update(hashable_string.encode("utf-8"))
    return hasher.hexdigest()


def analyze_function(func: Callable[..., Any]) -> FunctionAnalysisResult:
    """
    Inspects a function and extracts its signature and schemas.
    """
    try:
        signature = inspect.signature(func)

        # 1. Get the callable signature
        callable_signature = f"{func.__name__}{signature}"

        # 2. Build the input schema
        input_schema = json.dumps(
            {
                name: str(param.annotation)
                for name, param in signature.parameters.items()
                if param.annotation is not inspect.Parameter.empty
            }
        )

        # 3. Get the output schema
        output_schema = str(signature.return_annotation)
        if output_schema == "<class 'inspect._empty'>":
            output_schema = None  # Handle functions without a return hint

        return FunctionAnalysisResult(
            name=func.__name__,
            callable_signature=callable_signature,
            input_schema=input_schema,
            output_schema=output_schema,
        )

    except (TypeError, ValueError) as e:
        print(f"Could not analyze function {func.__name__}: {e}")
        return {}


class NodeSpecSpanAttributes(Enum):
    """The attribute names for the NodeSpec that will be emitted in telemetry."""

    ID: str = "codon.nodespec.id"
    Name: str = "codon.nodespec.name"
    Role: str = "codon.nodespec.role"
    Version: str = "codon.nodespec.version"
    CallableSignature: str = "codon.nodespec.callable_signature"
    InputSchema: str = "codon.nodespec.input_schema"
    OutputSchema: str = "codon.nodespec.output_schema"
    ModelVersion: str = "codon.nodespec.model_version"
    ModelName: str = "codon.nodespec.model_name"
