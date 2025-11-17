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

## Next Steps

Now that you have the SDK installed and configured, you can:

- **Build from scratch**: Create custom agents with [CodonWorkload](building-from-scratch.md)
- **Use existing frameworks**: Integrate with [LangGraph](instrumentation/langgraph.md) or other supported frameworks
- **Learn the APIs**: Explore detailed documentation in the [API Reference](api-reference.md)

For detailed information about NodeSpec and Logic ID generation, see the [API Reference](api-reference.md).