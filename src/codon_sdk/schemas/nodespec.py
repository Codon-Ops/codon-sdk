from pydantic import BaseModel, Field
from typing import Optional, Callable, Any, Dict, get_type_hints
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
    model_version: Optional[str] = Field(default=None, description="The version of the model currently used")

    def generate_nodespec_id(self) -> str:
        """
        Generates a unique identifier for the node specification.
        """
        hasher = hashlib.sha256()
        required_fields = " ".join([
            getattr(self, field_name) for field_name, field_info in
            NodeSpec.model_fields.items()
            if field_info.is_required()
        ])
        optional_fields = " ".join([
            getattr(self, field_name) for field_name, field_info in 
            NodeSpec.model_fields.items()
            if not field_info.is_required() 
              and field_name not in self.model_fields_set
              and getattr(self, field_name) is not None
        ])
        to_hash = " ".join([required_fields, optional_fields]).strip()
        hasher.update(to_hash.encode("utf-8"))
        
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
        name: str, 
        role: str, 
        callable: Callable[..., Any], 
        model_name: Optional[str] = None,
        model_version: Optional[str] = None) -> NodeSpec:
    # Analyze the function
    func_metadata = analyze_function(func=callable)
    # Create the nodespec
    nodespec = NodeSpec(
        name = name,
        role = role,
        callable_signature = func_metadata.callable_signature,
        input_schema = func_metadata.input_schema,
        output_schema = func_metadata.output_schema,
        model_name = model_name,
        model_version = model_version
    )
    return nodespec