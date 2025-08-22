from .version import __version__
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Callable, Any, Dict, Literal, get_type_hints
import hashlib
import inspect
import json
    
class NodeSpec(BaseModel):
    name: str = Field(description="The name of the node.")
    role: str = Field(description="The role of the node.")
    callable_signature: str = Field(description="The callable signature of the node.")
    input_schema: Optional[str] = Field(default=None, description="The input schema of the node.")
    output_schema: Optional[str] = Field(default=None, description="The output schema of the node.")
    model_name: Optional[str] = Field(default=None, description="The name of the model used in the node.")
    model_version: Optional[str] = Field(default=None, description="The version of the model currently used.")
    spec_version: str = Field(default=__version__, description="The current version of the NodeSpec specification.")

    @field_validator("spec_version", mode="before")
    @classmethod
    def _enforce_current_spec_version(cls, v: Any) -> str:
        """This validator ensures that the spec_version used is the official one and won't be overridden."""
        return __version__
    
    def generate_nodespec_id(self, namespace: str) -> str:
        """
        Generates a unique identifier for the node specification.
        """
        py_dict = self.model_dump(mode="json", exclude_none=True)
        canonical_spec = json.dumps(py_dict, sort_keys=True, separators=(',', ':'))
        to_hash = f"{namespace} {canonical_spec.strip()}".strip()
        nodespec_id = nodespec_hash_method(hashable_string=to_hash)
        
        return nodespec_id
    

def nodespec_hash_method(hashable_string: str) -> str:
    """The method used to create the hash for the nodespec_id"""
    hasher = hashlib.sha256()
    hasher.update(hashable_string.encode("utf-8"))
    return hasher.hexdigest()

class FunctionAnalysisResult(BaseModel):
    name: str = Field(description="The name of the function.")
    callable_signature: str = Field(description="The callable signature of the function.")
    input_schema: str = Field(description="The input schema of the function.")
    output_schema: Optional[str] = Field(default=None, description="The output schema of the function.")
    
def analyze_function(func: Callable[..., Any]) -> FunctionAnalysisResult:
    """
    Inspects a function and extracts its signature and schemas.
    """
    try:
        signature = inspect.signature(func)
        type_hints = get_type_hints(func)

        # 1. Get the callable signature
        callable_signature = f"{func.__name__}{signature}"

        # 2. Build the input schema
        input_schema = json.dumps({
            name: str(param.annotation)
            for name, param in signature.parameters.items()
            if param.annotation is not inspect.Parameter.empty
        })

        # 3. Get the output schema
        output_schema = str(signature.return_annotation)
        if output_schema == "<class 'inspect._empty'>":
            output_schema = None # Handle functions without a return hint

        return FunctionAnalysisResult(
            name = func.__name__,
            callable_signature = callable_signature,
            input_schema = input_schema,
            output_schema = output_schema
        )

    except (TypeError, ValueError) as e:
        print(f"Could not analyze function {func.__name__}: {e}")
        return {}
    

def generate_nodespec(
        node_name: str, 
        role: str, 
        callable: Callable[..., Any], 
        model_name: Optional[str] = None,
        model_version: Optional[str] = None) -> NodeSpec:
    # Analyze the function
    func_metadata = analyze_function(func=callable)
    # Create the nodespec
    nodespec = NodeSpec(
        name = node_name,
        role = role,
        callable_signature = func_metadata.callable_signature,
        input_schema = func_metadata.input_schema,
        output_schema = func_metadata.output_schema,
        model_name = model_name,
        model_version = model_version
    )
    return nodespec

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

    