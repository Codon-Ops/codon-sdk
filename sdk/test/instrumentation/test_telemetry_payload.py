import json

from codon_sdk.instrumentation.telemetry import NodeTelemetryPayload


def test_node_telemetry_payload_records_tokens_and_model():
    payload = NodeTelemetryPayload()
    payload.record_tokens(
        input_tokens=5,
        output_tokens=7,
        total_tokens=12,
        token_usage={"prompt_tokens": 5, "completion_tokens": 7},
    )
    payload.set_model_info(model_name="gpt-4o", vendor="openai", identifier="gpt-4o")
    payload.add_network_call({"request_id": "abc"})
    payload.extra_attributes["foo"] = "bar"

    raw_json = payload.to_raw_attributes_json()
    assert raw_json is not None
    parsed = json.loads(raw_json)
    assert parsed["token_usage"]["prompt_tokens"] == 5
    assert parsed["network_calls"][0]["request_id"] == "abc"
    assert parsed["extra"]["foo"] == "bar"

    attributes = payload.as_span_attributes()
    assert attributes["input_tokens"] == 5
    assert attributes["model_name"] == "gpt-4o"
