from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config import NETWORK, SERVER, SERVICE
from ..models import PlayerState, color_from_name, facing_from_vector, facing_towards, normalize
from ..protocol import ProtocolError, decode_message, read_message, send_message
from ..world import MapLayout


@dataclass
class ClientSession:
    player: PlayerState
    writer: asyncio.StreamWriter


class GameServer:
    def __init__(self) -> None:
        self.map_layout = MapLayout.build_default()
        self.sessions: Dict[str, ClientSession] = {}
        self.server: Optional[asyncio.AbstractServer] = None
        self.health_server: Optional[asyncio.AbstractServer] = None
        self._tick_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self.server = await asyncio.start_server(self.handle_connection, NETWORK.host, NETWORK.port)
        self.health_server = await asyncio.start_server(self.handle_health_connection, NETWORK.host, SERVICE.health_port)
        self._tick_task = asyncio.create_task(self.game_loop(), name="game-loop")
        sockets = self.server.sockets or []
        addresses = ", ".join(str(sock.getsockname()) for sock in sockets)
        print(f"Skyroom server listening on {addresses}")
        health_sockets = self.health_server.sockets or []
        health_addresses = ", ".join(str(sock.getsockname()) for sock in health_sockets)
        print(f"Skyroom health listening on {health_addresses}")

    async def stop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.health_server:
            self.health_server.close()
            await self.health_server.wait_closed()
        for session in list(self.sessions.values()):
            session.writer.close()
            with contextlib.suppress(Exception):
                await session.writer.wait_closed()
        self.sessions.clear()

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        player_id = ""
        try:
            raw_line = await reader.readline()
            if not raw_line:
                raise ConnectionError("Socket closed")
            hello = decode_message(raw_line)
            if hello.get("type") == "ping":
                await send_message(writer, {"type": "pong", "server": "skyroom"})
                return
            if hello.get("type") != "hello":
                raise ProtocolError("Expected hello packet first")

            name = str(hello.get("name", "")).strip()[:18] or "Starlight"
            player = self.create_player(name)
            player_id = player.player_id
            self.sessions[player_id] = ClientSession(player=player, writer=writer)

            await send_message(
                writer,
                {
                    "type": "welcome",
                    "self_id": player_id,
                    "map": self.map_layout.as_dict(),
                    "tick_rate": SERVER.tick_rate,
                },
            )
            await self.broadcast_event(
                {
                    "type": "system",
                    "message": f"{player.name} joined the room.",
                }
            )

            while True:
                payload = await read_message(reader)
                await self.handle_client_message(player_id, payload)
        except (ConnectionError, asyncio.IncompleteReadError, ProtocolError):
            pass
        finally:
            if player_id and player_id in self.sessions:
                player_name = self.sessions[player_id].player.name
                self.sessions.pop(player_id, None)
                await self.broadcast_event(
                    {
                        "type": "system",
                        "message": f"{player_name} left the room.",
                    }
                )
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def handle_health_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            while True:
                header_line = await reader.readline()
                if not header_line or header_line in (b"\r\n", b"\n"):
                    break
            if request_line.startswith(b"GET /health "):
                await self.respond_health(writer)
            else:
                await self.respond_not_found(writer)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def respond_health(self, writer: asyncio.StreamWriter) -> None:
        payload = {
            "status": True,
            "server_name": SERVICE.server_name,
            "server_host": SERVICE.public_host,
            "server_port": SERVICE.public_port,
            "online": len(self.sessions),
        }
        await self.respond_json(writer, 200, payload)

    async def respond_not_found(self, writer: asyncio.StreamWriter) -> None:
        await self.respond_json(writer, 404, {"status": False})

    async def respond_json(self, writer: asyncio.StreamWriter, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        reason = "OK" if status_code == 200 else "Not Found"
        header = (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        writer.write(header + body)
        await writer.drain()

    def create_player(self, name: str) -> PlayerState:
        x, y = self.map_layout.choose_spawn(session.player for session in self.sessions.values())
        return PlayerState(
            player_id=uuid.uuid4().hex[:8],
            name=name,
            x=x,
            y=y,
            color=color_from_name(name),
        )

    async def handle_client_message(self, player_id: str, payload: dict[str, Any]) -> None:
        session = self.sessions.get(player_id)
        if not session:
            return

        player = session.player
        message_type = payload.get("type")

        if message_type == "move":
            move_x = float(payload.get("x", 0.0))
            move_y = float(payload.get("y", 0.0))
            move_x, move_y = normalize(move_x, move_y)
            player.input_state.move_x = move_x
            player.input_state.move_y = move_y
            if move_x or move_y:
                player.input_state.clear_target()
                player.facing = facing_from_vector(move_x, move_y, player.facing)
            return

        if message_type == "click_move":
            target_x = float(payload.get("x", player.x))
            target_y = float(payload.get("y", player.y))
            player.input_state.target_x = max(0.0, min(self.map_layout.width, target_x))
            player.input_state.target_y = max(0.0, min(self.map_layout.height, target_y))
            return

        if message_type == "turn":
            facing = payload.get("facing")
            if facing in {"up", "right", "down", "left"}:
                player.facing = facing
            return

        if message_type == "toggle_glow":
            self.trigger_joy(player)
            return

        if message_type == "chat":
            text = str(payload.get("text", "")).strip().replace("\n", " ")[:80]
            if text:
                player.chat_text = text
                player.chat_until = time.time() + SERVER.chat_duration
            return

        if message_type == "handshake":
            self.try_handshake(player)

    def try_handshake(self, initiator: PlayerState) -> None:
        now = time.time()
        best_candidate: Optional[PlayerState] = None
        best_distance = SERVER.handshake_distance
        for session in self.sessions.values():
            other = session.player
            if other.player_id == initiator.player_id:
                continue
            distance = ((initiator.x - other.x) ** 2 + (initiator.y - other.y) ** 2) ** 0.5
            if distance <= best_distance:
                best_candidate = other
                best_distance = distance

        if not best_candidate:
            return

        initiator.facing = facing_towards((initiator.x, initiator.y), (best_candidate.x, best_candidate.y), initiator.facing)
        best_candidate.facing = facing_towards((best_candidate.x, best_candidate.y), (initiator.x, initiator.y), best_candidate.facing)
        initiator.handshake_started_at = now
        best_candidate.handshake_started_at = now
        initiator.handshake_until = now + SERVER.handshake_duration
        best_candidate.handshake_until = now + SERVER.handshake_duration
        initiator.handshake_partner_id = best_candidate.player_id
        best_candidate.handshake_partner_id = initiator.player_id

    def trigger_joy(self, player: PlayerState) -> None:
        now = time.time()
        duration = random.uniform(1.8, 3.2)
        player.glow_active = True
        player.joy_started_at = now
        player.joy_until = now + duration
        player.joy_seed = random.random()

    async def game_loop(self) -> None:
        dt = 1.0 / SERVER.tick_rate
        while True:
            tick_started = time.perf_counter()
            self.update_world(dt)
            await self.broadcast_snapshot()
            elapsed = time.perf_counter() - tick_started
            await asyncio.sleep(max(0.0, dt - elapsed))

    def update_world(self, dt: float) -> None:
        players = [session.player for session in self.sessions.values()]
        now = time.time()
        for player in players:
            if player.glow_active and now >= player.joy_until:
                player.glow_active = False
            if player.handshake_until and now >= player.handshake_until:
                player.handshake_partner_id = None
            desired_dx, desired_dy = self.compute_velocity(player)
            if desired_dx or desired_dy:
                self.try_move(player, desired_dx * dt, desired_dy * dt, players)

    def compute_velocity(self, player: PlayerState) -> tuple[float, float]:
        if player.input_state.move_x or player.input_state.move_y:
            return player.input_state.move_x * SERVER.player_speed, player.input_state.move_y * SERVER.player_speed

        if player.input_state.target_x is not None and player.input_state.target_y is not None:
            delta_x = player.input_state.target_x - player.x
            delta_y = player.input_state.target_y - player.y
            direction_x, direction_y = normalize(delta_x, delta_y)
            distance = (delta_x ** 2 + delta_y ** 2) ** 0.5
            if distance < 10:
                player.input_state.clear_target()
                return 0.0, 0.0
            player.facing = facing_from_vector(direction_x, direction_y, player.facing)
            return direction_x * SERVER.player_speed, direction_y * SERVER.player_speed

        return 0.0, 0.0

    def try_move(self, player: PlayerState, move_x: float, move_y: float, players: List[PlayerState]) -> None:
        radius = SERVER.player_radius
        next_x = player.x + move_x
        if not self.map_layout.collides(next_x, player.y, radius, players, skip_id=player.player_id):
            player.x = next_x

        next_y = player.y + move_y
        if not self.map_layout.collides(player.x, next_y, radius, players, skip_id=player.player_id):
            player.y = next_y

    async def broadcast_snapshot(self) -> None:
        if not self.sessions:
            return
        now = time.time()
        payload = {
            "type": "snapshot",
            "server_time": now,
            "players": [session.player.as_dict(now) for session in self.sessions.values()],
        }
        stale_ids: List[str] = []
        for player_id, session in self.sessions.items():
            try:
                await send_message(session.writer, payload)
            except ConnectionError:
                stale_ids.append(player_id)
        for player_id in stale_ids:
            self.sessions.pop(player_id, None)

    async def broadcast_event(self, payload: dict[str, Any]) -> None:
        if not self.sessions:
            return
        stale_ids: List[str] = []
        for player_id, session in self.sessions.items():
            try:
                await send_message(session.writer, payload)
            except ConnectionError:
                stale_ids.append(player_id)
        for player_id in stale_ids:
            self.sessions.pop(player_id, None)


async def async_main() -> None:
    server = GameServer()
    await server.start()
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()


def main() -> None:
    asyncio.run(async_main())
