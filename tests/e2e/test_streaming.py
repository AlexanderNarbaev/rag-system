"""E2E tests for streaming RAG responses via SSE."""

import json

import pytest
import requests


@pytest.mark.e2e
class TestStreamingRAG:
    """E2E tests for streaming /v1/chat/completions."""

    def test_streaming_rag(self, service_url: str, auth_headers: dict):
        """SSE streaming -> collect chunks -> verify final metadata."""
        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "What is RAG?"}],
            "temperature": 0.2,
            "stream": True,
        }
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json=payload,
            headers={**auth_headers, "Accept": "text/event-stream"},
            timeout=60,
            stream=True,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        chunks = []
        final_metadata = None
        done_received = False

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data: "):
                data_str = line[len("data: ") :]
                if data_str == "[DONE]":
                    done_received = True
                    break
                try:
                    data = json.loads(data_str)
                    if "rag_feedback_id" in data:
                        final_metadata = data
                    elif "choices" in data:
                        chunks.append(data)
                except json.JSONDecodeError:
                    continue

        assert len(chunks) > 0, "No content chunks received"
        assert done_received, "[DONE] not received"
        if final_metadata:
            assert "rag_feedback_id" in final_metadata
            assert "rag_confidence" in final_metadata

    def test_streaming_empty_query(self, service_url: str, auth_headers: dict):
        """SSE streaming with minimal query -> still returns chunks."""
        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "test"}],
            "stream": True,
        }
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json=payload,
            headers={**auth_headers, "Accept": "text/event-stream"},
            timeout=30,
            stream=True,
        )
        assert resp.status_code == 200
        chunk_count = 0
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                chunk_count += 1
                if chunk_count > 20:
                    break
        assert chunk_count > 0

    def test_streaming_headers_and_status(self, service_url: str, auth_headers: dict):
        """Verify SSE response has correct content type and status."""
        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json=payload,
            headers={**auth_headers, "Accept": "text/event-stream"},
            timeout=30,
            stream=True,
        )
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type or "text/plain" in content_type
