from __future__ import annotations

import math
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import pygame

from ..config import CLIENT, NETWORK
from .chrome import create_window_icon, draw_custom_cursor
from .rendering import PALETTE, pick_font_name
from .servers import ServerEntry, ServerStatusChecker, ServerStore
from .state import add_alpha, blend


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVERS_PATH = PROJECT_ROOT / "servers.json"


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
    def __init__(
        self,
        title: str,
        fields: list[TextInput],
        on_submit: Callable[[list[str]], None],
        submit_label: str,
    ) -> None:
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
        self.status = "Choose a mode."
        self.modal: Optional[ModalForm] = None
        self.server_process: Optional[ManagedProcess] = None
        self.client_processes: List[ManagedProcess] = []
        self.client_counter = 0
        self.store = ServerStore(SERVERS_PATH)
        self.checker = ServerStatusChecker()
        self.selected_server = 0
        self.signal_rects: list[tuple[pygame.Rect, ServerEntry]] = []
        self.context_menu_pos: Optional[tuple[int, int]] = None
        self.context_menu_index: Optional[int] = None
        self.last_click_index: Optional[int] = None
        self.last_click_at = 0.0
        self.cloud_phase = 0.0
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
        while self.running:
            dt = min(0.05, self.clock.tick(CLIENT.fps) / 1000.0)
            self.cloud_phase += dt
            self.cleanup_finished()
            self.checker.tick(self.store.servers)
            self.handle_events()
            self.draw()
        self.shutdown()

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
                continue
            if event.type == pygame.KEYDOWN and self.scene == "offline":
                if event.key == pygame.K_x:
                    self.start_client(ensure_local_server=True)
                    continue
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 3 and self.scene == "online":
                    self.open_context_menu_at(event.pos)
                    continue
                if event.button != 1:
                    continue
                if self.context_menu_pos and self.handle_context_menu_click(event.pos):
                    continue
                self.context_menu_pos = None
                for button in self.current_buttons():
                    if button.hit(event.pos):
                        button.action()
                        return
                if self.scene == "online":
                    self.handle_server_left_click(event.pos)

    def current_buttons(self) -> list[Button]:
        width, height = self.screen.get_size()
        if self.scene == "main":
            button_w, button_h = 250, 58
            x = width // 2 - button_w // 2
            y = height // 2 - 62
            return [
                Button(pygame.Rect(x, y, button_w, button_h), "Online", self.open_online),
                Button(pygame.Rect(x, y + 76, button_w, button_h), "Offline", self.open_offline),
                Button(pygame.Rect(x, y + 152, button_w, button_h), "Exit", self.exit_app),
            ]

        if self.scene == "offline":
            bottom = height - 96
            return [
                Button(pygame.Rect(56, bottom, 180, 54), "Start Server", self.start_server),
                Button(pygame.Rect(252, bottom, 180, 54), "New Client", lambda: self.start_client(ensure_local_server=True)),
                Button(pygame.Rect(width - 190, bottom, 134, 54), "Back", self.back_to_main),
            ]

        bottom = height - 88
        right = width - 56
        return [
            Button(pygame.Rect(56, bottom, 192, 52), "Direct Connect", self.open_direct_connect_modal),
            Button(pygame.Rect(264, bottom, 148, 52), "Add Server", self.open_add_modal),
            Button(pygame.Rect(right - 128, bottom, 128, 52), "Back", self.back_to_main),
        ]

    def open_online(self) -> None:
        self.scene = "online"
        self.context_menu_pos = None
        self.status = "Double-click a server to connect. Right-click for actions."
        self.checker.refresh_now(self.store.servers)

    def open_offline(self) -> None:
        self.scene = "offline"
        if not self.server_process:
            self.start_server()
        if not self.client_processes:
            self.start_client(ensure_local_server=True)

    def back_to_main(self) -> None:
        self.scene = "main"
        self.context_menu_pos = None
        self.status = "Choose a mode."

    def exit_app(self) -> None:
        self.running = False

    def start_server(self) -> None:
        if self.server_process and self.server_process.process.poll() is None:
            self.status = "Local server is already running."
            return
        process = subprocess.Popen([sys.executable, "server.py"], cwd=PROJECT_ROOT)
        self.server_process = ManagedProcess("server", process)
        self.status = "Local server started."

    def start_client(self, host: str = NETWORK.host, port: int = NETWORK.port, ensure_local_server: bool = False) -> None:
        if ensure_local_server:
            if not self.server_process or self.server_process.process.poll() is not None:
                self.start_server()
        self.client_counter += 1
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["SKYROOM_HOST"] = host
        env["SKYROOM_PORT"] = str(port)
        process = subprocess.Popen([sys.executable, "client.py"], cwd=PROJECT_ROOT, env=env)
        self.client_processes.append(ManagedProcess(f"client-{self.client_counter}", process))
        self.status = f"Opened client for {host}:{port}."

    def cleanup_finished(self) -> None:
        self.client_processes = [proc for proc in self.client_processes if proc.process.poll() is None]
        if self.server_process and self.server_process.process.poll() is not None:
            self.server_process = None

    def shutdown(self) -> None:
        for client in self.client_processes:
            if client.process.poll() is None:
                client.process.terminate()
        if self.server_process and self.server_process.process.poll() is None:
            self.server_process.process.terminate()
        pygame.quit()

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
        selected = self.get_selected_server()
        if not selected:
            return
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
            self.set_modal_error(f"That server already exists as {duplicate.name}.")
            return
        self.store.add(server)
        self.selected_server = len(self.store.servers) - 1
        self.checker.refresh_now(self.store.servers)
        self.modal = None
        self.status = f"Saved {server.name}."

    def submit_edit_server(self, values: list[str]) -> None:
        server = self.parse_server_values(values)
        if not server:
            return
        self.store.update(self.selected_server, server)
        self.checker.refresh_now(self.store.servers)
        self.modal = None
        self.status = f"Updated {server.name}."

    def parse_server_values(self, values: list[str]) -> Optional[ServerEntry]:
        name, host, port_text = values
        name = name.strip() or "Skyroom Server"
        host = host.strip()
        if not host:
            self.set_modal_error("Host is required.")
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

    def find_duplicate_server(self, server: ServerEntry, skip_index: Optional[int] = None) -> Optional[ServerEntry]:
        normalized_host = server.host.strip().lower()
        for index, existing in enumerate(self.store.servers):
            if skip_index is not None and index == skip_index:
                continue
            if existing.host.strip().lower() == normalized_host and existing.port == server.port:
                return existing
        return None

    def set_modal_error(self, text: str) -> None:
        if self.modal:
            self.modal.error = text

    def remove_selected_server(self) -> None:
        if not self.store.servers:
            return
        removed = self.store.servers[self.selected_server]
        self.store.remove(self.selected_server)
        self.selected_server = max(0, min(self.selected_server, len(self.store.servers) - 1))
        self.checker.refresh_now(self.store.servers)
        self.status = f"Removed {removed.name}."
        self.context_menu_pos = None

    def connect_selected_server(self) -> None:
        selected = self.get_selected_server()
        if selected:
            self.connect_to_server(selected)

    def connect_to_server(self, server: ServerEntry) -> None:
        self.status = f"Checking {server.host}:{server.port}..."
        self.draw()
        result = self.checker.check_once(server)
        if not result.online:
            self.status = f"{server.name} is offline or unreachable."
            return
        self.start_client(server.host, server.port)

    def get_selected_server(self) -> Optional[ServerEntry]:
        if not self.store.servers:
            return None
        self.selected_server = max(0, min(self.selected_server, len(self.store.servers) - 1))
        return self.store.servers[self.selected_server]

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
        if index is None:
            self.context_menu_pos = None
            self.context_menu_index = None
            return
        self.selected_server = index
        self.context_menu_index = index
        self.context_menu_pos = pos

    def handle_context_menu_click(self, pos: tuple[int, int]) -> bool:
        for button in self.context_menu_buttons():
            if button.hit(pos):
                button.action()
                self.context_menu_pos = None
                return True
        return False

    def server_index_at(self, pos: tuple[int, int]) -> Optional[int]:
        width, height = self.screen.get_size()
        list_rect = pygame.Rect(56, 150, width - 112, max(220, height - 260))
        row_h = 74
        for index, _server in enumerate(self.store.servers[: max(0, list_rect.height // row_h)]):
            row = pygame.Rect(list_rect.x + 12, list_rect.y + 12 + index * row_h, list_rect.width - 24, 62)
            if row.collidepoint(pos):
                return index
        return None

    def context_menu_buttons(self) -> list[Button]:
        if self.context_menu_pos is None or self.context_menu_index is None:
            return []
        x, y = self.context_menu_pos
        width, height = self.screen.get_size()
        menu_w = 172
        menu_h = 138
        x = min(x, width - menu_w - 14)
        y = min(y, height - menu_h - 14)
        return [
            Button(pygame.Rect(x + 10, y + 10, menu_w - 20, 34), "Connect", self.connect_selected_server),
            Button(pygame.Rect(x + 10, y + 52, menu_w - 20, 34), "Edit", self.open_edit_modal),
            Button(pygame.Rect(x + 10, y + 94, menu_w - 20, 34), "Remove", self.remove_selected_server),
        ]

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

    def draw_main_menu(self) -> None:
        width, height = self.screen.get_size()
        panel = pygame.Rect(width // 2 - 285, height // 2 - 220, 570, 440)
        self.draw_shadowed_panel(panel, 232)
        title = self.font_title.render("Skyroom", True, PALETTE["text"])
        subtitle = self.font_body.render("Soft rooms, local play, and saved servers", True, PALETTE["muted"])
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 72)))
        self.screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + 120)))
        for button in self.current_buttons():
            self.draw_glossy_button(button)
        self.draw_status_line(panel.bottom - 34)

    def draw_offline(self) -> None:
        width, height = self.screen.get_size()
        header = pygame.Rect(42, 36, width - 84, 112)
        self.draw_shadowed_panel(header, 224)
        title = self.font_heading.render("Offline", True, PALETTE["text"])
        hint = self.font_body.render("Local server and local client windows use the existing Skyroom game.", True, PALETTE["muted"])
        self.screen.blit(title, (header.x + 26, header.y + 22))
        self.screen.blit(hint, (header.x + 26, header.y + 66))

        panel = pygame.Rect(56, 180, width - 112, max(230, height - 310))
        self.draw_shadowed_panel(panel, 218)
        lines = [
            f"Server: {'running' if self.server_process else 'stopped'}",
            f"Client windows: {len(self.client_processes)} active",
            "Offline starts a local server and opens the client against 127.0.0.1.",
            "Use New Client when you want another local player window.",
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
        subtitle = self.font_body.render("Saved servers, direct connect, and local ping checks", True, PALETTE["muted"])
        self.screen.blit(title, (header.x + 26, header.y + 20))
        self.screen.blit(subtitle, (header.x + 26, header.y + 58))

        list_rect = pygame.Rect(56, 150, width - 112, max(220, height - 260))
        self.draw_shadowed_panel(list_rect, 216)
        if not self.store.servers:
            empty = self.font_body.render("No saved servers yet.", True, PALETTE["muted"])
            self.screen.blit(empty, empty.get_rect(center=list_rect.center))
        else:
            self.draw_server_rows(list_rect)

        for button in self.current_buttons():
            self.draw_glossy_button(button)
        self.draw_context_menu()
        self.draw_hover_tooltip()
        self.draw_status_line(height - 26)

    def draw_server_rows(self, list_rect: pygame.Rect) -> None:
        row_h = 74
        max_rows = max(0, list_rect.height // row_h)
        for index, server in enumerate(self.store.servers[:max_rows]):
            row = pygame.Rect(list_rect.x + 12, list_rect.y + 12 + index * row_h, list_rect.width - 24, 62)
            selected = index == self.selected_server
            fill = (255, 255, 255, 235) if selected else (248, 252, 255, 200)
            pygame.draw.rect(self.screen, fill, row, border_radius=22)
            pygame.draw.rect(self.screen, add_alpha(PALETTE["outline"], 240), row, width=2, border_radius=22)
            if selected:
                shine = pygame.Surface(row.size, pygame.SRCALPHA)
                pygame.draw.ellipse(shine, (255, 255, 255, 80), (-20, -24, row.width * 0.62, row.height * 0.92))
                self.screen.blit(shine, row.topleft)

            name = self.truncate(server.name, self.font_ui, row.width - 230)
            host = self.truncate(f"{server.host}:{server.port}", self.font_small, row.width - 230)
            name_surface = self.font_ui.render(name, True, PALETTE["text"])
            host_surface = self.font_small.render(host, True, PALETTE["muted"])
            self.screen.blit(name_surface, (row.x + 22, row.y + 11))
            self.screen.blit(host_surface, (row.x + 23, row.y + 39))

            signal_rect = pygame.Rect(row.right - 82, row.y + 17, 46, 32)
            self.signal_rects.append((signal_rect, server))
            self.draw_signal_indicator(signal_rect, self.checker.get(server))

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

    def draw_hover_tooltip(self) -> None:
        mouse = pygame.mouse.get_pos()
        for rect, server in self.signal_rects:
            if not rect.collidepoint(mouse):
                continue
            result = self.checker.get(server)
            text = f"Ping: {result.ping_ms} ms" if result.online and result.ping_ms is not None else "Offline"
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
        if not buttons:
            return
        bounds = buttons[0].rect.unionall([button.rect for button in buttons[1:]]).inflate(20, 20)
        shadow = pygame.Surface((bounds.width + 16, bounds.height + 16), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (111, 152, 211, 42), (8, 8, bounds.width, bounds.height), border_radius=18)
        self.screen.blit(shadow, (bounds.x - 8, bounds.y - 4))
        pygame.draw.rect(self.screen, (255, 255, 255, 240), bounds, border_radius=18)
        pygame.draw.rect(self.screen, add_alpha(PALETTE["outline"], 245), bounds, width=2, border_radius=18)
        for button in buttons:
            self.draw_context_button(button)

    def draw_context_button(self, button: Button) -> None:
        hover = button.rect.collidepoint(pygame.mouse.get_pos())
        fill = (241, 249, 255) if hover else (255, 255, 255)
        pygame.draw.rect(self.screen, fill, button.rect, border_radius=14)
        label = self.font_small.render(button.label, True, PALETTE["text"])
        self.screen.blit(label, label.get_rect(center=button.rect.center))

    def draw_modal(self) -> None:
        if not self.modal:
            return
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((236, 244, 255, 126))
        self.screen.blit(overlay, (0, 0))
        width, height = self.screen.get_size()
        modal_width = min(width - 96, 680)
        modal_rect = pygame.Rect(width // 2 - modal_width // 2, height // 2 - 160, modal_width, 320)
        self.draw_shadowed_panel(modal_rect, 244)
        title = self.font_heading.render(self.modal.title, True, PALETTE["text"])
        self.screen.blit(title, title.get_rect(center=(modal_rect.centerx, modal_rect.y + 44)))

        field_margin = 56
        field_gap = 24
        inner_width = modal_rect.width - field_margin * 2
        port_width = 168
        host_width = inner_width - field_gap - port_width
        if len(self.modal.fields) == 3:
            name_field, host_field, port_field = self.modal.fields
            self.draw_modal_field(name_field, pygame.Rect(modal_rect.x + field_margin, modal_rect.y + 108, inner_width, 48))
            self.draw_modal_field(host_field, pygame.Rect(modal_rect.x + field_margin, modal_rect.y + 184, host_width, 48))
            self.draw_modal_field(port_field, pygame.Rect(modal_rect.x + field_margin + host_width + field_gap, modal_rect.y + 184, port_width, 48))
        elif len(self.modal.fields) == 2:
            host_field, port_field = self.modal.fields
            self.draw_modal_field(host_field, pygame.Rect(modal_rect.x + field_margin, modal_rect.y + 126, host_width, 48))
            self.draw_modal_field(port_field, pygame.Rect(modal_rect.x + field_margin + host_width + field_gap, modal_rect.y + 126, port_width, 48))
        else:
            field_y = modal_rect.y + 92
            for field in self.modal.fields:
                self.draw_modal_field(field, pygame.Rect(modal_rect.x + field_margin, field_y + 24, inner_width, 48))
                field_y += 72

        if self.modal.error:
            error = self.font_small.render(self.modal.error, True, (188, 100, 126))
            self.screen.blit(error, error.get_rect(center=(modal_rect.centerx, modal_rect.bottom - 86)))

        self.modal.submit_rect = pygame.Rect(modal_rect.centerx - 170, modal_rect.bottom - 62, 158, 48)
        self.modal.cancel_rect = pygame.Rect(modal_rect.centerx + 12, modal_rect.bottom - 62, 158, 48)
        self.draw_glossy_button(Button(self.modal.submit_rect, self.modal.submit_label, lambda: None))
        self.draw_glossy_button(Button(self.modal.cancel_rect, "Cancel", lambda: None))

    def draw_modal_field(self, field: TextInput, rect: pygame.Rect) -> None:
        label = self.font_small.render(field.label, True, PALETTE["muted"])
        self.screen.blit(label, (rect.x + 2, rect.y - 22))
        field.rect = rect
        fill = PALETTE["panel_soft"] if field.active else (250, 253, 255)
        pygame.draw.rect(self.screen, fill, field.rect, border_radius=18)
        outline = PALETTE["primary"] if field.active else PALETTE["outline"]
        pygame.draw.rect(self.screen, outline, field.rect, width=2, border_radius=18)
        value = field.value or field.placeholder
        color = PALETTE["text"] if field.value else (155, 174, 204)
        rendered = self.font_body.render(self.truncate(value, self.font_body, field.rect.width - 26), True, color)
        if not field.value:
            rendered.set_alpha(150)
        self.screen.blit(rendered, (field.rect.x + 14, field.rect.y + 12))

    def draw_status_line(self, y: int) -> None:
        rendered = self.font_small.render(self.status, True, PALETTE["muted"])
        self.screen.blit(rendered, rendered.get_rect(center=(self.screen.get_width() // 2, y)))

    def draw_shadowed_panel(self, rect: pygame.Rect, alpha: int) -> None:
        shadow = pygame.Surface((rect.width + 24, rect.height + 24), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (111, 152, 211, 42), (12, 12, rect.width, rect.height), border_radius=28)
        self.screen.blit(shadow, (rect.x - 12, rect.y - 4))
        pygame.draw.rect(self.screen, add_alpha(PALETTE["panel"], alpha), rect, border_radius=28)
        pygame.draw.rect(self.screen, add_alpha(PALETTE["outline"], alpha), rect, width=2, border_radius=28)

    def draw_glossy_button(self, button: Button) -> None:
        mouse_over = button.rect.collidepoint(pygame.mouse.get_pos()) and button.enabled
        base = PALETTE["primary"] if button.enabled else (194, 208, 226)
        fill = blend(base, (255, 255, 255), 0.13 if mouse_over else 0.0)
        pygame.draw.rect(self.screen, fill, button.rect, border_radius=23)
        pygame.draw.rect(self.screen, add_alpha((255, 255, 255), 165), button.rect, width=2, border_radius=23)
        gloss = pygame.Surface(button.rect.size, pygame.SRCALPHA)
        pygame.draw.ellipse(gloss, (255, 255, 255, 92), (-8, -14, button.rect.width * 0.98, button.rect.height * 0.76))
        self.screen.blit(gloss, button.rect.topleft)
        label_color = (255, 255, 255) if button.enabled else (238, 244, 252)
        label = self.font_body.render(button.label, True, label_color)
        self.screen.blit(label, label.get_rect(center=button.rect.center))

    def draw_cloud(self, x: int, y: int, scale: float) -> None:
        surface = pygame.Surface((220, 110), pygame.SRCALPHA)
        cloud_color = (255, 255, 255, 68)
        for cx, cy, radius in ((58, 58, 34), (96, 42, 42), (136, 54, 38), (170, 60, 26)):
            pygame.draw.circle(surface, cloud_color, (int(cx * scale), int(cy * scale)), int(radius * scale))
        self.screen.blit(surface, (x, y))

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
