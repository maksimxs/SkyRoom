from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from ..config import ENDPOINT


LogFn = Optional[Callable[[str, str, str, str, str], None]]


@dataclass
class EndpointServerRecord:
    server_name: str
    server_host: str
    server_port: int
    status: bool

    @property
    def key(self) -> str:
        return f"{self.server_host}:{self.server_port}"


class EndpointClient:
    def __init__(self, base_url: str = ENDPOINT.base_url, timeout: float = ENDPOINT.timeout, logger: LogFn = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logger

    def fetch_servers(self) -> tuple[bool, list[EndpointServerRecord], str]:
        payload, ok, error = self._request("GET", "/servers")
        servers: list[EndpointServerRecord] = []
        if ok:
            for item in payload.get("servers", []) if isinstance(payload, dict) else []:
                try:
                    servers.append(
                        EndpointServerRecord(
                            server_name=str(item.get("server_name", "")).strip() or "Skyroom Server",
                            server_host=str(item.get("server_host", "")).strip(),
                            server_port=int(item.get("server_port", 0)),
                            status=bool(item.get("status", False)),
                        )
                    )
                except (TypeError, ValueError):
                    continue
        return ok and bool(payload.get("status", False)), servers, error

    def post_player_join(self, nick: str, server_name: str, server_host: str, server_port: int, online: int) -> tuple[bool, str]:
        payload = {
            "nick": nick,
            "server_name": server_name,
            "server_host": server_host,
            "server_port": server_port,
            "online": online,
        }
        response, ok, error = self._request("POST", "/player-join", payload)
        return ok and bool(response.get("status", False)), error

    def post_entry(self) -> tuple[bool, str]:
        response, ok, error = self._request("POST", "/entry", {})
        return ok and bool(response.get("status", False)), error

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> tuple[dict, bool, str]:
        url = f"{self.base_url}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "User-Agent": "curl/8.0.1",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        self._log("ENDPOINT", "<-", f"{path}" + (f" {payload}" if payload is not None else ""), method=method, level="INFO")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                self._log("ENDPOINT", "->", f"{path} {response.status} {parsed}", method=method, level="INFO")
                return parsed if isinstance(parsed, dict) else {}, True, ""
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            self._log("ENDPOINT", "->", f"{path} ERROR {exc}", method=method, level="ERROR")
            return {}, False, str(exc)

    def _log(self, source: str, direction: str, message: str, method: str = "", level: str = "INFO") -> None:
        if self.logger:
            self.logger(source, direction, message, method, level)
