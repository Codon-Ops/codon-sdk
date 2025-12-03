# Codon SDK Monorepo

Codon SDK provides common building blocks for Codon agents, including immutable node specifications, logic ID generation, and a shared telemetry vocabulary. This repository also houses framework-specific instrumentation packages that emit OpenTelemetry spans enriched with Codon metadata.

## Key Features
- Immutable `NodeSpec` records that introspect Python callables and generate stable SHA-256 identifiers tied to organization, role, and model metadata.
- Canonical logic request hashing that deduplicates workloads by agent class, participating nodes, and topology.
- OpenTelemetry span attribute catalog for agent runs, tools, LLMs, and vector database interactions.
- Pluggable instrumentation packages (e.g., LangGraph) that decorate nodes, capture latency, and forward spans to OTLP endpoints.

## Repository Layout
```
README.md
sdk/
  pyproject.toml        # Core codon_sdk packaging metadata
  src/codon_sdk/        # SDK source (schemas, instrumentation helpers)
  test/                 # Test scaffold
instrumentation-packages/
  codon-instrumentation-langgraph/
    codon/instrumentation/langgraph/   # LangGraph decorators & attributes
    pyproject.toml                     # Package metadata
  codon-instrumentation-openai/        # Placeholder for OpenAI instrumentation
```

## Prerequisites
- Python 3.9 or newer
- `pip` and a virtual environment tool such as `venv` or `pipenv`
- Access to an OTLP-compatible collector if you plan to export telemetry

## Installation
Clone the repository and install the core SDK in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e sdk
```

Instrumentation packages are published independently. To work on one locally, install it the same way:

```bash
pip install -e instrumentation-packages/codon-instrumentation-langgraph
```

> **Note:** The OpenAI package is currently a stub and will be populated in a future iteration.

## Environment Configuration
| Variable | Purpose |
| -------- | ------- |
| `ORG_NAMESPACE` | Required by `NodeSpec` and instrumentation to scope identifiers. |
| `OTEL_SERVICE_NAME` | Optional service name applied during telemetry initialization. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Configure the OTLP collector when using the default exporter. |

Set `ORG_NAMESPACE` before constructing `NodeSpec` objects or instrumented decorators will raise a validation error.

## Working with NodeSpec
`NodeSpec` inspects Python callables to capture the function signature, type hints, and optional model metadata. It emits a deterministic SHA-256 ID that downstream systems can rely on.

```python
from codon_sdk.instrumentation.schemas.nodespec import NodeSpec

@track_node("summarize", role="processor")
def summarize(text: str) -> str:
    ...

# Alternatively, construct the NodeSpec directly
nodespec = NodeSpec(
    org_namespace="acme",
    name="summarize",
    role="processor",
    callable=summarize,
    model_name="gpt-4o",
    model_version="2024-05-13",
)
print(nodespec.id)
```

`NodeSpec` requires type annotations to build JSON schemas for inputs and outputs. If annotations are missing, the generated schemas may be empty.

## Generating Logic IDs
Logic IDs canonicalize workload definitions so repeated submissions map to the same identifier.

```python
from codon_sdk.instrumentation.schemas.logic_id import (
    AgentClass,
    LogicRequest,
    generate_logic_id,
)

logic_request = LogicRequest(
    agent_class=AgentClass(
        name="ReportAgent",
        version="0.1.0",
        description="Generates weekly status reports",
    ),
    nodes=[nodespec],
)
logic_id = generate_logic_id(logic_request)
print(logic_id)  # Stable SHA-256 hash
```

The hash is deterministic because nodes and topology edges are sorted prior to serialization. This enables safe retries and caching.

## Instrumentation & Telemetry
Start by configuring OTEL and decorating nodes:

```python
from codon.instrumentation.langgraph import initialize_telemetry, track_node

initialize_telemetry(service_name="codon-langgraph-demo")

@track_node("retrieve_docs", role="retriever")
def retrieve_docs(query: str) -> list[str]:
    ...
```

When the decorated function executes, the LangGraph package:
- materializes a `NodeSpec` and captures its ID, signature, and schemas
- wraps execution in an OpenTelemetry span (async and sync supported)
- records inputs, outputs, and wall-clock latency via standardized span attributes

Spans are exported with `org.namespace`, `agent.framework.name`, and the Codon span names defined in `codon_sdk.instrumentation.schemas.telemetry.spans`.

## Development Workflow
- Run formatting/linting aligned with your team preferences (no toolchain is enforced yet).
- Execute tests with `pytest` once suites are populated:
  ```bash
  pytest sdk/test
  ```
- Use `pip install -e <package>` for editable installs while iterating.

## Roadmap & Known Gaps
- `codon-instrumentation-openai` awaits implementation.
- Minimal test coverage is checked in; broaden it as modules stabilize.
- README content inside `codon_sdk` will be expanded with module-level documentation.

## License
Package metadata references the MIT License. Add the license file before publishing to PyPI.
