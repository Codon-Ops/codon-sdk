# Instrumentation

Framework-specific instrumentation packages that emit OpenTelemetry spans enriched with Codon metadata.

## Available Integrations

### **[LangGraph Integration](langgraph.md)**
Seamlessly integrate your existing LangGraph StateGraphs with Codon telemetry and observability.

- Automatic node instrumentation via `LangGraphWorkloadAdapter`
- Manual function decoration with `@track_node`
- OpenTelemetry span export with Codon metadata

## Coming Soon

- **OpenAI Integration** - Direct instrumentation for OpenAI API calls
- **CrewAI Integration** - Support for CrewAI agent frameworks

## Installation

Instrumentation packages are installed separately from the core SDK:

```bash
# Install core SDK
pip install -e sdk

# Install specific instrumentation packages as needed
pip install -e instrumentation-packages/codon-instrumentation-langgraph
```

Each integration provides telemetry and observability for its respective framework while working alongside the core Codon SDK.