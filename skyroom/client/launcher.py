from __future__ import annotations

import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pygame

from ..config import CLIENT, ENDPOINT, NETWORK, SERVICE
from .chrome import create_window_icon, draw_custom_cursor
from .debug import DebugConsole
from .endpoint import EndpointClient, EndpointServerRecord
from .rendering import PALETTE, pick_font_name
from .servers import BrowserStateStore, ServerEntry, ServerStatusChecker, ServerStore, is_valid_host, is_valid_server_entry
from .state import add_alpha, blend


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVERS_PATH = PROJECT_ROOT / "servers.json"
BROWSER_STATE_PATH = PROJECT_ROOT / "server_browser_state.json"
LOCAL_SERVER_HOST = "127.0.0.1"
LOCAL_SERVER_NAME = "Local Skyroom"
ROLE_FLAG = "--skyroom-role"


@dataclass
class ManagedProcess:
    label: str
    process: subprocess.Popen[str]


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    action: Callable[[], None]
    enabled: bool = True

    def hit(self, pos: tuple[int, int]) -> bool:
        return self.enabled and self.rect.collidepoint(pos)


@dataclass
class DisplayedServer:
    server: ServerEntry
    local_index: Optional[int]
    from_endpoint: bool
    endpoint_status: bool
    is_new: bool
    is_localhost: bool = False

    @property
    def key(self) -> str:
        return self.server.key


@dataclass
class LauncherToast:
    text: str
    kind: str
    created_at: float
    duration: float = 3.4


class TextInput:
    def __init__(self, label: str, value: str = "", limit: int = 64, placeholder: str = "") -> None:
        self.label = label
        self.value = value
        self.limit = limit
        self.placeholder = placeholder or label
        self.active = False
        self.rect = pygame.Rect(0, 0, 1, 1)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.active = self.rect.collidepoint(event.pos)
            return self.active
        if event.type != pygame.KEYDOWN or not self.active:
            return False
        if event.key == pygame.K_BACKSPACE:
            self.value = self.value[:-1]
        elif event.key in (pygame.K_RETURN, pygame.K_TAB, pygame.K_ESCAPE):
            return False
        elif event.unicode.isprintable() and len(self.value) < self.limit:
            self.value += event.unicode
        return True


class ModalForm:
    def __init__(self, title: str, fields: list[TextInput], on_submit: Callable[[list[str]], None], submit_label: str) -> None:
        self.title = title
        self.fields = fields
        self.on_submit = on_submit
        self.submit_label = submit_label
        self.error = ""
        self.submit_rect = pygame.Rect(0, 0, 1, 1)
        self.cancel_rect = pygame.Rect(0, 0, 1, 1)
        if self.fields:
            self.fields[0].active = True

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return False
            if event.key == pygame.K_RETURN:
                self.submit()
                return True
            if event.key == pygame.K_TAB and self.fields:
                active_index = next((i for i, field in enumerate(self.fields) if field.active), 0)
                self.fields[active_index].active = False
                self.fields[(active_index + 1) % len(self.fields)].active = True
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.submit_rect.collidepoint(event.pos):
                self.submit()
                return True
            if self.cancel_rect.collidepoint(event.pos):
                return False
            clicked_field = False
            for field in self.fields:
                field.active = field.rect.collidepoint(event.pos)
                clicked_field = clicked_field or field.active
            if clicked_field:
                return True
        for field in self.fields:
            field.handle_event(event)
        return True

    def submit(self) -> None:
        self.error = ""
        self.on_submit([field.value.strip() for field in self.fields])


