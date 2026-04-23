from __future__ import annotations

import queue
import select
import socket
import threading
from typing import Any, Optional

from ..protocol import ProtocolError, decode_message, encode_message


class ServerConnection:
    def __init__(self, host: str, port: int, player_name: str) -> None:
        self.host = host
        self.port = port
        self.player_name = player_name
        self.incoming: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.outgoing: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="skyroom-network", daemon=True)
        self._socket: Optional[socket.socket] = None

    def start(self) -> None:
        self._thread.start()

    def send(self, payload: dict[str, Any]) -> None:
        if not self._closed.is_set():
            self.outgoing.put(payload)

    def poll(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        while True:
            try:
                messages.append(self.incoming.get_nowait())
            except queue.Empty:
                return messages

    def close(self) -> None:
        self._closed.set()
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass

    def _run(self) -> None:
        buffer = b""
        try:
            sock = socket.create_connection((self.host, self.port), timeout=5.0)
            sock.setblocking(False)
            self._socket = sock
            self._send_direct({"type": "hello", "name": self.player_name})
            self.incoming.put({"type": "connection_state", "state": "connected"})

            while not self._closed.is_set():
                self._flush_outgoing()
                readable, _, _ = select.select([sock], [], [], 0.05)
                if not readable:
                    continue

                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Server closed the connection")
                buffer += chunk

                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    if not raw_line:
                        continue
                    payload = decode_message(raw_line + b"\n")
                    self.incoming.put(payload)
        except (ConnectionError, OSError, ProtocolError) as exc:
            self.incoming.put({"type": "connection_state", "state": "error", "message": str(exc)})
        finally:
            self._closed.set()

    def _flush_outgoing(self) -> None:
        while True:
            try:
                payload = self.outgoing.get_nowait()
            except queue.Empty:
                return
            self._send_direct(payload)

    def _send_direct(self, payload: dict[str, Any]) -> None:
        if not self._socket:
            return
        self._socket.sendall(encode_message(payload))
