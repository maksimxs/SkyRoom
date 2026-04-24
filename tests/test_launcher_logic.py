from __future__ import annotations

import queue
import sys
from types import SimpleNamespace

import pytest

import launcher as launcher_entry
from skyroom.client.endpoint import EndpointServerRecord
from skyroom.client.launcher import DisplayedServer, LOCAL_SERVER_HOST, LOCAL_SERVER_NAME, ManagedProcess, ROLE_FLAG, SkyroomLauncherApp
from skyroom.client.servers import HealthResult, ServerEntry
from skyroom.config import NETWORK


class DummyChecker:
    def __init__(self, results: dict[str, HealthResult] | None = None) -> None:
        self.results = results or {}
        self.refreshed: list[ServerEntry] | None = None

    def get(self, server: ServerEntry) -> HealthResult:
        return self.results.get(server.key, HealthResult())

    def refresh_now(self, servers: list[ServerEntry]) -> None:
        self.refreshed = list(servers)

    def check_once(self, server: ServerEntry) -> HealthResult:
        return self.results.get(server.key, HealthResult())


class FakeThread:
    starts = 0

    def __init__(self, target, daemon: bool = False) -> None:
        self.target = target
        self.daemon = daemon

    def start(self) -> None:
        type(self).starts += 1
        self.target()


def make_launcher_stub() -> SkyroomLauncherApp:
    app = object.__new__(SkyroomLauncherApp)
    app.store = SimpleNamespace(servers=[])
    app.browser_state = SimpleNamespace(seen_endpoint_keys=set(), mark_seen=lambda keys: None)
    app.endpoint_servers = []
    app.new_endpoint_keys = set()
    app.endpoint_queue = queue.Queue()
    app.local_server_queue = queue.Queue()
    app.status = ""
    app.entry_reported = False
    app.local_server_autostarted = False
    app.server_process = None
    app.checker = DummyChecker()
    app.debug_console = SimpleNamespace(log=lambda *args: None)
    app.push_toast = lambda *args, **kwargs: None
    return app


def test_displayed_servers_pins_localhost_and_sorts_rest_by_online_count() -> None:
    app = make_launcher_stub()
    app.store.servers = [
        ServerEntry("Local Skyroom", "127.0.0.1", 8765),
        ServerEntry("Alpha", "alpha.skyroom.dev", 8765),
        ServerEntry("Beta Local Name", "beta.skyroom.dev", 8765),
    ]
    app.endpoint_servers = [
        EndpointServerRecord("Gamma Endpoint", "gamma.skyroom.dev", 8765, True),
        EndpointServerRecord("Beta Endpoint Name", "beta.skyroom.dev", 8765, True),
    ]
    app.new_endpoint_keys = {"gamma.skyroom.dev:8765"}
    app.checker = DummyChecker(
        {
            "alpha.skyroom.dev:8765": HealthResult(online=True, online_count=2),
            "beta.skyroom.dev:8765": HealthResult(online=True, online_count=6),
            "gamma.skyroom.dev:8765": HealthResult(online=True, online_count=9),
        }
    )

    displayed = SkyroomLauncherApp.displayed_servers(app)

    assert [item.server.host for item in displayed] == [
        "127.0.0.1",
        "gamma.skyroom.dev",
        "beta.skyroom.dev",
        "alpha.skyroom.dev",
    ]
    assert displayed[0].is_localhost is True
    assert displayed[1].is_new is True
    assert displayed[2].local_index == 2
    assert displayed[2].from_endpoint is True


def test_consume_endpoint_results_marks_only_unseen_nonlocal_servers_as_new() -> None:
    seen_before = {"seen.skyroom.dev:8765"}
    marked: list[str] = []
    app = make_launcher_stub()
    app.store.servers = [ServerEntry("Saved Duplicate", "saved.skyroom.dev", 8765)]
    app.browser_state = SimpleNamespace(
        seen_endpoint_keys=set(seen_before),
        mark_seen=lambda keys: marked.extend(list(keys)),
    )
    app.endpoint_queue.put(
        (
            True,
            [
                EndpointServerRecord("Seen", "seen.skyroom.dev", 8765, True),
                EndpointServerRecord("Fresh", "fresh.skyroom.dev", 8765, True),
                EndpointServerRecord("Saved Duplicate", "saved.skyroom.dev", 8765, True),
                EndpointServerRecord("Broken", "bad host", 8765, True),
            ],
            "",
        )
    )

    SkyroomLauncherApp.consume_endpoint_results(app)

    assert [item.key for item in app.endpoint_servers] == [
        "seen.skyroom.dev:8765",
        "fresh.skyroom.dev:8765",
        "saved.skyroom.dev:8765",
    ]
    assert app.new_endpoint_keys == {"fresh.skyroom.dev:8765"}
    assert marked == ["seen.skyroom.dev:8765", "fresh.skyroom.dev:8765", "saved.skyroom.dev:8765"]
    assert app.status == "Loaded 3 servers from endpoint."


