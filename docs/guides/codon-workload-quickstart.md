# CodonWorkload Quickstart

This guide walks through building and executing a workload with the SDK’s token-based, auditable runtime. Each node processes tokens, can emit new tokens to downstream nodes, and the SDK captures an execution ledger suitable for compliance and replay.

## 1. Define Node Functions
Node functions receive the incoming token `message`, a `runtime` helper, and the shared execution `context`.

```python
from codon_sdk.agents import CodonWorkload


def ingest(message, *, runtime, context):
    lines = message["document"].splitlines()
    runtime.emit("summarize", {"lines": lines})
    return {"lines": len(lines)}


def summarize(message, *, runtime, context):
    runtime.record_event("summary_started", metadata={"line_count": len(message["lines"])})
    summary = {
        "title": message["lines"][0] if message["lines"] else "",
        "line_count": len(message["lines"]),
        "deployment": context["deployment_id"],
    }
    return summary
```

The `runtime` helper provides:
- `emit(target, payload, *, audit_metadata=None)` to queue tokens for connected nodes.
- `record_event(event_type, metadata=None)` to append custom audit events.
- `state` (a mutable dict) for sharing state across node invocations.
- `stop()` to halt execution once conditions are met.

## 2. Register Nodes and Edges

```python
workload = CodonWorkload(name="ReportAgent", version="0.2.0")

workload.add_node(ingest, name="ingest", role="parser")
workload.add_node(summarize, name="summarize", role="responder")
workload.add_edge("ingest", "summarize")
```

Edges declare permissible routes for tokens. Nodes can emit to a target only if the edge exists. Self-edges are allowed for loops.

## 3. Execute the Workload

```python
report = workload.execute(
    {"document": "Status Update\nWeek 42"},
    deployment_id="dev-cluster-1",
    invoked_by="cli",
)

print(report.node_results("summarize")[-1])
# {'title': 'Status Update', 'line_count': 2, 'deployment': 'dev-cluster-1'}
```

`execute` returns an `ExecutionReport` containing:
- `node_results(name)` – ordered results for each node invocation.
- `ledger` – a chronological list of `AuditEvent` entries (enqueue/dequeue, node completion, custom events) forming an audit trail.
- `context` – the run metadata (deployment ID, logic ID, run ID, plus any extras you supplied).

## 4. Inspect the Audit Trail

```python
for event in report.ledger:
    print(event.event_type, event.source_node, event.target_node, event.metadata)
```

Events include immutable token IDs, lineage, and payload representations so you can replay or verify an invocation.

## 5. Loops and Shared State

Loops are enabled by adding self-edges and using `runtime.emit`.

```python
def loop(message, *, runtime, context):
    step = runtime.state.get("step", 0)
    runtime.state["step"] = step + 1
    if step < 2:
        runtime.emit("loop", message)
    else:
        runtime.stop()
    return step

loop_workload = CodonWorkload(name="Looper", version="0.1.0")
loop_workload.add_node(loop, name="loop", role="controller")
loop_workload.add_edge("loop", "loop")
loop_report = loop_workload.execute({}, deployment_id="qa")
# In async contexts use: loop_report = await loop_workload.execute_async(...)
print(loop_report.node_results("loop"))  # [0, 1, 2]
```

## 6. Next Steps
- Hook the workload into instrumentation mixins to emit OpenTelemetry spans alongside the audit ledger.
- Persist or stream `ExecutionReport` entries for downstream compliance tooling.
- Add tests that assert specific ledger sequences for critical workloads.

For deeper architectural context, revisit `docs/design/Workload builder spec - Codon SDK.txt` or the broader agent documentation in `sdk/AGENTS.md`.
