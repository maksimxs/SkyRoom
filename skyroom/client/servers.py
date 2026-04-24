from __future__ import annotations

from dataclasses import asdict, dataclass
import http.client
import ipaddress
from pathlib import Path
import json
import queue
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, Iterable, Optional

from ..config import SERVICE

DEFAULT_SERVER_PATH = Path("servers.json")
DEFAULT_BROWSER_STATE_PATH = Path("server_browser_state.json")
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?!-)(?:[a-zA-Z0-9-]{1,63}\.)*[a-zA-Z0-9-]{1,63}$")
LogFn = Optional[Callable[[str, str, str, str, str], None]]


@dataclass
class ServerEntry:
    name: str
    host: str
    port: int

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"


def is_valid_host(host: str) -> bool:
    candidate = host.strip()
    if not candidate or any(char.isspace() for char in candidate):
        return False
    lowered = candidate.lower()
    if lowered == "localhost":
        return True
    if "://" in candidate or "/" in candidate or "\\" in candidate or ":" in candidate:
        return False
    try:
        ipaddress.IPv4Address(candidate)
        return True
    except ipaddress.AddressValueError:
        pass
    if candidate.endswith("."):
        candidate = candidate[:-1]
    if not candidate or "." not in candidate:
        return False
    if not HOSTNAME_RE.fullmatch(candidate):
        return False
    return all(not part.startswith("-") and not part.endswith("-") for part in candidate.split("."))


def is_valid_server_entry(host: str, port: int) -> bool:
    return is_valid_host(host) and 1 <= port <= 65535


@dataclass
class HealthResult:
    online: bool = False
    ping_ms: Optional[int] = None
    checked_at: float = 0.0
    server_name: str = ""
    online_count: Optional[int] = None
    status_flag: bool = False

    @property
    def bars(self) -> int:
        if not self.online or self.ping_ms is None:
            return 0
        if self.ping_ms <= 90:
            return 3
        if self.ping_ms <= 180:
            return 2
        return 1


class ServerStore:
    def __init__(self, path: Path = DEFAULT_SERVER_PATH) -> None:
        self.path = path
        self.servers: list[ServerEntry] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.servers = [ServerEntry("Local Skyroom", "127.0.0.1", 8765)]
            self.save()
            return

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = []

        servers: list[ServerEntry] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                name = str(item.get("name", "")).strip() or "Skyroom Server"
                host = str(item.get("host", "")).strip() or "127.0.0.1"
                port = int(item.get("port", 8765))
            except (AttributeError, TypeError, ValueError):
                continue
            if is_valid_server_entry(host, port):
                servers.append(ServerEntry(name=name[:32], host=host[:128], port=port))

        self.servers = servers or [ServerEntry("Local Skyroom", "127.0.0.1", 8765)]

    def save(self) -> None:
        payload = [asdict(server) for server in self.servers]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add(self, server: ServerEntry) -> None:
        self.servers.append(server)
        self.save()

    def update(self, index: int, server: ServerEntry) -> None:
        if 0 <= index < len(self.servers):
            self.servers[index] = server
            self.save()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.servers):
            self.servers.pop(index)
            self.save()


class BrowserStateStore:
    def __init__(self, path: Path = DEFAULT_BROWSER_STATE_PATH) -> None:
        self.path = path
        self.seen_endpoint_keys: set[str] = set()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.seen_endpoint_keys = set()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        seen = raw.get("seen_endpoint_keys", []) if isinstance(raw, dict) else []
        self.seen_endpoint_keys = {str(item) for item in seen if isinstance(item, str)}

    def save(self) -> None:
        payload = {"seen_endpoint_keys": sorted(self.seen_endpoint_keys)}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def mark_seen(self, keys: Iterable[str]) -> None:
        updated = False
        for key in keys:
            if key not in self.seen_endpoint_keys:
                self.seen_endpoint_keys.add(key)
                updated = True
        if updated:
            self.save()


class ServerStatusChecker:
    def __init__(self, interval: float = 5.0, timeout: float = 1.5, logger: LogFn = None) -> None:
        self.interval = interval
        self.timeout = timeout
        self.logger = logger
        self.results: Dict[str, HealthResult] = {}
        self._pending: set[str] = set()
        self._queue: "queue.Queue[tuple[str, HealthResult]]" = queue.Queue()

    def tick(self, servers: Iterable[ServerEntry]) -> None:
        self._consume_results()
        for server in servers:
            if server.key in self._pending:
                continue
            if server.key in self.results:
                continue
            self._pending.add(server.key)
            threading.Thread(target=self._check, args=(server,), daemon=True).start()

    def get(self, server: ServerEntry) -> HealthResult:
        return self.results.get(server.key, HealthResult(checked_at=0.0))

    def check_once(self, server: ServerEntry) -> HealthResult:
        started = time.perf_counter()
        url = f"http://{server.host}:{SERVICE.health_port}/health"
        self._log("SERVER", "<-", url, method="GET", level="INFO")
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                payload = json.loads(body) if body else {}
                ping_ms = max(1, int((time.perf_counter() - started) * 1000))
                ok = bool(payload.get("status", False))
                result = HealthResult(
                    online=ok,
                    ping_ms=ping_ms if ok else None,
                    checked_at=time.time(),
                    server_name=str(payload.get("server_name", "")).strip(),
                    online_count=int(payload.get("online", 0)) if ok else None,
                    status_flag=ok,
                )
                self._log("SERVER", "->", f"{url} {response.status} {payload}", method="GET", level="INFO")
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            json.JSONDecodeError,
            TimeoutError,
            socket.timeout,
            OSError,
            ValueError,
        ) as exc:
            result = HealthResult(online=False, ping_ms=None, checked_at=time.time(), status_flag=False)
            self._log("SERVER", "->", f"{url} ERROR {exc}", method="GET", level="ERROR")
        self.results[server.key] = result
        return result

    def refresh_now(self, servers: Iterable[ServerEntry]) -> None:
        for server in servers:
            self.results.pop(server.key, None)

    def _consume_results(self) -> None:
        while True:
            try:
                key, result = self._queue.get_nowait()
            except queue.Empty:
                return
            self._pending.discard(key)
            self.results[key] = result

    def _check(self, server: ServerEntry) -> None:
        try:
            result = self.check_once(server)
        except Exception as exc:
            result = HealthResult(online=False, ping_ms=None, checked_at=time.time(), status_flag=False)
            url = f"http://{server.host}:{SERVICE.health_port}/health"
            self._log("SERVER", "->", f"{url} ERROR unexpected {exc}", method="GET", level="ERROR")
        self._queue.put((server.key, result))

    def _log(self, source: str, direction: str, message: str, method: str = "", level: str = "INFO") -> None:
        if self.logger:
            self.logger(source, direction, message, method, level)
