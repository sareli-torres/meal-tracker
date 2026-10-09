"""Runs ClaudeBackend through the real Anthropic SDK against a local stub server.

No network and no API key: it checks that the request we build is serialised correctly by the
SDK and that a response in the Messages API shape is turned into a valid estimate.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

anthropic = pytest.importorskip("anthropic")

from mealtrack.vision import ClaudeBackend, MockBackend, VisionError, analyze_photo  # noqa: E402


class _Stub(BaseHTTPRequestHandler):
    captured: dict = {}
    status = 200
    body: dict = {}

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        type(self).captured = {
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "json": json.loads(self.rfile.read(length)),
        }
        data = json.dumps(type(self).body).encode()
        self.send_response(type(self).status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    _Stub.captured, _Stub.status = {}, 200
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield _Stub, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


def _message(payload):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "stub",
        "content": [{"type": "tool_use", "id": "toolu_test", "name": "report_meal", "input": payload}],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def test_request_shape_and_response_parsing_with_the_real_sdk(stub, jpeg_bytes, payload):
    handler, url = stub
    handler.body = _message(payload)
    client = anthropic.Anthropic(base_url=url, api_key="test-key", max_retries=0)
    backend = ClaudeBackend(model="stub-model", client=client)

    analysis = analyze_photo(jpeg_bytes, backend, hint="rice 90 g")

    assert analysis.estimate.kcal == 482.0 and analysis.backend == "claude"
    req = handler.captured
    assert req["path"] == "/v1/messages"
    assert req["headers"]["x-api-key"] == "test-key"
    body = req["json"]
    assert body["model"] == "stub-model"
    assert body["tool_choice"] == {"type": "tool", "name": "report_meal"}
    assert body["tools"][0]["input_schema"]["required"][0] == "is_food"
    image, text = body["messages"][0]["content"]
    assert image["source"]["type"] == "base64" and image["source"]["media_type"] == "image/jpeg"
    assert "rice 90 g" in text["text"]
    assert body["system"].startswith("You estimate the nutrition")


def test_api_errors_become_vision_errors(stub, jpeg_bytes):
    handler, url = stub
    handler.status = 401
    handler.body = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    client = anthropic.Anthropic(base_url=url, api_key="bad", max_retries=0)
    with pytest.raises(VisionError, match="Claude API call failed"):
        ClaudeBackend(client=client).estimate(jpeg_bytes, None)


def test_mock_and_claude_payloads_share_the_same_schema_keys(payload):
    mock = MockBackend().estimate(b"x", None)
    assert set(mock) == set(payload)
    assert set(mock["items"][0]) == set(payload["items"][0])
