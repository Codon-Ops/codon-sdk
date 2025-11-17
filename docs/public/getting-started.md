# Getting Started

## Prerequisites
- Python 3.8 or newer
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

You can set these environment variables directly:

```bash
export ORG_NAMESPACE=your-org-name
export OTEL_SERVICE_NAME=your-service-name  # optional
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317  # optional
```

Or create a `.env` file in your project root:

```bash
# Required
ORG_NAMESPACE=your-org-name

# Optional - only needed if using telemetry
OTEL_SERVICE_NAME=your-service-name
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

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