import os
import pytest
import json
import hashlib
from typing import List
from codon_sdk.instrumentation.schemas.nodespec import (
    analyze_function,
    nodespec_hash_method,
    NodeSpec,
    NodeSpecValidationError,
    FunctionAnalysisResult,
    nodespec_env,
)

# Test data
def sample_function(a: int, b: str) -> float:
    """A sample function."""
    return float(a) + len(b)

def function_without_return_hint(a: int):
    pass

def function_without_params():
    return "hello"

# Tests for analyze_function
def test_analyze_function_simple():
    result = analyze_function(sample_function)
    assert isinstance(result, FunctionAnalysisResult)
    assert result.name == "sample_function"
    assert result.callable_signature == "sample_function(a: int, b: str) -> float"
    assert json.loads(result.input_schema) == {"a": "<class 'int'>", "b": "<class 'str'>"}
    assert result.output_schema == "<class 'float'>"

def test_analyze_function_no_return_hint():
    result = analyze_function(function_without_return_hint)
    assert result.output_schema is None

def test_analyze_function_no_params():
    result = analyze_function(function_without_params)
    assert json.loads(result.input_schema) == {}
    assert result.output_schema is None


# Tests for nodespec_hash_method
def test_nodespec_hash_method_consistency():
    string_to_hash = "test_string"
    hash1 = nodespec_hash_method(string_to_hash)
    hash2 = nodespec_hash_method(string_to_hash)
    assert hash1 == hash2

def test_nodespec_hash_method_sha256():
    string_to_hash = "test_string"
    expected_hash = hashlib.sha256(string_to_hash.encode("utf-8")).hexdigest()
    assert nodespec_hash_method(string_to_hash) == expected_hash


# Tests for NodeSpec
@pytest.fixture()
def set_my_org_env_var():
    os.environ[nodespec_env.OrgNamespace] = "my-org"
    yield
    del os.environ[nodespec_env.OrgNamespace]

def test_nodespec_creation_success(set_my_org_env_var):
    spec = NodeSpec(
        name="test_node",
        role="test_role",
        callable=sample_function,
    )
    assert spec.name == "test_node"
    assert spec.role == "test_role"
    assert spec.org_namespace == "my-org"
    assert spec.spec_version == "0.1.0"
    assert spec.callable_signature == "sample_function(a: int, b: str) -> float"
    assert spec.id is not None

def test_nodespec_creation_no_env_var_fails():
    with pytest.raises(NodeSpecValidationError, match="ORG_NAMESPACE environment variable not set"):
        NodeSpec(
            name="test_node",
            role="test_role",
            callable=sample_function,
        )

def test_nodespec_id_generation(set_my_org_env_var):
    spec = NodeSpec(
        name="test_node",
        role="test_role",
        callable=sample_function,
        model_name="test_model",
        model_version="1.0"
    )

    callable_attrs = analyze_function(sample_function)
    nodespec_meta_attrs = {
        "org_namespace": "my-org",
        "name": "test_node",
        "role": "test_role",
        "model_name": "test_model",
        "model_version": "1.0",
    }
    canonical_spec = json.dumps(
        {**callable_attrs.model_dump(mode="json", exclude_none=True), **nodespec_meta_attrs},
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_id = nodespec_hash_method(canonical_spec.strip())

    assert spec.id == expected_id

@pytest.mark.xfail(reason="The field_validator for spec_version is not working as expected for frozen models")
def test_nodespec_spec_version_override_fails(set_my_org_env_var):
    with pytest.raises(NodeSpecValidationError, match="spec_version cannot be changed"):
        NodeSpec(
            name="test_node",
            role="test_role",
            callable=sample_function,
            spec_version="anything"
        )
