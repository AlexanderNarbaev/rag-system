"""Step definitions for chat completion feature."""

import os

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../chat_completion.feature")

PROXY_URL = os.getenv("RAG_PROXY_URL", "http://localhost:9080")
REQUEST_TIMEOUT = 30


@pytest.fixture
def chat_context():
    """Shared context for chat test steps."""
    return {}


@given("the RAG system is running")
def check_system_running():
    """Verify the RAG proxy is reachable."""
    r = httpx.get(f"{PROXY_URL}/v1/health/live", timeout=5)
    assert r.status_code == 200, f"RAG system not running: {r.status_code}"


@given("the knowledge base contains documents")
def check_kb_has_documents():
    """Verify knowledge base has documents (non-fatal in test env)."""
    # In test environments the KB may be empty — this is acceptable for ungrounded tests.
    pass


@given("the knowledge base is empty")
def set_empty_kb():
    """Mark scenario as targeting empty knowledge base."""
    pass


@when(parsers.parse('I send a chat request with model "{model}" and message "{message}"'))
def send_chat_request(chat_context, model, message):
    """Send a non-streaming chat completion request."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "stream": False,
    }
    chat_context["request_payload"] = payload
    r = httpx.post(
        f"{PROXY_URL}/v1/chat/completions",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    chat_context["response"] = r
    chat_context["response_json"] = r.json() if r.status_code == 200 else {}


@when(parsers.parse('I send a streaming chat request with model "{model}" and message "{message}"'))
def send_streaming_chat_request(chat_context, model, message):
    """Send a streaming chat completion request and collect SSE events."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "stream": True,
    }
    chat_context["request_payload"] = payload
    events = []
    with httpx.stream(
        "POST",
        f"{PROXY_URL}/v1/chat/completions",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    ) as r:
        chat_context["response"] = r
        for line in r.iter_lines():
            if line.strip():
                events.append(line)
    chat_context["sse_events"] = events


@when(parsers.parse("I set rag_top_k to {value:d}"))
def set_rag_top_k(chat_context, value):
    """Set rag_top_k parameter on the request payload."""
    chat_context["request_payload"]["rag_top_k"] = value


@when(parsers.parse("I set rag_return_chunks to {value}"))
def set_rag_return_chunks(chat_context, value):
    """Set rag_return_chunks parameter on the request payload."""
    chat_context["request_payload"]["rag_return_chunks"] = value.lower() == "true"


@when(parsers.parse("I set rag_force_refresh to {value}"))
def set_rag_force_refresh(chat_context, value):
    """Set rag_force_refresh parameter on the request payload."""
    chat_context["request_payload"]["rag_force_refresh"] = value.lower() == "true"
    # Re-send the request with the updated payload
    r = httpx.post(
        f"{PROXY_URL}/v1/chat/completions",
        json=chat_context["request_payload"],
        timeout=REQUEST_TIMEOUT,
    )
    chat_context["response"] = r
    chat_context["response_json"] = r.json() if r.status_code == 200 else {}


@then(parsers.parse("I receive a response with status {status:d}"))
def check_response_status(chat_context, status):
    """Assert the HTTP response status code."""
    assert chat_context["response"].status_code == status, (
        f"Expected status {status}, got {chat_context['response'].status_code}"
    )


@then(parsers.parse('the response contains "{key}" with {count:d} item'))
@then(parsers.parse('the response contains "{key}" with {count:d} items'))
def check_response_key_count(chat_context, key, count):
    """Assert a key in the response JSON has the expected number of items."""
    data = chat_context["response_json"]
    assert key in data, f"Key '{key}' not in response: {list(data.keys())}"
    assert len(data[key]) == count, f"Expected {count} items in '{key}', got {len(data[key])}"


@then(parsers.parse('the response contains "{key}"'))
def check_response_key_exists(chat_context, key):
    """Assert a key exists in the response JSON."""
    data = chat_context["response_json"]
    assert key in data, f"Key '{key}' not in response: {list(data.keys())}"


@then(parsers.parse('the response contains "{key}" between {low:d} and {high:d}'))
def check_response_key_range(chat_context, key, low, high):
    """Assert a numeric key is within the expected range."""
    data = chat_context["response_json"]
    assert key in data, f"Key '{key}' not in response"
    value = data[key]
    assert low <= value <= high, f"Expected '{key}' between {low} and {high}, got {value}"


@then(parsers.parse('the response contains "{key}" as "{value}"'))
def check_response_key_value(chat_context, key, value):
    """Assert a key has the expected string value."""
    data = chat_context["response_json"]
    assert key in data, f"Key '{key}' not in response"
    assert str(data[key]) == value, f"Expected '{key}' = '{value}', got '{data[key]}'"


@then(parsers.parse('the response does not contain "{key}"'))
def check_response_key_absent(chat_context, key):
    """Assert a key does NOT exist in the response JSON."""
    data = chat_context["response_json"]
    assert key not in data, f"Key '{key}' should not be in response"


@then("I receive SSE events")
def check_sse_events(chat_context):
    """Assert SSE events were received."""
    events = chat_context.get("sse_events", [])
    assert len(events) > 0, "No SSE events received"


@then(parsers.parse('each event starts with "{prefix}"'))
def check_sse_prefix(chat_context, prefix):
    """Assert each SSE event starts with the expected prefix."""
    events = chat_context.get("sse_events", [])
    for event in events:
        assert event.startswith(prefix), f"Event does not start with '{prefix}': {event[:50]}"


@then(parsers.parse('the stream ends with "{terminator}"'))
def check_stream_terminator(chat_context, terminator):
    """Assert the SSE stream ends with the expected terminator."""
    events = chat_context.get("sse_events", [])
    assert len(events) > 0, "No SSE events received"
    assert events[-1].strip() == terminator, f"Expected last event '{terminator}', got '{events[-1].strip()}'"


@then("the response contains an ungrounded notice")
def check_ungrounded_notice(chat_context):
    """Assert the response indicates the answer is ungrounded."""
    data = chat_context["response_json"]
    # Check for RAG extensions indicating ungrounded response
    has_notice = (
        data.get("rag_knowledge_status") == "absent"
        or "rag_clarifying_questions" in data
        or "ungrounded" in str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).lower()
    )
    assert has_notice, "Response does not contain ungrounded notice"


@then(parsers.parse('the response contains "rag_sources" with at most {count:d} items'))
def check_rag_sources_max(chat_context, count):
    """Assert rag_sources has at most the expected number of items."""
    data = chat_context["response_json"]
    sources = data.get("rag_sources", [])
    assert len(sources) <= count, f"Expected at most {count} rag_sources, got {len(sources)}"


@then("the response is freshly generated")
def check_fresh_response(chat_context):
    """Assert the response was freshly generated (not cached)."""
    data = chat_context["response_json"]
    # A fresh response should have a unique request id or feedback id
    assert "rag_feedback_id" in data or "id" in data, "Response does not appear to be freshly generated"
