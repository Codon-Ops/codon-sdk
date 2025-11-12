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

"""Logic for creating a Logic ID based on the agent's logic and classification"""
import hashlib
import json
from typing import List

from pydantic import BaseModel, Field

from ..nodespec import NodeSpec

class AgentClass(BaseModel):
  name: str = Field(description="The name of the agent class")
  version: str = Field(description="The version number of the agent class")
  description: str = Field(description="The description of the agent class")

class NodeEdge(BaseModel):
  source_nodespec_id: str = Field(description="The nodespec_id of the source node")
  target_nodespec_id: str = Field(description="The nodespec_id of the target node")

class Topology(BaseModel):
  edges: List[NodeEdge] = Field(default_factory=list, description="A list of edges between nodes describing a workload")

class LogicRequest(BaseModel):
  agent_class: AgentClass = Field("The Agentic Class of the Logic Workload")
  nodes: List[NodeSpec]
  topology: Topology = Field(default_factory=Topology, description="A list of edges between nodes describing a workload")

def canonicalize_logic_request(logic_request: LogicRequest) -> str:
  """
  Transforms a LogicRequest into a canonicalized JSON string.

  Args:
    logic_request: The LogicRequest object to canonicalize.

  Returns:
    A canonicalized JSON string representation of the LogicRequest.
  """
  # Convert the LogicRequest object to a dictionary
  request_dict = logic_request.model_dump()

  # Sort the nodes and edges lists to ensure consistent ordering
  request_dict['nodes'] = sorted(request_dict['nodes'], key=lambda x: x['id'])
  if request_dict['topology']['edges']:
    request_dict['topology']['edges'] = sorted(request_dict['topology']['edges'], key=lambda x: (x['source_nodespec_id'], x['target_nodespec_id']))

  # Convert the dictionary to a JSON string with consistent formatting
  canonicalized_json = json.dumps(request_dict, sort_keys=True, indent=None, separators=(',', ':'))

  return canonicalized_json

def generate_idempotent_id(canonicalized_request: str) -> str:
  """
  Generates an idempotent ID from a canonicalized request string.

  Args:
    canonicalized_request: The canonicalized string representation of the request.

  Returns:
    An idempotent ID (SHA-256 hash) of the canonicalized request.
  """
  # Use SHA-256 hash for idempotency
  return hashlib.sha256(canonicalized_request.encode('utf-8')).hexdigest()


def generate_logic_id(logic_request: LogicRequest) -> str:
  """Generates the idempotent Logic ID"""
  canonicalized_form = canonicalize_logic_request(logic_request)
  logic_id = generate_idempotent_id(canonicalized_form)

  return logic_id