class SkyroomLauncherApp:
    def __init__(self) -> None:
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        pygame.init()
        pygame.font.init()
        pygame.display.set_caption("Skyroom")
        self.screen = pygame.display.set_mode((980, 640), pygame.RESIZABLE)
        pygame.display.set_icon(create_window_icon())
        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()
        self.font_name = pick_font_name()
        self.font_title = pygame.font.SysFont(self.font_name, 54, bold=True)
        self.font_heading = pygame.font.SysFont(self.font_name, 34, bold=True)
        self.font_ui = pygame.font.SysFont(self.font_name, 25)
        self.font_body = pygame.font.SysFont(self.font_name, 21)
        self.font_small = pygame.font.SysFont(self.font_name, 17)
        self.running = True
        self.scene = "main"
        self.status = ""
        self.modal: Optional[ModalForm] = None
        self.server_process: Optional[ManagedProcess] = None
        self.client_processes: list[ManagedProcess] = []
        self.client_counter = 0
        self.debug_console = DebugConsole()
        self.store = ServerStore(SERVERS_PATH)
        self.browser_state = BrowserStateStore(BROWSER_STATE_PATH)
        self.endpoint = EndpointClient(base_url=ENDPOINT.base_url, timeout=ENDPOINT.timeout, logger=self.debug_console.log)
        self.checker = ServerStatusChecker(logger=self.debug_console.log)
        self.endpoint_servers: list[EndpointServerRecord] = []
        self.new_endpoint_keys: set[str] = set()
        self.endpoint_loading = False
        self.endpoint_queue: "queue.Queue[tuple[bool, list[EndpointServerRecord], str]]" = queue.Queue()
        self.local_server_queue: "queue.Queue[tuple[str, int, bool, str]]" = queue.Queue()
        self.selected_server = 0
        self.signal_rects: list[tuple[pygame.Rect, DisplayedServer]] = []
        self.toasts: list[LauncherToast] = []
        self.context_menu_pos: Optional[tuple[int, int]] = None
        self.context_menu_kind: Optional[str] = None
        self.context_menu_index: Optional[int] = None
        self.last_click_index: Optional[int] = None
        self.last_click_at = 0.0
        self.cloud_phase = 0.0
        self.entry_reported = False
        self.local_server_autostarted = False
        rng = random.Random(time.time_ns())
        self.cloud_specs = [
            {
                "offset": rng.uniform(-200.0, 980.0),
                "y": rng.uniform(28.0, 540.0),
                "speed": rng.uniform(7.0, 18.0),
                "wobble": rng.uniform(5.0, 15.0),
                "scale": rng.uniform(0.68, 1.12),
                "drift": rng.uniform(120.0, 320.0),
                "phase": rng.uniform(0.0, math.tau),
            }
            for _ in range(9)
        ]

    def run(self) -> None:
        self.bootstrap_background_services()
        while self.running:
            dt = min(0.05, self.clock.tick(CLIENT.fps) / 1000.0)
            self.cloud_phase += dt
            self.cleanup_finished()
            self.update_toasts()
            self.consume_endpoint_results()
            self.consume_local_server_results()
            self.checker.tick([item.server for item in self.displayed_servers()])
            self.handle_events()
            self.draw()
        self.shutdown()

    def bootstrap_background_services(self) -> None:
        self.report_entry_once()
        self.autostart_local_server()

    def report_entry_once(self) -> None:
        if self.entry_reported:
            return
        self.entry_reported = True
        threading.Thread(target=self._send_entry_worker, daemon=True).start()

    def _send_entry_worker(self) -> None:
        self.endpoint.post_entry()

    def localhost_server_entry(self) -> ServerEntry:
        return ServerEntry(LOCAL_SERVER_NAME, LOCAL_SERVER_HOST, NETWORK.port)

    @staticmethod
    def runtime_command(role: str) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, ROLE_FLAG, role]
        script_name = "server.py" if role == "server" else "client.py"
        return [sys.executable, script_name]

    def local_server_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["SKYROOM_HOST"] = LOCAL_SERVER_HOST
        env["SKYROOM_PORT"] = str(NETWORK.port)
        env["SKYROOM_HEALTH_PORT"] = str(SERVICE.health_port)
        env["SKYROOM_SERVER_NAME"] = LOCAL_SERVER_NAME
        env.pop("SKYROOM_PUBLIC_HOST", None)
        env.pop("SKYROOM_PUBLIC_PORT", None)
        env.pop("SKYROOM_ENDPOINT_BASE_URL", None)
        env.pop("SKYROOM_CHECKUP_INTERVAL", None)
        return env

    def autostart_local_server(self) -> None:
        if self.local_server_autostarted:
            return
        self.local_server_autostarted = True
        self.start_server(auto=True)

    def main_menu_buttons(self) -> list[Button]:
        width, height = self.screen.get_size()
        button_w, button_h = 250, 58
        x = width // 2 - button_w // 2
        y = height // 2 - 62
        return [
            Button(pygame.Rect(x, y, button_w, button_h), "Online", self.open_online),
            Button(pygame.Rect(x, y + 76, button_w, button_h), "Offline", self.open_offline),
            Button(pygame.Rect(x, y + 152, button_w, button_h), "Exit", self.exit_app),
        ]

    def current_buttons(self) -> list[Button]:
        width, height = self.screen.get_size()
        if self.scene == "main":
            return self.main_menu_buttons()
        if self.scene == "offline":
            bottom = height - 96
            return [
                Button(pygame.Rect(56, bottom, 180, 54), "Start Server", self.start_server),
                Button(pygame.Rect(252, bottom, 180, 54), "New Client", lambda: self.start_client(server_name="Local Skyroom", ensure_local_server=True)),
                Button(pygame.Rect(width - 190, bottom, 134, 54), "Back", self.back_to_main),
            ]
        bottom = height - 88
        right = width - 56
        return [
            Button(pygame.Rect(56, bottom, 192, 52), "Direct Connect", self.open_direct_connect_modal),
            Button(pygame.Rect(264, bottom, 148, 52), "Add Server", self.open_add_modal),
            Button(pygame.Rect(right - 128, bottom, 128, 52), "Back", self.back_to_main),
        ]

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return
            if event.type == pygame.VIDEORESIZE:
                width = max(860, event.w)
                height = max(560, event.h)
                self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
                continue
            if self.debug_console.handle_event(event, self.screen.get_size()):
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_d and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                self.debug_console.toggle()
                continue
            if self.modal:
                keep_modal = self.modal.handle_event(event)
                if not keep_modal:
                    self.modal = None
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if self.scene == "main":
                    self.running = False
                else:
                    self.scene = "main"
                self.context_menu_kind = None
                continue
            if event.type == pygame.KEYDOWN and self.scene == "offline" and event.key == pygame.K_x:
                self.start_client(server_name="Local Skyroom", ensure_local_server=True)
                continue
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 3 and self.scene == "online":
                    self.open_context_menu_at(event.pos)
                    continue
                if event.button != 1:
                    continue
                if self.context_menu_kind and self.handle_context_menu_click(event.pos):
                    continue
                self.context_menu_kind = None
                for button in self.current_buttons():
                    if button.hit(event.pos):
                        button.action()
                        return
                if self.scene == "online":
                    self.handle_server_left_click(event.pos)

    def displayed_servers(self) -> list[DisplayedServer]:
        combined: dict[str, DisplayedServer] = {}
        localhost_server = self.localhost_server_entry()
        localhost_index = next(
            (
                index
                for index, local_server in enumerate(self.store.servers)
                if local_server.host.strip().lower() == localhost_server.host.lower() and local_server.port == localhost_server.port
            ),
            None,
        )
        combined[localhost_server.key] = DisplayedServer(
            server=localhost_server,
            local_index=localhost_index,
            from_endpoint=False,
            endpoint_status=False,
            is_new=False,
            is_localhost=True,
        )
        for record in self.endpoint_servers:
            key = record.key
            if key not in combined:
                combined[key] = DisplayedServer(
                    server=ServerEntry(record.server_name[:32], record.server_host[:128], record.server_port),
                    local_index=None,
                    from_endpoint=True,
                    endpoint_status=record.status,
                    is_new=key in self.new_endpoint_keys,
                )
        for index, local_server in enumerate(self.store.servers):
            key = local_server.key
            if key in combined:
                combined[key].local_index = index
                continue
            combined[key] = DisplayedServer(local_server, index, False, False, False)
        localhost_item = combined.pop(localhost_server.key)
        sorted_items = sorted(
            combined.values(),
            key=lambda item: (
                -(self.checker.get(item.server).online_count or 0),
                -int(self.checker.get(item.server).online),
                item.server.name.lower(),
                item.server.host.lower(),
                item.server.port,
            ),
        )
        return [localhost_item, *sorted_items]

    def consume_endpoint_results(self) -> None:
        while True:
            try:
                ok, servers, error = self.endpoint_queue.get_nowait()
            except queue.Empty:
                return
            self.endpoint_loading = False
            if not ok:
                self.status = f"Endpoint unavailable: {error or 'failed to fetch /servers'}"
                continue
            previous_seen = set(self.browser_state.seen_endpoint_keys)
            self.endpoint_servers = [
                server
                for server in servers
                if is_valid_server_entry(server.server_host, server.server_port)
            ]
            self.new_endpoint_keys = {
                server.key
                for server in self.endpoint_servers
                if server.key not in previous_seen and not self.exists_in_local_store(server.server_host, server.server_port)
            }
            self.browser_state.mark_seen(server.key for server in self.endpoint_servers)
            self.status = f"Loaded {len(self.endpoint_servers)} servers from endpoint."

    def cleanup_finished(self) -> None:
        self.client_processes = [proc for proc in self.client_processes if proc.process.poll() is None]
        if self.server_process and self.server_process.process.poll() is not None:
            self.server_process = None

    def consume_local_server_results(self) -> None:
        while True:
            try:
                state, pid, auto, message = self.local_server_queue.get_nowait()
            except queue.Empty:
                return
            if self.server_process and self.server_process.process.pid == pid and state in {"already_running", "failed"}:
                self.server_process = None
            self.checker.refresh_now([self.localhost_server_entry()])
            self.status = message
            if state == "started":
                self.debug_console.log("LOCALHOST", "->", message, "LOCAL", "INFO")
            elif state == "already_running":
                self.debug_console.log("LOCALHOST", "->", message, "LOCAL", "WARN")
            else:
                self.debug_console.log("LOCALHOST", "->", message, "LOCAL", "ERROR")
            if not auto and state != "started":
                self.push_toast(message, kind="error" if state == "failed" else "info")

    def update_toasts(self) -> None:
        now = time.time()
        self.toasts = [toast for toast in self.toasts if now - toast.created_at <= toast.duration]

    def push_toast(self, text: str, kind: str = "info") -> None:
        if not text:
            return
        self.toasts.insert(0, LauncherToast(text=text, kind=kind, created_at=time.time()))
        self.toasts = self.toasts[:3]

    def shutdown(self) -> None:
        for client in self.client_processes:
            if client.process.poll() is None:
                client.process.terminate()
        if self.server_process and self.server_process.process.poll() is None:
            self.server_process.process.terminate()
        pygame.quit()

    def back_to_main(self) -> None:
        self.scene = "main"
        self.context_menu_kind = None
        self.status = ""

    def start_server(self, *, auto: bool = False) -> None:
        if self.server_process and self.server_process.process.poll() is None:
            self.status = "Local server is already running."
            self.debug_console.log("LOCALHOST", "->", "Local server is already running.", "LOCAL", "INFO")
            return
        self.debug_console.log("LOCALHOST", "<-", f"Launch local server {LOCAL_SERVER_HOST}:{NETWORK.port}", "LOCAL", "INFO")
        try:
            process = subprocess.Popen(self.runtime_command("server"), cwd=PROJECT_ROOT, env=self.local_server_env())
        except OSError as exc:
            message = f"Local server launch failed: {exc}"
            self.status = message
            self.debug_console.log("LOCALHOST", "->", message, "LOCAL", "ERROR")
            if not auto:
                self.push_toast("Local server is unavailable.", kind="error")
            return
        self.server_process = ManagedProcess("server", process)
        self.status = "Starting local server..."
        threading.Thread(
            target=self._verify_local_server_start,
            args=(process.pid, auto),
            daemon=True,
        ).start()

    def _verify_local_server_start(self, pid: int, auto: bool) -> None:
        time.sleep(0.8)
        managed = self.server_process
        if not managed or managed.process.pid != pid:
            return
        if managed.process.poll() is None:
            self.local_server_queue.put(("started", pid, auto, "Local server is running on localhost."))
            return
        result = self.checker.check_once(self.localhost_server_entry())
        if result.online:
            self.local_server_queue.put(("already_running", pid, auto, "Local server is already available on localhost."))
        else:
            self.local_server_queue.put(("failed", pid, auto, "Local server is unavailable or the port is busy."))

    def start_client(
        self,
        host: str = NETWORK.host,
        port: int = NETWORK.port,
        server_name: str = "",
        ensure_local_server: bool = False,
    ) -> None:
        if ensure_local_server and (not self.server_process or self.server_process.process.poll() is not None):
            self.start_server()
        self.client_counter += 1
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["SKYROOM_HOST"] = host
        env["SKYROOM_PORT"] = str(port)
        if server_name:
            env["SKYROOM_SERVER_NAME"] = server_name
        process = subprocess.Popen(self.runtime_command("client"), cwd=PROJECT_ROOT, env=env)
        self.client_processes.append(ManagedProcess(f"client-{self.client_counter}", process))
        self.status = f"Opened client for {host}:{port}."

    def fetch_endpoint_servers_async(self) -> None:
        if self.endpoint_loading:
            return
        self.endpoint_loading = True
        threading.Thread(target=self._fetch_endpoint_servers_worker, daemon=True).start()

    def _fetch_endpoint_servers_worker(self) -> None:
        ok, servers, error = self.endpoint.fetch_servers()
        self.endpoint_queue.put((ok, servers, error))

    def exists_in_local_store(self, host: str, port: int) -> bool:
        return any(server.host.strip().lower() == host.strip().lower() and server.port == port for server in self.store.servers)

    def refresh_all_servers(self) -> None:
        displayed = self.displayed_servers()
        self.checker.refresh_now([item.server for item in displayed])
        self.status = f"Refreshing {len(displayed)} visible servers..."

    def open_direct_connect_modal(self) -> None:
        self.modal = ModalForm(
            "Direct Connect",
            [
                TextInput("Host / IP", "", placeholder="127.0.0.1 or play.example.com"),
                TextInput("Port", "", limit=5, placeholder="8765"),
            ],
            self.submit_direct_connect,
            "Connect",
        )

    def open_add_modal(self) -> None:
        self.modal = ModalForm(
            "Add Server",
            [
                TextInput("Name", "", placeholder="My Skyroom"),
                TextInput("Host / IP", "", placeholder="127.0.0.1 or play.example.com"),
                TextInput("Port", "", limit=5, placeholder="8765"),
            ],
            self.submit_add_server,
            "Save",
        )

    def open_edit_modal(self) -> None:
        item = self.get_selected_item()
        if not item or item.local_index is None:
            return
        selected = self.store.servers[item.local_index]
        self.modal = ModalForm(
            "Edit Server",
            [
                TextInput("Name", selected.name),
                TextInput("Host / IP", selected.host),
                TextInput("Port", str(selected.port), limit=5),
            ],
            self.submit_edit_server,
            "Save",
        )

    def submit_direct_connect(self, values: list[str]) -> None:
        server = self.parse_server_values(["Direct", values[0], values[1]])
        if not server:
            return
        self.modal = None
        self.connect_to_server(server)

    def submit_add_server(self, values: list[str]) -> None:
        server = self.parse_server_values(values)
        if not server:
            return
        duplicate = self.find_duplicate_server(server)
        if duplicate:
            self.set_modal_error(f"That server already exists as {duplicate.server.name}.")
            return
        self.store.add(server)
        self.modal = None
        self.status = f"Saved {server.name}."
        self.refresh_all_servers()

    def submit_edit_server(self, values: list[str]) -> None:
        item = self.get_selected_item()
        if not item or item.local_index is None:
            return
        server = self.parse_server_values(values)
        if not server:
            return
        duplicate = self.find_duplicate_server(server, skip_local_index=item.local_index)
        if duplicate:
            self.set_modal_error(f"That server already exists as {duplicate.server.name}.")
            return
        self.store.update(item.local_index, server)
        self.modal = None
        self.status = f"Updated {server.name}."
        self.refresh_all_servers()

    def parse_server_values(self, values: list[str]) -> Optional[ServerEntry]:
        name, host, port_text = values
        name = name.strip() or "Skyroom Server"
        host = host.strip()
        if not host:
            self.set_modal_error("Host is required.")
            return None
        if not is_valid_host(host):
            self.set_modal_error("Enter a valid IPv4 address, localhost, or domain.")
            return None
        try:
            port = int(port_text)
        except ValueError:
            self.set_modal_error("Port must be a number.")
            return None
        if not 1 <= port <= 65535:
            self.set_modal_error("Port must be between 1 and 65535.")
            return None
        return ServerEntry(name=name[:32], host=host[:128], port=port)

    def find_duplicate_server(self, server: ServerEntry, skip_local_index: Optional[int] = None) -> Optional[DisplayedServer]:
        normalized_host = server.host.strip().lower()
        for item in self.displayed_servers():
            if skip_local_index is not None and item.local_index == skip_local_index:
                continue
            if item.server.host.strip().lower() == normalized_host and item.server.port == server.port:
                return item
        return None

    def set_modal_error(self, text: str) -> None:
        if self.modal:
            self.modal.error = text

    def remove_selected_server(self) -> None:
        item = self.get_selected_item()
        if not item or item.local_index is None:
            self.status = "Only locally saved servers can be removed."
            return
        removed = self.store.servers[item.local_index]
        self.store.remove(item.local_index)
        self.selected_server = max(0, min(self.selected_server, len(self.displayed_servers()) - 1))
        self.context_menu_kind = None
        self.status = f"Removed {removed.name}."

    def connect_selected_server(self) -> None:
        item = self.get_selected_item()
        if item:
            self.connect_to_server(item.server)

    def connect_to_server(self, server: ServerEntry) -> None:
        self.status = f"Checking {server.host}:{server.port}..."
        self.draw()
        try:
            result = self.checker.check_once(server)
        except Exception as exc:
            self.status = ""
            if self.debug_console:
                self.debug_console.log(
                    "SERVER",
                    "->",
                    f"http://{server.host}:{SERVICE.health_port}/health ERROR unexpected {exc}",
                    "GET",
                    "ERROR",
                )
            self.push_toast(f"{server.name} is offline or unreachable.", kind="error")
            return
        if not result.online:
            self.status = ""
            self.push_toast(f"{server.name} is offline or unreachable.", kind="error")
            return
        self.start_client(server.host, server.port, server_name=result.server_name or server.name)

    def get_selected_item(self) -> Optional[DisplayedServer]:
        displayed = self.displayed_servers()
        if not displayed:
            return None
        self.selected_server = max(0, min(self.selected_server, len(displayed) - 1))
        return displayed[self.selected_server]

    def handle_server_left_click(self, pos: tuple[int, int]) -> None:
        index = self.server_index_at(pos)
        if index is None:
            return
        now = time.time()
        is_double_click = self.last_click_index == index and now - self.last_click_at <= 0.35
        self.selected_server = index
        self.last_click_index = index
        self.last_click_at = now
        if is_double_click:
            self.connect_selected_server()

    def open_context_menu_at(self, pos: tuple[int, int]) -> None:
        index = self.server_index_at(pos)
        self.context_menu_pos = pos
        self.context_menu_index = index
        self.context_menu_kind = "server" if index is not None else "global"
        if index is not None:
            self.selected_server = index

    def handle_context_menu_click(self, pos: tuple[int, int]) -> bool:
        for button in self.context_menu_buttons():
            if button.hit(pos):
                button.action()
                self.context_menu_kind = None
                return True
        return False

    def server_index_at(self, pos: tuple[int, int]) -> Optional[int]:
        width, height = self.screen.get_size()
        list_rect = pygame.Rect(56, 150, width - 112, max(220, height - 260))
        row_h = 74
        for index, _item in enumerate(self.displayed_servers()[: max(0, list_rect.height // row_h)]):
            row = pygame.Rect(list_rect.x + 12, list_rect.y + 12 + index * row_h, list_rect.width - 24, 62)
            if row.collidepoint(pos):
                return index
        return None

    def context_menu_buttons(self) -> list[Button]:
        if self.context_menu_kind is None or self.context_menu_pos is None:
            return []
        x, y = self.context_menu_pos
        width, height = self.screen.get_size()
        menu_w = 184
        x = min(x, width - menu_w - 14)
        if self.context_menu_kind == "global":
            y = min(y, height - 60 - 14)
            return [Button(pygame.Rect(x + 10, y + 10, menu_w - 20, 34), "Refresh All", self.refresh_all_servers)]
        item = self.get_selected_item()
        if not item:
            return []
        y = min(y, height - 138 - 14)
        return [
            Button(pygame.Rect(x + 10, y + 10, menu_w - 20, 34), "Connect", self.connect_selected_server),
            Button(pygame.Rect(x + 10, y + 52, menu_w - 20, 34), "Edit", self.open_edit_modal, item.local_index is not None),
            Button(pygame.Rect(x + 10, y + 94, menu_w - 20, 34), "Remove", self.remove_selected_server, item.local_index is not None),
        ]

    def open_online(self) -> None:
        self.scene = "online"
        self.context_menu_kind = None
        self.status = "Loading servers from endpoint..."
        self.fetch_endpoint_servers_async()
        self.refresh_all_servers()

    def open_offline(self) -> None:
        self.scene = "offline"
        if not self.server_process:
            self.start_server()
        if not self.client_processes:
            self.start_client(server_name="Local Skyroom", ensure_local_server=True)

    def exit_app(self) -> None:
        self.running = False

    def draw(self) -> None:
        self.draw_background()
        if self.scene == "main":
            self.draw_main_menu()
        elif self.scene == "offline":
            self.draw_offline()
        else:
            self.draw_online()
        if self.modal:
            self.draw_modal()
        self.draw_toasts()
        self.debug_console.draw(self.screen)
        draw_custom_cursor(self.screen, pygame.mouse.get_pos(), self.cloud_phase)
        pygame.display.flip()

    def draw_background(self) -> None:
        width, height = self.screen.get_size()
        for y in range(height):
            t = y / max(1, height - 1)
            pygame.draw.line(self.screen, blend(PALETTE["bg_top"], PALETTE["bg_bottom"], t), (0, y), (width, y))
        for spec in self.cloud_specs:
            span = width + spec["drift"] + 240.0
            offset = (spec["offset"] + self.cloud_phase * spec["speed"]) % span - 170.0
            cloud_y = spec["y"] + math.sin(self.cloud_phase * 0.6 + spec["phase"]) * spec["wobble"]
            self.draw_cloud(int(offset), int(cloud_y), spec["scale"])

    def draw_cloud(self, x: int, y: int, scale: float) -> None:
        surface = pygame.Surface((220, 110), pygame.SRCALPHA)
        cloud_color = (255, 255, 255, 68)
        for cx, cy, radius in ((58, 58, 34), (96, 42, 42), (136, 54, 38), (170, 60, 26)):
            pygame.draw.circle(surface, cloud_color, (int(cx * scale), int(cy * scale)), int(radius * scale))
        self.screen.blit(surface, (x, y))

    def draw_main_menu(self) -> None:
        width, height = self.screen.get_size()
        panel = pygame.Rect(width // 2 - 285, height // 2 - 220, 570, 440)
        self.draw_shadowed_panel(panel, 232)
        title = self.font_title.render("Skyroom", True, PALETTE["text"])
        subtitle = self.font_body.render("Jews rule. Crème de la crème", True, PALETTE["muted"])
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 72)))
        self.screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + 118)))
        for button in self.main_menu_buttons():
            self.draw_glossy_button(button)

    def draw_offline(self) -> None:
        width, height = self.screen.get_size()
        header = pygame.Rect(42, 36, width - 84, 112)
        self.draw_shadowed_panel(header, 224)
        title = self.font_heading.render("Offline", True, PALETTE["text"])
        subtitle = self.font_body.render("Jews rule", True, PALETTE["muted"])
        self.screen.blit(title, (header.x + 26, header.y + 22))
        self.screen.blit(subtitle, (header.x + 26, header.y + 62))

        panel = pygame.Rect(56, 180, width - 112, max(230, height - 310))
        self.draw_shadowed_panel(panel, 218)
        lines = [
            f"Server: {'running' if self.server_process else 'stopped'}",
            f"Client windows: {len(self.client_processes)} active",
            "Offline starts a local server and opens the client against 127.0.0.1.",
            "Use New Client or press X for another local player window.",
        ]
        for index, line in enumerate(lines):
            color = PALETTE["text"] if index < 2 else PALETTE["muted"]
            rendered = self.font_body.render(line, True, color)
            self.screen.blit(rendered, (panel.x + 30, panel.y + 36 + index * 42))

        for button in self.current_buttons():
            self.draw_glossy_button(button)
        self.draw_status_line(height - 26)

    def draw_online(self) -> None:
        width, height = self.screen.get_size()
        self.signal_rects = []
        header = pygame.Rect(42, 34, width - 84, 96)
        self.draw_shadowed_panel(header, 224)
        title = self.font_heading.render("Online", True, PALETTE["text"])
        subtitle = self.font_body.render("Jews rule", True, PALETTE["muted"])
        self.screen.blit(title, (header.x + 26, header.y + 20))
        self.screen.blit(subtitle, (header.x + 26, header.y + 56))

        list_rect = pygame.Rect(56, 150, width - 112, max(220, height - 260))
        self.draw_shadowed_panel(list_rect, 216)
        displayed = self.displayed_servers()
        if not displayed:
            empty = self.font_body.render("No servers yet.", True, PALETTE["muted"])
            helper = self.font_small.render("Add one or use Direct Connect.", True, PALETTE["muted"])
            self.screen.blit(empty, empty.get_rect(center=(list_rect.centerx, list_rect.centery - 12)))
            self.screen.blit(helper, helper.get_rect(center=(list_rect.centerx, list_rect.centery + 18)))
        else:
            self.draw_server_rows(list_rect, displayed)

        for button in self.current_buttons():
            self.draw_glossy_button(button)
        self.draw_context_menu()
        self.draw_hover_tooltip()
        self.draw_status_line(height - 26)

    def draw_server_rows(self, list_rect: pygame.Rect, displayed: list[DisplayedServer]) -> None:
        row_h = 74
        max_rows = max(0, list_rect.height // row_h)
        for index, item in enumerate(displayed[:max_rows]):
            row = pygame.Rect(list_rect.x + 12, list_rect.y + 12 + index * row_h, list_rect.width - 24, 62)
            selected = index == self.selected_server
            fill = (255, 255, 255, 235) if selected else (248, 252, 255, 200)
            pygame.draw.rect(self.screen, fill, row, border_radius=22)
            pygame.draw.rect(self.screen, add_alpha(PALETTE["outline"], 240), row, width=2, border_radius=22)

            dot_offset = 0
            if item.is_new:
                marker_center = (row.x + 24, row.centery)
                pygame.draw.circle(self.screen, (250, 232, 156), marker_center, 6)
                pygame.draw.circle(self.screen, (255, 248, 220), marker_center, 6, width=1)
                dot_offset = 18

            health = self.checker.get(item.server)
            name = self.truncate(health.server_name or item.server.name, self.font_ui, row.width - 290)
            host = self.truncate(f"{item.server.host}:{item.server.port}", self.font_small, row.width - 290)
            name_x = row.x + 22 + dot_offset
            name_y = row.y + 10
            name_surface = self.font_ui.render(name, True, PALETTE["text"])
            self.screen.blit(name_surface, (name_x, name_y))
            if item.is_localhost:
                self.draw_localhost_badge(name_x + name_surface.get_width() + 12, row.y + 13)
            self.screen.blit(self.font_small.render(host, True, PALETTE["muted"]), (row.x + 22 + dot_offset, row.y + 39))

            if health.online_count is not None:
                online_label = self.font_small.render(f"{health.online_count} online", True, PALETTE["muted"])
                self.screen.blit(online_label, online_label.get_rect(right=row.right - 96, centery=row.centery))

            signal_rect = pygame.Rect(row.right - 82, row.y + 17, 46, 32)
            self.signal_rects.append((signal_rect, item))
            self.draw_signal_indicator(signal_rect, health)

    def draw_signal_indicator(self, rect: pygame.Rect, result) -> None:
        bars = result.bars
        inactive = (185, 199, 218, 125)
        active_colors = {
            1: (255, 203, 162, 235),
            2: (255, 228, 145, 235),
            3: (143, 224, 197, 240),
        }
        for index, height in enumerate((10, 18, 27), start=1):
            bar = pygame.Rect(rect.x + (index - 1) * 13, rect.bottom - height, 9, height)
            color = active_colors.get(bars, inactive) if index <= bars else inactive
            pygame.draw.rect(self.screen, color, bar, border_radius=5)
            pygame.draw.rect(self.screen, (255, 255, 255, 150), bar, width=1, border_radius=5)

    def draw_localhost_badge(self, x: int, y: int) -> None:
        label = self.font_small.render("localhost", True, PALETTE["muted"])
        badge = label.get_rect(topleft=(x, y)).inflate(16, 8)
        pill = pygame.Surface(badge.size, pygame.SRCALPHA)
        pygame.draw.rect(pill, (246, 250, 255, 208), pill.get_rect(), border_radius=14)
        pygame.draw.rect(pill, add_alpha(PALETTE["outline"], 230), pill.get_rect(), width=1, border_radius=14)
        self.screen.blit(pill, badge.topleft)
        self.screen.blit(label, label.get_rect(center=badge.center))

    def draw_hover_tooltip(self) -> None:
        mouse = pygame.mouse.get_pos()
        for rect, item in self.signal_rects:
            if not rect.collidepoint(mouse):
                continue
            result = self.checker.get(item.server)
            if result.online and result.ping_ms is not None:
                text = f"Ping: {result.ping_ms} ms"
                if result.online_count is not None:
                    text += f" | Online: {result.online_count}"
            else:
                text = "Offline"
            label = self.font_small.render(text, True, PALETTE["text"])
            tooltip = label.get_rect()
            tooltip.width += 30
            tooltip.height += 22
            tooltip.x = min(mouse[0] + 18, self.screen.get_width() - tooltip.width - 14)
            tooltip.y = max(14, mouse[1] - tooltip.height - 12)
            shadow = pygame.Surface((tooltip.width + 16, tooltip.height + 16), pygame.SRCALPHA)
            pygame.draw.rect(shadow, (111, 152, 211, 38), (8, 8, tooltip.width, tooltip.height), border_radius=18)
            self.screen.blit(shadow, (tooltip.x - 8, tooltip.y - 4))
            pygame.draw.rect(self.screen, (255, 255, 255, 238), tooltip, border_radius=18)
            pygame.draw.rect(self.screen, add_alpha(PALETTE["outline"], 245), tooltip, width=2, border_radius=18)
            self.screen.blit(label, label.get_rect(center=tooltip.center))
            return

    def draw_context_menu(self) -> None:
        buttons = self.context_menu_buttons()
        if not buttons or self.context_menu_pos is None:
            return
        x, y = self.context_menu_pos
        width = max(button.rect.width for button in buttons) + 20
        height = (buttons[-1].rect.bottom - buttons[0].rect.y) + 20
        panel = pygame.Rect(buttons[0].rect.x - 10, buttons[0].rect.y - 10, width, height)
        self.draw_shadowed_panel(panel, 238, radius=18, shadow_alpha=34)
        for button in buttons:
            self.draw_context_button(button)

    def draw_context_button(self, button: Button) -> None:
        mouse = pygame.mouse.get_pos()
        hovered = button.enabled and button.rect.collidepoint(mouse)
        if button.enabled:
            fill = (247, 251, 255, 242) if hovered else (242, 248, 255, 226)
            text_color = PALETTE["text"]
        else:
            fill = (239, 243, 249, 150)
            text_color = PALETTE["muted"]
        pygame.draw.rect(self.screen, fill, button.rect, border_radius=14)
        pygame.draw.rect(self.screen, add_alpha(PALETTE["outline"], 220), button.rect, width=1, border_radius=14)
        label = self.font_small.render(button.label, True, text_color)
        self.screen.blit(label, label.get_rect(center=button.rect.center))

    def draw_modal(self) -> None:
        if not self.modal:
            return
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((27, 40, 68, 68))
        self.screen.blit(overlay, (0, 0))

        width, height = self.screen.get_size()
        field_count = len(self.modal.fields)
        panel_h = 248 if field_count <= 2 else 296
        panel = pygame.Rect(width // 2 - 248, height // 2 - panel_h // 2, 496, panel_h)
        self.draw_shadowed_panel(panel, 244, radius=28, shadow_alpha=42)

        title = self.font_heading.render(self.modal.title, True, PALETTE["text"])
        self.screen.blit(title, (panel.x + 28, panel.y + 22))

        if field_count == 2:
            host_rect = pygame.Rect(panel.x + 28, panel.y + 98, 316, 54)
            port_rect = pygame.Rect(host_rect.right + 14, host_rect.y, panel.right - host_rect.right - 42, 54)
            self.draw_modal_field(self.modal.fields[0], host_rect)
            self.draw_modal_field(self.modal.fields[1], port_rect)
        elif field_count >= 3:
            self.draw_modal_field(self.modal.fields[0], pygame.Rect(panel.x + 28, panel.y + 78, panel.width - 56, 54))
            host_rect = pygame.Rect(panel.x + 28, panel.y + 150, 316, 54)
            port_rect = pygame.Rect(host_rect.right + 14, host_rect.y, panel.right - host_rect.right - 42, 54)
            self.draw_modal_field(self.modal.fields[1], host_rect)
            self.draw_modal_field(self.modal.fields[2], port_rect)

        error_y = panel.bottom - 94
        if self.modal.error:
            error = self.font_small.render(self.modal.error, True, (183, 95, 116))
            self.screen.blit(error, (panel.x + 30, error_y))

        self.modal.cancel_rect = pygame.Rect(panel.right - 160, panel.bottom - 66, 108, 42)
        self.modal.submit_rect = pygame.Rect(panel.right - 278, panel.bottom - 66, 108, 42)
        self.draw_glossy_button(Button(self.modal.submit_rect, self.modal.submit_label, self.modal.submit))
        self.draw_glossy_button(Button(self.modal.cancel_rect, "Cancel", lambda: None))

    def draw_modal_field(self, field: TextInput, rect: pygame.Rect) -> None:
        field.rect = rect
        label = self.font_small.render(field.label, True, PALETTE["muted"])
        self.screen.blit(label, (rect.x + 4, rect.y - 22))

        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        base_fill = (255, 255, 255, 242) if field.active else (249, 252, 255, 214)
        pygame.draw.rect(surface, base_fill, surface.get_rect(), border_radius=18)
        pygame.draw.rect(
            surface,
            add_alpha(PALETTE["accent"], 240) if field.active else add_alpha(PALETTE["outline"], 220),
            surface.get_rect(),
            width=2,
            border_radius=18,
        )
        self.screen.blit(surface, rect.topleft)

        text_value = field.value or field.placeholder
        text_color = PALETTE["text"] if field.value else (155, 168, 188)
        rendered = self.font_body.render(text_value, True, text_color)
        self.screen.blit(rendered, rendered.get_rect(midleft=(rect.x + 18, rect.centery)))

    def draw_status_line(self, y: int) -> None:
        if not self.status:
            return
        width = self.screen.get_width() - 112
        status = self.truncate(self.status, self.font_small, width)
        label = self.font_small.render(status, True, PALETTE["muted"])
        self.screen.blit(label, (56, y))

    def draw_toasts(self) -> None:
        if not self.toasts:
            return
        right = self.screen.get_width() - 24
        top = 24
        for index, toast in enumerate(self.toasts[:3]):
            age = time.time() - toast.created_at
            fade = 1.0 if age < toast.duration - 0.45 else max(0.0, (toast.duration - age) / 0.45)
            width = 360
            height = 64
            rect = pygame.Rect(right - width, top + index * 76, width, height)
            self.draw_toast(rect, toast, fade)

    def draw_toast(self, rect: pygame.Rect, toast: LauncherToast, fade: float) -> None:
        if toast.kind == "error":
            fill = (255, 237, 241, int(232 * fade))
            outline = (239, 192, 201, int(246 * fade))
            icon_fill = (235, 162, 176, int(230 * fade))
            icon_fg = (255, 250, 252, int(250 * fade))
            text_color = (126, 85, 100)
        else:
            fill = (246, 250, 255, int(228 * fade))
            outline = (214, 228, 244, int(240 * fade))
            icon_fill = (172, 203, 235, int(226 * fade))
            icon_fg = (255, 255, 255, int(248 * fade))
            text_color = PALETTE["text"]

        shadow = pygame.Surface((rect.width + 18, rect.height + 18), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (100, 122, 158, int(24 * fade)), (9, 10, rect.width, rect.height), border_radius=22)
        self.screen.blit(shadow, (rect.x - 9, rect.y - 6))

        card = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(card, fill, card.get_rect(), border_radius=22)
        pygame.draw.rect(card, outline, card.get_rect(), width=2, border_radius=22)
        self.screen.blit(card, rect.topleft)

        icon_center = (rect.x + 34, rect.centery)
        pygame.draw.circle(self.screen, icon_fill, icon_center, 14)
        pygame.draw.circle(self.screen, outline, icon_center, 14, width=1)
        pygame.draw.line(self.screen, icon_fg, (icon_center[0] - 4, icon_center[1] - 4), (icon_center[0] + 4, icon_center[1] + 4), 2)
        pygame.draw.line(self.screen, icon_fg, (icon_center[0] + 4, icon_center[1] - 4), (icon_center[0] - 4, icon_center[1] + 4), 2)

        text = self.truncate(toast.text, self.font_small, rect.width - 74)
        label = self.font_small.render(text, True, text_color)
        self.screen.blit(label, label.get_rect(midleft=(rect.x + 58, rect.centery)))

    def draw_shadowed_panel(
        self,
        rect: pygame.Rect,
        fill_alpha: int,
        radius: int = 30,
        shadow_alpha: int = 28,
    ) -> None:
        shadow = pygame.Surface((rect.width + 26, rect.height + 26), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (114, 146, 203, shadow_alpha), (12, 14, rect.width, rect.height), border_radius=radius + 10)
        self.screen.blit(shadow, (rect.x - 12, rect.y - 10))

        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(panel, (255, 255, 255, fill_alpha), panel.get_rect(), border_radius=radius)
        pygame.draw.rect(panel, add_alpha(PALETTE["outline"], 230), panel.get_rect(), width=2, border_radius=radius)
        self.screen.blit(panel, rect.topleft)

    def draw_glossy_button(self, button: Button) -> None:
        mouse = pygame.mouse.get_pos()
        hovered = button.enabled and button.rect.collidepoint(mouse)
        pressed = hovered and pygame.mouse.get_pressed()[0]
        if button.enabled:
            fill = PALETTE["accent"] if hovered else PALETTE["panel"]
            text_color = PALETTE["text"]
        else:
            fill = (225, 232, 242)
            text_color = PALETTE["muted"]

        surface = pygame.Surface(button.rect.size, pygame.SRCALPHA)
        pygame.draw.rect(surface, add_alpha(fill, 236), surface.get_rect(), border_radius=20)
        pygame.draw.rect(surface, add_alpha(PALETTE["outline"], 240), surface.get_rect(), width=2, border_radius=20)
        if pressed:
            pygame.draw.rect(surface, (255, 255, 255, 18), surface.get_rect(), border_radius=20)
        self.screen.blit(surface, button.rect.topleft)

        label = self.font_body.render(button.label, True, text_color)
        self.screen.blit(label, label.get_rect(center=button.rect.center))

    @staticmethod
    def truncate(text: str, font: pygame.font.Font, max_width: int) -> str:
        if font.size(text)[0] <= max_width:
            return text
        clipped = text
        while clipped and font.size(clipped + "...")[0] > max_width:
            clipped = clipped[:-1]
        return clipped + "..." if clipped else "..."


def main() -> None:
    SkyroomLauncherApp().run()
