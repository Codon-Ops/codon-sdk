# Building from Scratch

If you're building agents from the ground up, [CodonWorkload](api-reference.md#codon_sdkagentscodonworkload) provides a flexible foundation for creating single-agent and multi-agent workflows with token-based execution and comprehensive audit trails.

## The CodonWorkload Class

CodonWorkload is the foundation for building observable AI agents. Whether you build from scratch or use frameworks like LangGraph, it gives your agents the ability to track their own performance, costs, and behavior over time.

**Key capabilities:**
- **Node registration**: Add Python functions as workflow steps
- **Graph definition**: Connect nodes with directed edges to define execution flow
- **Token-based execution**: Messages flow between nodes with full provenance tracking
- **Audit trails**: Automatic recording of every step, decision, and data transformation
- **Runtime operations**: Nodes can emit messages, record custom events, and share state

For complete method signatures and parameters, see the [API Reference](api-reference.md).

## Key Concepts

**Nodes**: Individual Python functions that perform specific tasks (e.g., "summarize", "validate", "format"). Each node receives input, processes it, and can emit output to other nodes.

**Edges**: Directed connections between nodes that define how tokens (messages) flow through your workflow.

**Tokens**: Immutable messages that carry data between nodes, each with unique provenance tracking. This creates an immutable tape of your agent's actions during invocation that can be used for compliance monitoring, audit, evaluation, debugging, and experimentation.

**Runtime**: The execution context that provides nodes access to operations like `runtime.emit()`, `runtime.record_event()`, and `runtime.state`.

## Single-Agent Workflow

Here's a simple Q&A agent that processes a user question:

```python
from codon_sdk.agents import CodonWorkload
from datetime import datetime

# Define a workload
workload = CodonWorkload(name="QA-Agent", version="0.1.0")

# Define node functions
def call_model(message: Dict[str, Any], *, runtime, context):
    prompt = message["question"]
    answer = call_openai(prompt, system="You are a helpful assistant that answers questions you are asked.")
    runtime.record_event("call_model", metadata={"answer_length": len(answer)})
    runtime.emit("finalize", {"question": message["question"], "answer": answer})
    return answer

def prompt_builder(message: Dict[str, Any], *, runtime, context):
    question = message["question"]
    prompt = (
        "Answer the user's question in clear, friendly prose."
        f"Question: {question}"
    )
    runtime.record_event("prompt_created", metadata={"length": len(prompt)})
    runtime.emit("call_model", {"question": question})
    return prompt

def finalize(message: Dict[str, Any], *, runtime, context):
    result = {
        "question": message["question"],
        "answer": message["answer"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    runtime.record_event("finalized", metadata={"question_hash": hash(message["question"])})
    return result

# Add the nodes
workload.add_node(call_model, name="call_model", role="llm")
workload.add_node(finalize, name="finalize", role="postprocess")
workload.add_node(prompt_builder, name="prompt_builder", role="format_prompt")

# Define the edges
workload.add_edge("prompt_builder", "call_model")
workload.add_edge("call_model", "finalize")

# Execute the workload
report = workload.execute({"question": "What is the meaning of life, the universe, and everything?"}, deployment_id="local")

# Check results
final_result = report.node_results("finalize")[-1]
print(f"Logic ID: {workload.logic_id}")
```

## Multi-Agent Workflow

For more complex scenarios, you can orchestrate multiple agents that collaborate through token passing and shared state:

```python
def build_multi_agent_workload() -> CodonWorkload:
    workload = CodonWorkload(name="Research-Writer", version="0.1.0")

    def planner(message: Dict[str, Any], *, runtime, context):
        topic = message["topic"]
        prompt = (
            "Design a concise research plan outlining key angles and questions."
            f"Topic: {topic}"
            "Return a numbered list with three focus areas."
        )
        plan = call_openai(prompt, system="You are a strategic project planner.")
        runtime.state["plan"] = plan
        runtime.emit("researcher", {"topic": topic, "plan": plan})
        return plan

    def researcher(message: Dict[str, Any], *, runtime, context):
        prompt = (
            "Given this plan, provide bullet insights (max 3 per focus area)."
            f"Plan: {message['plan']}"
        )
        insights = call_openai(prompt, system="You are an expert analyst.")
        runtime.state["insights"] = insights
        runtime.emit(
            "writer",
            {
                "topic": message["topic"],
                "plan": message["plan"],
                "insights": insights,
            },
        )
        return insights

    def writer(message: Dict[str, Any], *, runtime, context):
        prompt = (
            "Write a concise executive summary (<=120 words) in a warm, professional tone."
            f"Topic: {message['topic']}"
            f"Plan: {message['plan']}"
            f"Insights: {message['insights']}"
        )
        summary = call_openai(prompt, system="You are a skilled report writer.")
        runtime.record_event("summary_created", metadata={"length": len(summary)})
        return {
            "topic": message["topic"],
            "plan": message["plan"],
            "insights": message["insights"],
            "summary": summary,
        }

    workload.add_node(planner, name="planner", role="planner")
    workload.add_node(researcher, name="researcher", role="analyst")
    workload.add_node(writer, name="writer", role="author")
    workload.add_edge("planner", "researcher")
    workload.add_edge("researcher", "writer")

    return workload

# Use the multi-agent workload
multi_agent = build_multi_agent_workload()
project = {"topic": "The impact of community gardens on urban wellbeing"}
multi_report = multi_agent.execute(project, deployment_id="demo", max_steps=20)
final_document = multi_report.node_results("writer")[-1]
```

## Key Concepts

### Token-Based Execution
- Each node receives a token `message` with data from previous nodes
- Nodes can emit new tokens to downstream nodes via `runtime.emit(target_node, payload)`
- Tokens carry immutable provenance with unique IDs, lineage, and timestamps

### Runtime Operations
The `runtime` parameter provides access to workflow operations:
- `runtime.emit(node_name, payload)` - Send tokens to other nodes
- `runtime.record_event(event_type, metadata={})` - Add custom audit entries
- `runtime.state` - Shared dictionary for coordination between nodes
- `runtime.stop()` - Halt execution early

### Audit Ledger
Every workflow execution generates a comprehensive audit trail:
- Token enqueue/dequeue events
- Node completion events  
- Custom events via `runtime.record_event()`
- Execution context (deployment_id, logic_id, run_id)

**Note:** Only fired nodes are represented in a workload run, so the complete workload definition may not be present in the workload run summary. Your audit trail shows actual execution paths, not all possible paths defined in your workflow.

Access the audit ledger through the execution report:
```python
for event in report.ledger:
    print(f"{event.timestamp.isoformat()} | {event.event_type} | {event.source_node}")
```

### Logic IDs
Each workload gets a deterministic Logic ID based on:
- Agent class metadata (name, version, description)
- Node definitions and their roles
- Graph topology (edges between nodes)

Same workload structure = same Logic ID, enabling deduplication and version tracking.

**Example: Logic ID Generation and Changes**
```python
# Based on test_codon_workload.py test patterns
workload = CodonWorkload(name="TestWorkload", version="0.1.0")

def simple_node(message, *, runtime, context):
    return f"Result: {message['input']}"

workload.add_node(simple_node, name="test_node", role="processor")

print(f"Initial Logic ID: {workload.logic_id}")
baseline_logic_id = workload.logic_id

# Adding a node changes the Logic ID
def echo_node(message, *, runtime, context):
    return message

workload.add_node(echo_node, name="echo", role="responder")
workload.add_edge("test_node", "echo")

print(f"After adding node: {workload.logic_id}")
print(f"Logic ID changed? {workload.logic_id != baseline_logic_id}")  # True
```

This deterministic identification enables:
- **Deduplication**: Skip redundant executions of the same logic
- **Version tracking**: Compare agent iterations across deployments  
- **Caching**: Store and retrieve results based on stable identifiers