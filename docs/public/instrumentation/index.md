# Instrumentation

Framework-specific instrumentation packages that emit OpenTelemetry spans enriched with Codon metadata.

## Available Integrations

### **[LangGraph Integration](langgraph.md)**
Seamlessly integrate your existing LangGraph StateGraphs with Codon telemetry and observability.

- Automatic node instrumentation via `LangGraphWorkloadAdapter`
- OpenTelemetry span export with Codon metadata
- Just a few lines of code integration

## Coming Soon

- **OpenAI Integration** - Direct instrumentation for OpenAI API calls
- **CrewAI Integration** - Support for CrewAI agent frameworks

## Installation

Instrumentation packages are installed separately from the core SDK:

```bash
# Install core SDK
pip install codon-sdk

# Install specific instrumentation packages as needed
pip install codon-instrumentation-langgraph
```

Each integration provides telemetry and observability for its respective framework while working alongside the core Codon SDK.

**Universal Interface:** All instrumentation packages convert framework-specific workflows into standard CodonWorkloads. This means you get the same `execute()`, `execute_async()`, `node_results()`, and other methods regardless of whether you built from scratch or wrapped an existing framework. See [Execution and Results](../building-from-scratch.md#execution-and-results) for the complete interface.