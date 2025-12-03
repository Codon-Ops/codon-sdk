### Phase 1: The "Front Door" (API Gateway)

**Objective:** Secure the ingestion pipeline immediately with minimal complexity.
**Timeline:** Immediate / MVP.

#### 1\. SDK Changes (Core Refactoring)

  * **Move Logic:** Move `initialize_telemetry` from `codon.instrumentation.langgraph` to `codon_sdk.instrumentation`.
  * **Update Signature:** Accept `api_key` and `endpoint` arguments.
  * **Hardcode Default:** Set the default endpoint to your production load balancer (e.g., `https://ingest.codonops.ai:4317`).
  * **Header Injection:** Inject `x-codon-api-key` into the exporter.

**Action:** Create `sdk/src/codon_sdk/instrumentation/config.py` (or similar) and migrate the logic there. Update the LangGraph package to import it.

#### 2\. Infrastructure Changes (Server-Side)

  * **DNS:** Point `ingest.codonops.ai` to your Cloud Load Balancer.
  * **Gateway:** Deploy Nginx (or Kong) behind the LB.
      * **Config:** specific rule to check `x-codon-api-key` against your DB/Cache.
      * **Success:** If valid, inject header `X-Codon-Org-ID: <org_id>` and forward to Collector.
      * **Failure:** Return `401 Unauthorized`.
  * **OTel Collector:**
      * Enable `include_metadata: true` on OTLP receivers.
      * Add `attributes/insert_tenancy` processor to extract `metadata.x-codon-org-id`.

-----

### Phase 2: The "Infinite Scale" (JWT)

**Objective:** Decouple ingestion authorization from the database to handle high-volume telemetry.
**Timeline:** Post-Launch / Scale-up.

#### 1\. SDK Changes

  * **Token Manager:** Implement a `TokenManager` class in the Core SDK.
      * **Exchange:** On init, call `https://api.codon.ai/auth/token` with the API Key to get a JWT.
      * **Refresh:** Automatically refresh the JWT 5 minutes before expiry.
  * **Exporter Update:** Update `initialize_telemetry` to use the dynamic JWT in the `Authorization: Bearer <token>` header instead of the static API key.

#### 2\. Infrastructure Changes

  * **Auth Service:** Ensure your backend has an endpoint to mint signed JWTs (RS256) containing the `org_id` claim.
  * **Collector/Gateway:** Reconfigure to use the **OIDC Authenticator**.
      * It will now validate the **signature** of the JWT locally (CPU operation) instead of calling the DB (I/O operation).
      * The `attributes` processor will now extract tenancy from `auth.claims.org_id`.

-----

### Architecture Decision Records (ADRs)

Here are the formal records you should commit to your documentation (e.g., `docs/adr/`).

#### ADR 001: Telemetry Authentication Strategy

**Status:** Accepted
**Date:** 2025-11-24

**Context:**
We need to secure the OpenTelemetry ingestion endpoint (`ingest.codonops.ai`) to prevent unauthorized data submission and ensure accurate billing/tenancy. We have two options: checking API keys against a database (Gateway pattern) or using signed tokens (JWT pattern).

**Decision:**
We will implement a **Two-Phase Strategy**:

1.  **Phase 1 (API Gateway):** Validate API Keys at the ingress gateway (Nginx) via a database/cache lookup.
2.  **Phase 2 (JWT):** Migrate to client-side JWT exchange for stateless authentication at scale.

**Consequences:**

  * **Positive:** Phase 1 allows for rapid implementation using existing API keys without complex SDK logic. Phase 2 provides a clear path to handling massive concurrency without database bottlenecks.
  * **Negative:** Phase 1 introduces a database dependency on the hot path of telemetry ingestion. If the DB slows down, telemetry ingestion slows down. This is acceptable for MVP volumes but must be replaced (Phase 2) before high-scale adoption.

#### ADR 002: Centralization of Telemetry Configuration

**Status:** Accepted
**Date:** 2025-11-24

**Context:**
Currently, `initialize_telemetry` is defined inside the `codon-instrumentation-langgraph` package. As we add support for OpenAI, CrewAI, and other frameworks, duplicating this initialization logic will lead to drift in configuration defaults (endpoints, auth headers, resource attributes).

**Decision:**
We will move the telemetry initialization logic to the **SDK Core** (`codon_sdk`).

  * **New Location:** `codon_sdk.instrumentation.initialize` (or similar).
  * **Instrumentation Packages:** Will import and wrap this core function or instruct users to call it directly.

**Consequences:**

  * **Positive:** Single source of truth for endpoints and authentication. Updates to the ingestion architecture (e.g., changing the endpoint URL or auth header format) only need to happen in one place (`codon_sdk`).
  * **Negative:** Instrumentation packages take a hard dependency on the specific version of `codon_sdk` that contains this utility.

-----

### Recommended Code Structure for Core SDK

Here is how you should implement the **Core SDK** change right now to support Phase 1.

**File:** `sdk/src/codon_sdk/instrumentation/__init__.py` (or a new `config.py` inside it)

```python
import os
from typing import Optional, Dict
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Hardcoded Production Endpoint - The "Front Door"
DEFAULT_INGEST_ENDPOINT = "https://ingest.codonops.ai:4317"

def initialize_telemetry(
    api_key: Optional[str] = None,
    service_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> None:
    """
    Global initialization for Codon telemetry.

    This should be called once at the start of the application. It configures
    OpenTelemetry to send traces to the Codon Cloud (or a custom collector).
    """

    # 1. Resolve Identity
    final_api_key = api_key or os.getenv("CODON_API_KEY")
    if not final_api_key:
        # Fallback for local dev without auth (optional, or raise Error)
        # For Phase 1 production, we might want to enforce this.
        pass

    # 2. Resolve Context
    # We prefer the user-provided service name, then env var, then default.
    final_service_name = (
        service_name
        or os.getenv("OTEL_SERVICE_NAME")
        or "unknown_codon_service"
    )

    # 3. Resolve Destination
    # Default to Prod, allow env var override, allow explicit arg override.
    final_endpoint = (
        endpoint
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or DEFAULT_INGEST_ENDPOINT
    )

    # 4. Configure Headers
    headers: Dict[str, str] = {}
    if final_api_key:
        headers["x-codon-api-key"] = final_api_key

    # 5. Setup OpenTelemetry
    resource = Resource(attributes={"service.name": final_service_name})

    exporter = OTLPSpanExporter(
        endpoint=final_endpoint,
        headers=headers
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    # Set the global tracer provider so all instrumentation packages pick it up
    trace.set_tracer_provider(provider)
```

**Usage in `codon-instrumentation-langgraph`:**
You would delete the local `initialize_telemetry` definition and re-export or document the usage of the core one.

```python
# instrumentation-packages/codon-instrumentation-langgraph/codon/instrumentation/langgraph/__init__.py

# Re-export for convenience, or deprecate and point users to core
from codon_sdk.instrumentation import initialize_telemetry
```
