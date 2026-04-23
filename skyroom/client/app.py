from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from typing import Any, Dict, Optional

import pygame

from ..config import CLIENT, ENDPOINT, NETWORK, SERVER
from ..models import clamp, facing_from_vector, lerp
from .chrome import AudioController, create_window_icon
from .debug import DebugConsole
from .endpoint import EndpointClient
from .network import ServerConnection
from .rendering import SceneRenderer, pick_font_name
from .state import PlayerView, Toast


class SkyroomClientApp:
    def __init__(self, host: str = NETWORK.host, port: int = NETWORK.port) -> None:
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        pygame.init()
        pygame.font.init()
        pygame.display.set_caption("Skyroom")
        self.screen = pygame.display.set_mode((CLIENT.width, CLIENT.height), pygame.RESIZABLE)
        pygame.display.set_icon(create_window_icon())
        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()
        self.font_name = pick_font_name()
        self.font_small = pygame.font.SysFont(self.font_name, 18)
        self.font_body = pygame.font.SysFont(self.font_name, 22)
        self.font_ui = pygame.font.SysFont(self.font_name, 28)
        self.font_title = pygame.font.SysFont(self.font_name, 52, bold=True)
        self.font_emoji = pygame.font.SysFont("Segoe UI Emoji", 28)
        self.font_console = pygame.font.SysFont(self.font_name, 18)
        self.running = True
        self.scene = "login"
        self.login_name = ""
        self.server_host = host
        self.server_port = port
        self.server_name = os.getenv("SKYROOM_SERVER_NAME", "")
        self.connection: Optional[ServerConnection] = None
        self.connection_state = "offline"
        self.connection_message = ""
        self.self_id: Optional[str] = None
        self.map_data: Optional[Dict[str, Any]] = None
        self.players: Dict[str, PlayerView] = {}
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.last_move_payload = (999.0, 999.0)
        self.chat_mode = False
        self.chat_input = ""
        self.toasts: list[Toast] = []
        self.last_mouse_facing = "down"
        self.player_join_reported = False
        self.active_handshake_pairs: set[tuple[str, str]] = set()
        self.cloud_phase = 0.0
        self.mouse_walk_active = False
        self.last_mouse_walk_sent_at = 0.0
        self.last_mouse_walk_target = (-9999.0, -9999.0)
        rng = random.Random(time.time_ns())
        self.cloud_specs = [
            {
                "offset": rng.uniform(-240.0, CLIENT.width + 240.0),
                "y": rng.uniform(52.0, 620.0),
                "speed": rng.uniform(9.0, 26.0),
                "wobble": rng.uniform(6.0, 18.0),
                "scale": rng.uniform(0.72, 1.18),
                "drift": rng.uniform(120.0, 340.0),
                "phase": rng.uniform(0.0, math.tau),
            }
            for _ in range(8)
        ]
        self.audio = AudioController()
        self.audio.set_scene("login")
        self.debug_console = DebugConsole()
        self.endpoint = EndpointClient(base_url=ENDPOINT.base_url, timeout=ENDPOINT.timeout, logger=self.debug_console.log)
        self.renderer = SceneRenderer(self)

    def run(self) -> None:
        while self.running:
            dt = min(0.05, self.clock.tick(CLIENT.fps) / 1000.0)
            self.cloud_phase += dt
            self.handle_events()
            self.consume_network()
            self.update(dt)
            self.renderer.draw()
        self.shutdown()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return
            if event.type == pygame.VIDEORESIZE:
                self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                continue
            if self.debug_console.handle_event(event, self.screen.get_size()):
                continue
            if self.scene == "login":
                self.handle_login_event(event)
            else:
                self.handle_world_event(event)

    def handle_login_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_d and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                self.debug_console.toggle()
                return
            if event.key == pygame.K_RETURN:
                self.try_connect()
            elif event.key == pygame.K_BACKSPACE:
                self.login_name = self.login_name[:-1]
            elif event.unicode.isprintable() and len(self.login_name) < 18:
                self.login_name += event.unicode
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.login_button_rect().collidepoint(event.pos):
                self.try_connect()

    def handle_world_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_d and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                self.debug_console.toggle()
                return
            if self.chat_mode:
                if event.key == pygame.K_RETURN:
                    text = self.chat_input.strip()
                    if text and self.connection:
                        self.connection.send({"type": "chat", "text": text})
                    self.chat_input = ""
                    self.chat_mode = False
                elif event.key == pygame.K_ESCAPE:
                    self.chat_input = ""
                    self.chat_mode = False
                elif event.key == pygame.K_BACKSPACE:
                    self.chat_input = self.chat_input[:-1]
                elif event.unicode.isprintable() and len(self.chat_input) < 80:
                    self.chat_input += event.unicode
                return

            if event.key == pygame.K_RETURN:
                self.chat_mode = True
                self.chat_input = ""
            elif event.key == pygame.K_q and self.connection:
                self.connection.send({"type": "toggle_glow"})
            elif event.key == pygame.K_e:
                if self.player_nearby():
                    if self.connection:
                        self.connection.send({"type": "handshake"})
                else:
                    self.push_toast("No one nearby for a handshake yet.")

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not self.chat_mode:
            if self.connection and self.self_id and self.self_id in self.players:
                self.mouse_walk_active = True
                world_x, world_y = self.screen_to_world(event.pos)
                self.connection.send({"type": "click_move", "x": world_x, "y": world_y})

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.mouse_walk_active = False

        if event.type == pygame.MOUSEMOTION and not self.chat_mode:
            self.update_mouse_facing(event.pos)

    def try_connect(self) -> None:
        name = self.login_name.strip()
        if not name:
            self.push_toast("Type your name first.")
            return
        if self.connection:
            self.connection.close()
        self.scene = "login"
        self.self_id = None
        self.map_data = None
        self.players.clear()
        self.active_handshake_pairs.clear()
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.last_move_payload = (999.0, 999.0)
        self.player_join_reported = False
        self.connection = ServerConnection(self.server_host, self.server_port, name, logger=self.debug_console.log)
        self.connection.start()
        self.connection_state = "connecting"
        self.connection_message = f"Connecting to {self.server_host}:{self.server_port}"

    def consume_network(self) -> None:
        if not self.connection:
            return
        for message in self.connection.poll():
            message_type = message.get("type")
            if message_type == "connection_state":
                state = message.get("state", "offline")
                self.connection_state = state
                if state == "error":
                    self.connection_message = message.get("message", "Connection error")
                    self.push_toast(self.connection_message)
                    self.debug_console.log("SOCKET", self.connection_message)
                else:
                    self.connection_message = "Connected"
            elif message_type == "welcome":
                self.self_id = message["self_id"]
                self.map_data = message["map"]
                self.scene = "world"
                self.connection_state = "online"
                self.connection_message = f"{self.server_host}:{self.server_port}"
                self.audio.set_scene("world")
                self.active_handshake_pairs.clear()
            elif message_type == "snapshot":
                self.apply_snapshot(message)
                self.maybe_report_player_join()
            elif message_type == "system":
                self.push_toast(message.get("message", ""))

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        seen_handshakes: set[tuple[str, str]] = set()
        logged_handshakes: set[tuple[str, str]] = set()
        incoming_ids: set[str] = set()
        for payload in snapshot.get("players", []):
            player_id = payload["id"]
            incoming_ids.add(player_id)
            previous = self.players.get(player_id)
            if player_id not in self.players:
                self.players[player_id] = PlayerView(
                    player_id=player_id,
                    name=payload["name"],
                    x=float(payload["x"]),
                    y=float(payload["y"]),
                    color=tuple(payload["color"]),
                    facing=payload["facing"],
                    glow_active=bool(payload["glow_active"]),
                    joy_duration=float(payload.get("joy_duration", 0.0)),
                    joy_remaining=float(payload.get("joy_remaining", 0.0)),
                    joy_seed=float(payload.get("joy_seed", 0.0)),
                    chat_text=payload.get("chat_text", ""),
                    chat_remaining=float(payload.get("chat_remaining", 0.0)),
                    handshake_active=bool(payload.get("handshake_active", False)),
                    handshake_duration=float(payload.get("handshake_duration", 0.0)),
                    handshake_remaining=float(payload.get("handshake_remaining", 0.0)),
                    handshake_partner_id=payload.get("handshake_partner_id", "") or "",
                    display_x=float(payload["x"]),
                    display_y=float(payload["y"]),
                )
                previous = None
            self.log_snapshot_event(previous, payload, logged_handshakes)
            self.players[player_id].absorb(payload)
            if payload.get("handshake_active") and payload.get("handshake_partner_id"):
                pair = tuple(sorted((player_id, str(payload.get("handshake_partner_id", "")))))
                if pair[0] and pair[1]:
                    seen_handshakes.add(pair)

        for player_id in list(self.players):
            if player_id not in incoming_ids:
                self.players.pop(player_id, None)
        self.active_handshake_pairs = seen_handshakes

    def update(self, dt: float) -> None:
        for toast in list(self.toasts):
            if time.time() - toast.created_at > toast.duration:
                self.toasts.remove(toast)

        if self.scene == "world":
            self.send_movement_if_needed()
            self.update_mouse_walk()
            self.update_camera(dt)

        for player_id, player in self.players.items():
            player.tick(dt, player_id == self.self_id)

    def send_movement_if_needed(self) -> None:
        if not self.connection or self.chat_mode:
            return
        keys = pygame.key.get_pressed()
        move_x = float(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - float(keys[pygame.K_a] or keys[pygame.K_LEFT])
        move_y = float(keys[pygame.K_s] or keys[pygame.K_DOWN]) - float(keys[pygame.K_w] or keys[pygame.K_UP])
        magnitude = math.hypot(move_x, move_y)
        if magnitude:
            move_x /= magnitude
            move_y /= magnitude

        payload = (round(move_x, 3), round(move_y, 3))
        if payload != self.last_move_payload:
            self.connection.send({"type": "move", "x": move_x, "y": move_y})
            self.last_move_payload = payload

    def update_camera(self, dt: float) -> None:
        local_player = self.players.get(self.self_id or "")
        if not local_player:
            return
        screen_w, screen_h = self.screen.get_size()
        target_x = local_player.display_x - screen_w * 0.5
        target_y = local_player.display_y - screen_h * 0.52
        if self.map_data:
            max_x = max(0, self.map_data["width"] - screen_w)
            max_y = max(0, self.map_data["height"] - screen_h)
            target_x = clamp(target_x, 0, max_x)
            target_y = clamp(target_y, 0, max_y)
        smoothing = 1 - math.pow(1 - CLIENT.camera_lerp, dt * 60)
        self.camera_x = lerp(self.camera_x, target_x, smoothing)
        self.camera_y = lerp(self.camera_y, target_y, smoothing)

    def update_mouse_facing(self, mouse_pos: tuple[int, int]) -> None:
        local_player = self.players.get(self.self_id or "")
        if not local_player or not self.connection:
            return
        world_x, world_y = self.screen_to_world(mouse_pos)
        facing = facing_from_vector(world_x - local_player.display_x, world_y - local_player.display_y, local_player.facing)
        if facing != self.last_mouse_facing:
            self.connection.send({"type": "turn", "facing": facing})
            self.last_mouse_facing = facing

    def update_mouse_walk(self) -> None:
        if not self.mouse_walk_active or not self.connection or self.chat_mode:
            return
        now = time.time()
        if now - self.last_mouse_walk_sent_at < CLIENT.move_send_interval:
            return
        world_x, world_y = self.screen_to_world(pygame.mouse.get_pos())
        if math.hypot(world_x - self.last_mouse_walk_target[0], world_y - self.last_mouse_walk_target[1]) < 5:
            return
        self.connection.send({"type": "click_move", "x": world_x, "y": world_y})
        self.last_mouse_walk_target = (world_x, world_y)
        self.last_mouse_walk_sent_at = now

    def player_nearby(self) -> bool:
        local_player = self.players.get(self.self_id or "")
        if not local_player:
            return False
        for player_id, player in self.players.items():
            if player_id == self.self_id:
                continue
            if math.hypot(player.x - local_player.x, player.y - local_player.y) <= SERVER.handshake_distance:
                return True
        return False

    def screen_to_world(self, point: tuple[int, int]) -> tuple[float, float]:
        return point[0] + self.camera_x, point[1] + self.camera_y

    def world_to_screen(self, point: tuple[float, float]) -> tuple[int, int]:
        return int(point[0] - self.camera_x), int(point[1] - self.camera_y)

    def push_toast(self, text: str) -> None:
        if text:
            self.toasts.insert(0, Toast(text=text, created_at=time.time()))

    def maybe_report_player_join(self) -> None:
        if self.player_join_reported or not self.self_id:
            return
        local_player = self.players.get(self.self_id)
        if not local_player:
            return
        self.player_join_reported = True
        online_count = max(1, len(self.players))
        self.debug_console.log("ENDPOINT", f"queue /player-join online={online_count}")
        threading.Thread(
            target=self._send_player_join,
            args=(local_player.name, online_count),
            daemon=True,
        ).start()

    def _send_player_join(self, nick: str, online_count: int) -> None:
        ok, error = self.endpoint.post_player_join(
            nick=nick,
            server_name=self.server_name or self.server_host,
            server_host=self.server_host,
            server_port=self.server_port,
            online=online_count,
        )
        if not ok and error:
            self.debug_console.log("ENDPOINT", f"/player-join failed {error}")

    def log_snapshot_event(
        self,
        previous: Optional[PlayerView],
        payload: dict[str, Any],
        logged_handshakes: set[tuple[str, str]],
    ) -> None:
        name = str(payload.get("name", "Player")).strip() or "Player"
        chat_text = str(payload.get("chat_text", "")).strip()
        if chat_text and (previous is None or previous.chat_text != chat_text):
            self.log_socket_snapshot_event(
                {
                    "type": "snapshot",
                    "event": "chat",
                    "player": name,
                    "text": chat_text[:72],
                }
            )

        glow_active = bool(payload.get("glow_active", False))
        if glow_active and (previous is None or not previous.glow_active):
            self.log_socket_snapshot_event(
                {
                    "type": "snapshot",
                    "event": "glow",
                    "player": name,
                    "glow_active": True,
                }
            )

        handshake_active = bool(payload.get("handshake_active", False))
        partner_id = str(payload.get("handshake_partner_id", "") or "")
        if handshake_active and partner_id:
            pair = tuple(sorted((str(payload.get("id", "")), partner_id)))
            if pair not in self.active_handshake_pairs and pair not in logged_handshakes:
                partner_name = self.players.get(partner_id).name if partner_id in self.players else "someone"
                self.log_socket_snapshot_event(
                    {
                        "type": "snapshot",
                        "event": "handshake",
                        "player": name,
                        "partner": partner_name,
                    }
                )
                logged_handshakes.add(pair)

    def log_socket_snapshot_event(self, payload: dict[str, Any]) -> None:
        self.debug_console.log("SOCKET", f"RESPONSE {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}")

    def login_button_rect(self) -> pygame.Rect:
        width, height = self.screen.get_size()
        return pygame.Rect(width // 2 - 100, height // 2 + 96, 200, 58)

    def shutdown(self) -> None:
        if self.connection:
            self.connection.close()
        self.audio.stop()
        pygame.quit()


def main() -> None:
    SkyroomClientApp().run()
