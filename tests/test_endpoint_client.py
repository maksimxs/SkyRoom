from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from skyroom.client.endpoint import EndpointClient


class FakeHTTPResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


def header_map(request: urllib.request.Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.header_items()}


def test_fetch_servers_uses_cloudflare_headers_and_parses_records(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    logs: list[tuple[str, str, str, str, str]] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> FakeHTTPResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeHTTPResponse(
            {
                "status": True,
                "servers": [
                    {
                        "server_name": "Pastel Deck",
                        "server_host": "play.skyroom.dev",
                        "server_port": 8765,
                        "status": True,
                    },
                    {
                        "server_name": "Broken",
                        "server_host": "bad.skyroom.dev",
                        "server_port": "oops",
                        "status": True,
                    },
                ],
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = EndpointClient("https://api.skyroom.dev", timeout=7.5, logger=lambda *args: logs.append(args))

    ok, servers, error = client.fetch_servers()

    assert ok is True
    assert error == ""
    assert len(servers) == 1
    assert servers[0].server_name == "Pastel Deck"
    assert servers[0].server_host == "play.skyroom.dev"
    assert servers[0].server_port == 8765

    request = captured["request"]
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == "https://api.skyroom.dev/servers"
    assert request.get_method() == "GET"
    assert captured["timeout"] == 7.5
    headers = header_map(request)
    assert headers["accept"] == "application/json"
    assert headers["user-agent"] == "curl/8.0.1"
    assert "content-type" not in headers
    assert logs[0][:4] == ("ENDPOINT", "<-", "/servers", "GET")
    assert logs[-1][1] == "->"
    assert logs[-1][4] == "INFO"


def test_post_player_join_sends_json_headers_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> FakeHTTPResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeHTTPResponse({"status": True})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = EndpointClient("https://api.skyroom.dev")

    ok, error = client.post_player_join("User", "Pastel Deck", "play.skyroom.dev", 8765, 7)

    assert ok is True
    assert error == ""
    request = captured["request"]
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == "https://api.skyroom.dev/player-join"
    assert request.get_method() == "POST"
    headers = header_map(request)
    assert headers["accept"] == "application/json"
    assert headers["user-agent"] == "curl/8.0.1"
    assert headers["content-type"] == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "nick": "User",
        "server_name": "Pastel Deck",
        "server_host": "play.skyroom.dev",
        "server_port": 8765,
        "online": 7,
    }


def test_post_entry_sends_empty_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> FakeHTTPResponse:
        captured["request"] = request
        return FakeHTTPResponse({"status": True})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = EndpointClient("https://api.skyroom.dev")

    ok, error = client.post_entry()

    assert ok is True
    assert error == ""
    request = captured["request"]
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == "https://api.skyroom.dev/entry"
    assert request.get_method() == "POST"
    assert json.loads(request.data.decode("utf-8")) == {}
    assert header_map(request)["content-type"] == "application/json"


def test_fetch_servers_soft_fails_on_url_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> FakeHTTPResponse:
        raise urllib.error.URLError("403 Forbidden")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = EndpointClient("https://api.skyroom.dev")

    ok, servers, error = client.fetch_servers()

    assert ok is False
    assert servers == []
    assert "403 Forbidden" in error
