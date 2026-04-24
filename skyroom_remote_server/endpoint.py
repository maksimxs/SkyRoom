from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from config import ENDPOINT, SERVICE


class EndpointAnnouncer:
    @property
    def enabled(self) -> bool:
        return bool(ENDPOINT.base_url and SERVICE.public_host.strip())

    async def check_up(self) -> None:
        if not self.enabled:
            if ENDPOINT.base_url and not SERVICE.public_host.strip():
                self._log("skip /check-up: SKYROOM_PUBLIC_HOST is not set")
            return
        payload = {
            "server_name": SERVICE.server_name,
            "server_host": SERVICE.public_host.strip(),
            "server_port": SERVICE.public_port,
        }
        try:
            await asyncio.to_thread(self._post_json, "/check-up", payload)
            self._log(f"/check-up ok {SERVICE.server_name} {SERVICE.public_host}:{SERVICE.public_port}")
        except Exception as exc:
            self._log(f"/check-up failed {exc}")

    def _post_json(self, path: str, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{ENDPOINT.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=ENDPOINT.timeout) as response:
                response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def _log(message: str) -> None:
        print(f"ENDPOINT {message}")
