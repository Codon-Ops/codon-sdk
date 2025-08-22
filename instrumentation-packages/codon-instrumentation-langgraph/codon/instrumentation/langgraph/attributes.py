from enum import Enum

class LangGraphSpanAttributes(Enum):
    Inputs: str = "codon.instrumentation.langgraph.node.inputs"
    Outputs: str = "codon.instrumentation.langgraph.node.outputs"
    NodeLatency: str = "codon.instrumentation.langgraph.node.latency.seconds"