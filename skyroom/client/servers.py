from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import queue
import socket
import threading
import time
from typing import Dict, Iterable, Optional

from ..protocol import ProtocolError, decode_message, encode_message


DEFAULT_SERVER_PATH = Path("servers.json")


@dataclass
class ServerEntry:
    name: str
    host: str
    port: int

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class PingResult:
    online: bool = False
    ping_ms: Optional[int] = None
    checked_at: float = 0.0

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
            if 1 <= port <= 65535:
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


class ServerStatusChecker:
    def __init__(self, interval: float = 5.0, timeout: float = 1.2) -> None:
        self.interval = interval
        self.timeout = timeout
        self.results: Dict[str, PingResult] = {}
        self._pending: set[str] = set()
        self._queue: "queue.Queue[tuple[str, PingResult]]" = queue.Queue()

    def tick(self, servers: Iterable[ServerEntry]) -> None:
        self._consume_results()
        now = time.time()
        for server in servers:
            result = self.results.get(server.key)
            if server.key in self._pending:
                continue
            if result and now - result.checked_at < self.interval:
                continue
            self._pending.add(server.key)
            thread = threading.Thread(target=self._check, args=(server,), daemon=True)
            thread.start()

    def get(self, server: ServerEntry) -> PingResult:
        return self.results.get(server.key, PingResult(checked_at=0.0))

    def check_once(self, server: ServerEntry) -> PingResult:
        started = time.perf_counter()
        try:
            sock = socket.create_connection((server.host, server.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            with sock:
                sock.sendall(encode_message({"type": "ping"}))
                raw_line = self._read_line(sock)
                payload = decode_message(raw_line)
                if payload.get("type") != "pong":
                    raise ProtocolError("Unexpected ping response")
                ping_ms = max(1, int((time.perf_counter() - started) * 1000))
                result = PingResult(online=True, ping_ms=ping_ms, checked_at=time.time())
        except (OSError, ProtocolError):
            result = PingResult(online=False, ping_ms=None, checked_at=time.time())
        self.results[server.key] = result
        return result

    def _read_line(self, sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(1)
            if not chunk:
                raise ConnectionError("Socket closed")
            chunks.append(chunk)
            if chunk == b"\n":
                return b"".join(chunks)

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
        result = self.check_once(server)
        self._queue.put((server.key, result))
