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
| `CODON_API_KEY` | Required to export telemetry data to the Codon observability platform. |
| `OTEL_SERVICE_NAME` | Optional service name applied during telemetry initialization. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Configure the OTLP collector when using the default exporter. |

Set `ORG_NAMESPACE` before constructing `NodeSpec` objects or instrumented decorators will raise a validation error.

You can set these environment variables directly:

```bash
export ORG_NAMESPACE=your-org-name
export OTEL_SERVICE_NAME=your-service-name  # optional
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317  # optional
export CODON_API_KEY=your-api-key-from-dashboard  # required for telemetry on Codon platform
```

Or create a `.env` file in your project root:

```bash
# Required
ORG_NAMESPACE=your-org-name

# Optional - only needed if using telemetry
OTEL_SERVICE_NAME=your-service-name
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Required for captured telemetry visible on Codon platform
CODON_API_KEY=your-api-key-from-dashboard
```

## Platform Setup

To access the Codon observability platform and export telemetry data, you'll need to create an account and obtain an API key.

### Step 1: Access the Login Screen

Navigate to the Codon platform and click 'Sign in with Github':

![Login Screen](images/auth/step1-login-screen.png)

### Step 2: Authorize with GitHub

You'll be redirected to GitHub to authorize the Codon application:

![GitHub SSO](images/auth/step2-github-sso.png)

### Step 3: Access Your Dashboard

After authorization, you'll be redirected to your organization dashboard:

![Admin Panel](images/auth/step3-admin-panel.png)

Your dashboard will display your organization ID, name, email, and API key.

### Step 4: Configure Your Organization

Add or update your organization name and save your settings:

![Organization Settings](images/auth/step4-org-settings.png)

**Important:** Copy your API key and set it as the `CODON_API_KEY` environment variable to authenticate telemetry exports to the Codon platform.

## Initializing Telemetry

Once you have your API key configured, initialize telemetry to start sending observability data to the Codon platform:

```python
from codon_sdk.instrumentation import initialize_telemetry

# Initialize telemetry - uses CODON_API_KEY automatically
initialize_telemetry()
```

Call `initialize_telemetry()` once at the start of your application, before creating workloads or executing agents. This function:

- Configures OpenTelemetry to export spans to the Codon platform
- Automatically uses your `CODON_API_KEY` environment variable for authentication
- Sets up the service name from `OTEL_SERVICE_NAME` (optional)
- Works for both [from-scratch workloads](building-from-scratch.md) and [framework integrations](instrumentation/langgraph.md)

**Example with service name:**
```python
initialize_telemetry(service_name="my-ai-agent")
```

## Next Steps

Now that you have the SDK installed and configured, you can:

- **Build from scratch**: Create custom agents with [CodonWorkload](building-from-scratch.md)
- **Use existing frameworks**: Integrate with [LangGraph](instrumentation/langgraph.md) or other supported frameworks
- **Learn the APIs**: Explore detailed documentation in the [API Reference](api-reference.md)

For detailed information about NodeSpec and Logic ID generation, see the [API Reference](api-reference.md).