def test_local_server_env_keeps_local_only_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_launcher_stub()
    monkeypatch.setenv("SKYROOM_PUBLIC_HOST", "1.2.3.4")
    monkeypatch.setenv("SKYROOM_PUBLIC_PORT", "9999")
    monkeypatch.setenv("SKYROOM_ENDPOINT_BASE_URL", "https://api.skyroom.dev")
    monkeypatch.setenv("SKYROOM_CHECKUP_INTERVAL", "180")

    env = SkyroomLauncherApp.local_server_env(app)

    assert env["SKYROOM_HOST"] == LOCAL_SERVER_HOST
    assert env["SKYROOM_PORT"] == str(NETWORK.port)
    assert env["SKYROOM_SERVER_NAME"] == LOCAL_SERVER_NAME
    assert "SKYROOM_PUBLIC_HOST" not in env
    assert "SKYROOM_PUBLIC_PORT" not in env
    assert "SKYROOM_ENDPOINT_BASE_URL" not in env
    assert "SKYROOM_CHECKUP_INTERVAL" not in env


def test_report_entry_once_only_starts_single_background_call(monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_launcher_stub()
    calls: list[str] = []
    FakeThread.starts = 0
    app.endpoint = SimpleNamespace(post_entry=lambda: calls.append("entry"))

    monkeypatch.setattr("skyroom.client.launcher.threading.Thread", FakeThread)

    SkyroomLauncherApp.report_entry_once(app)
    SkyroomLauncherApp.report_entry_once(app)

    assert app.entry_reported is True
    assert FakeThread.starts == 1
    assert calls == ["entry"]


def test_refresh_all_servers_only_rechecks_visible_entries() -> None:
    app = make_launcher_stub()
    visible = [
        DisplayedServer(ServerEntry("Local", "127.0.0.1", 8765), 0, False, False, False, True),
        DisplayedServer(ServerEntry("Pastel", "play.skyroom.dev", 8765), None, True, True, False),
    ]
    app.displayed_servers = lambda: visible  # type: ignore[method-assign]

    SkyroomLauncherApp.refresh_all_servers(app)

    assert app.checker.refreshed == [item.server for item in visible]
    assert app.status == "Refreshing 2 visible servers..."


def test_verify_local_server_start_reports_already_running_when_port_is_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_launcher_stub()
    app.server_process = ManagedProcess("server", SimpleNamespace(pid=42, poll=lambda: 1))
    app.checker = DummyChecker({"127.0.0.1:8765": HealthResult(online=True)})

    monkeypatch.setattr("skyroom.client.launcher.time.sleep", lambda _: None)

    SkyroomLauncherApp._verify_local_server_start(app, 42, True)

    state, pid, auto, message = app.local_server_queue.get_nowait()
    assert (state, pid, auto) == ("already_running", 42, True)
    assert message == "Local server is already available on localhost."


def test_runtime_command_uses_role_flag_when_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "SkyRoom.exe")

    assert SkyroomLauncherApp.runtime_command("server") == ["SkyRoom.exe", ROLE_FLAG, "server"]
    assert SkyroomLauncherApp.runtime_command("client") == ["SkyRoom.exe", ROLE_FLAG, "client"]


def test_runtime_command_uses_python_scripts_when_not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", "python.exe")

    assert SkyroomLauncherApp.runtime_command("server") == ["python.exe", "server.py"]
    assert SkyroomLauncherApp.runtime_command("client") == ["python.exe", "client.py"]


def test_launcher_entry_extracts_role_and_cleans_args() -> None:
    role, args = launcher_entry._extract_role(["--foo", "--skyroom-role", "server", "--bar"])

    assert role == "server"
    assert args == ["--foo", "--bar"]
