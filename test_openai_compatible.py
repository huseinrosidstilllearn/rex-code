"""Self-check OpenAI-compatible request/response. Run: python test_openai_compatible.py"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.providers.manager import get_llm_provider
from rex.providers.router import OpenAIRouterProvider

received = {}
retry_attempts = 0

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        global retry_attempts
        length = int(self.headers["Content-Length"])
        received["path"] = self.path
        received["auth"] = self.headers.get("Authorization")
        received["body"] = json.loads(self.rfile.read(length))
        last_content = received["body"].get("messages", [{}])[-1].get("content")
        if last_content == "retry demo" and retry_attempts < 2:
            retry_attempts += 1
            self.send_response(503)
            self.end_headers()
            return
        if received["body"].get("stream") and last_content != "json fallback":
            chunks = [
                {"choices": [{"delta": {"content": "Halo "}}]},
                {"choices": [{"delta": {"content": "dunia", "tool_calls": [{
                    "index": 0, "id": "call_stream_1", "function": {"name": "read_file", "arguments": "{\"path\":"}
                }]}}]},
                {"choices": [{"delta": {"tool_calls": [{
                    "index": 0, "function": {"arguments": "\"demo.txt\"}"}
                }]}}]},
            ]
            body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            body += "data: [DONE]\n\n"
            body = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps({
            "choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_server_123",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"demo.txt\"}"},
                }],
            }}]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base_url = f"http://127.0.0.1:{server.server_port}/v1"

cfg = {
    "active_provider": "token_murah",
    "active_model": "cheap-coder",
    "active_mode": "build",
    "router_timeout_sec": 9,
    "providers": {"token_murah": {
        "name": "Token Murah",
        "type": "openai_compatible",
        "base_url": base_url,
        "api_key_env": "TOKEN_MURAH_API_KEY",
        "model": "cheap-coder",
        "available_models": ["cheap-coder"],
    }},
}

try:
    with patch("rex.providers.manager.load_config", return_value=cfg), \
         patch.dict(os.environ, {"TOKEN_MURAH_API_KEY": "secret-test-token"}):
        provider = get_llm_provider()

    assert isinstance(provider, OpenAIRouterProvider)
    assert provider.timeout_sec == 9
    response = provider.chat(
        [{"role": "user", "content": "baca demo"}],
        "Anda agen pengujian.",
        [{"name": "read_file", "description": "Baca file", "parameters": {
            "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]
        }}],
    )
    assert received["path"] == "/v1/chat/completions"
    assert received["auth"] == "Bearer secret-test-token"
    assert received["body"]["model"] == "cheap-coder"
    assert received["body"]["tools"][0]["function"]["name"] == "read_file"
    assert response.tool_calls == [{"id": "call_server_123", "name": "read_file", "args": {"path": "demo.txt"}}]
    events = list(provider.chat_stream(
        [{"role": "user", "content": "stream demo"}],
        "Anda agen pengujian.",
        [{"name": "read_file", "description": "Baca file", "parameters": {"type": "object", "properties": {}}}],
    ))
    assert [event.data for event in events if event.kind == "text"] == ["Halo ", "dunia"]
    final = events[-1].data
    assert final.content == "Halo dunia"
    assert final.tool_calls == [{"id": "call_stream_1", "name": "read_file", "args": {"path": "demo.txt"}}]
    assert received["body"]["stream"] is True
    fallback = list(provider.chat_stream(
        [{"role": "user", "content": "json fallback"}], "sistem"
    ))
    assert fallback[-1].kind == "final"
    assert fallback[-1].data.tool_calls[0]["id"] == "call_server_123"
    provider.retry_backoff_sec = 0
    retry = provider.chat([{"role": "user", "content": "retry demo"}], "sistem")
    assert retry_attempts == 2 and retry.tool_calls[0]["id"] == "call_server_123"
    print("OpenAI-compatible provider checks 13/13 PASS")
finally:
    server.shutdown()
    server.server_close()
