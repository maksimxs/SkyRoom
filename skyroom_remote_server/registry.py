from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Optional

from config import NETWORK, REGISTRY


class RegistryAnnouncer:
    def __init__(self) -> None:
        self._heartbeat_task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return bool(REGISTRY.registry_url and REGISTRY.public_host.strip())

    @property
    def public_host(self) -> str:
        return REGISTRY.public_host.strip()

    @property
    def public_port(self) -> int:
        return REGISTRY.public_port or NETWORK.port

    async def start(self) -> None:
        if not self.enabled:
            if REGISTRY.registry_url:
                print("Registry announce skipped: SKYROOM_PUBLIC_HOST is not set.")
            return
        await self._send("online")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="registry-heartbeat")

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self.enabled:
            await self._send("offline")

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(max(10.0, REGISTRY.heartbeat_interval))
            await self._send("heartbeat")

    async def _send(self, status: str) -> None:
        payload = {
            "game": "skyroom",
            "name": REGISTRY.server_name,
            "host": self.public_host,
            "port": self.public_port,
            "status": status,
            "secret": REGISTRY.shared_secret,
            "timestamp": time.time(),
        }
        try:
            await asyncio.to_thread(self._post_json, payload)
            print(f"Registry {status}: {self.public_host}:{self.public_port}")
        except Exception as exc:
            print(f"Registry {status} failed: {exc}")

    def _post_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            REGISTRY.registry_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc
