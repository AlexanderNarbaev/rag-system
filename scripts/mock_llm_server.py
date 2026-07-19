"""Minimal OpenAI-compatible mock LLM server for testing.

Provides:
- GET /v1/health — returns 200
- POST /v1/chat/completions — returns a mock response
- POST /v1/completions — returns a mock response
"""
import json
import time
import uuid

from http.server import HTTPServer, BaseHTTPRequestHandler


class MockLLMHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/health":
            self._respond(200, {"status": "ok"})
        elif self.path == "/v1/models":
            self._respond(200, {
                "object": "list",
                "data": [{"id": "mock-llm", "object": "model", "created": int(time.time()), "owned_by": "mock"}],
            })
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}

        if self.path == "/v1/chat/completions":
            stream = body.get("stream", False)
            if stream:
                self._stream_response(body)
            else:
                self._chat_completion(body)
        elif self.path == "/v1/completions":
            self._completion(body)
        else:
            self._respond(404, {"error": "not found"})

    def _chat_completion(self, body):
        messages = body.get("messages", [])
        last_msg = messages[-1]["content"] if messages else "Hello"
        response = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "mock-llm"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": f"Mock response to: {last_msg[:100]}"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        self._respond(200, response)

    def _completion(self, body):
        prompt = body.get("prompt", "")
        response = {
            "id": f"cmpl-{uuid.uuid4().hex[:8]}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": body.get("model", "mock-llm"),
            "choices": [{"text": f"Mock completion to: {prompt[:100]}", "index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        self._respond(200, response)

    def _stream_response(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        tokens = ["Mock", " streaming", " response", " to", " your", " query."]
        for token in tokens:
            chunk = {
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "mock-llm"),
                "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        # Final chunk
        final = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": body.get("model", "mock-llm"),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _respond(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # Suppress request logging


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8010), MockLLMHandler)
    print("Mock LLM server running on http://0.0.0.0:8010")
    server.serve_forever()
