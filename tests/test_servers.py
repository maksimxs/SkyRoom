from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from skyroom.client.servers import BrowserStateStore, ServerEntry, ServerStatusChecker, ServerStore, is_valid_host
from skyroom.config import SERVICE


class FakeHTTPResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("play.skyroom.dev", True),
        ("bad host", False),
        ("https://skyroom.dev", False),
        ("play.skyroom.dev:8765", False),
        ("", False),
    ],
)
def test_is_valid_host_cases(host: str, expected: bool) -> None:
    assert is_valid_host(host) is expected


def test_server_store_creates_default_local_entry_when_file_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "servers.json"

    store = ServerStore(path)

    assert [server.name for server in store.servers] == ["Local Skyroom"]
    assert store.servers[0].host == "127.0.0.1"
    assert store.servers[0].port == 8765
    assert path.exists() is True


def test_browser_state_store_persists_seen_endpoint_keys_sorted(tmp_path: Path) -> None:
    path = tmp_path / "browser-state.json"
    store = BrowserStateStore(path)

    store.mark_seen(["z.skyroom.dev:8765", "a.skyroom.dev:8765", "z.skyroom.dev:8765"])
    reloaded = BrowserStateStore(path)

    assert reloaded.seen_endpoint_keys == {"a.skyroom.dev:8765", "z.skyroom.dev:8765"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["seen_endpoint_keys"] == ["a.skyroom.dev:8765", "z.skyroom.dev:8765"]


def test_status_checker_parses_health_payload_and_logs_request(monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[tuple[str, str, str, str, str]] = []
    checker = ServerStatusChecker(timeout=1.2, logger=lambda *args: logs.append(args))
    server = ServerEntry("Pastel", "play.skyroom.dev", 8765)

    def fake_urlopen(url: str, timeout: float) -> FakeHTTPResponse:
        assert url == f"http://play.skyroom.dev:{SERVICE.health_port}/health"
        assert timeout == 1.2
        return FakeHTTPResponse({"status": True, "server_name": "Pastel", "online": 7}, status=200)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = checker.check_once(server)

    assert result.online is True
    assert result.server_name == "Pastel"
    assert result.online_count == 7
    assert result.ping_ms is not None and result.ping_ms >= 1
    assert checker.results[server.key] == result
    assert logs[0][:4] == ("SERVER", "<-", f"http://play.skyroom.dev:{SERVICE.health_port}/health", "GET")
    assert logs[-1][1] == "->"
    assert logs[-1][4] == "INFO"


def test_status_checker_returns_offline_on_health_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = ServerStatusChecker()
    server = ServerEntry("Pastel", "play.skyroom.dev", 8765)

    def fake_urlopen(url: str, timeout: float) -> FakeHTTPResponse:
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = checker.check_once(server)

    assert result.online is False
    assert result.ping_ms is None
    assert result.online_count is None
