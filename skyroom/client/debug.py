from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Deque

import pygame


@dataclass
class DebugEntry:
    created_at: float
    source: str
    message: str


class DebugConsole:
    def __init__(self, max_entries: int = 260) -> None:
        self.visible = False
        self.entries: Deque[DebugEntry] = deque(maxlen=max_entries)
        self.font_name = self._pick_font()
        self.font = pygame.font.SysFont(self.font_name, 16)
        self.font_header = pygame.font.SysFont(self.font_name, 18, bold=True)
        self.scroll_offset = 0
        self.overlay_rect = pygame.Rect(0, 0, 0, 0)

    def toggle(self) -> None:
        self.visible = not self.visible
        if self.visible:
            self.scroll_offset = 0

    def log(self, source: str, message: str) -> None:
        keep_tail = self.scroll_offset == 0
        self.entries.append(DebugEntry(created_at=time.time(), source=source[:8], message=message))
        if keep_tail:
            self.scroll_offset = 0

    def handle_event(self, event: pygame.event.Event, screen_size: tuple[int, int]) -> bool:
        if not self.visible:
            return False
        self._update_rect(screen_size)
        max_scroll = self._max_scroll()
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_PAGEUP:
                self.scroll_offset = min(max_scroll, self.scroll_offset + 8)
                return True
            if event.key == pygame.K_PAGEDOWN:
                self.scroll_offset = max(0, self.scroll_offset - 8)
                return True
            if event.key == pygame.K_HOME:
                self.scroll_offset = max_scroll
                return True
            if event.key == pygame.K_END:
                self.scroll_offset = 0
                return True
        if event.type == pygame.MOUSEWHEEL:
            if not self.overlay_rect.collidepoint(pygame.mouse.get_pos()):
                return False
            self.scroll_offset = max(0, min(max_scroll, self.scroll_offset + event.y * 3))
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5) and self.overlay_rect.collidepoint(event.pos):
            delta = 3 if event.button == 4 else -3
            self.scroll_offset = max(0, min(max_scroll, self.scroll_offset + delta))
            return True
        return False

    def draw(self, screen: pygame.Surface) -> None:
        if not self.visible:
            return
        width, height = screen.get_size()
        self._update_rect((width, height))
        overlay_rect = self.overlay_rect
        shadow = pygame.Surface((overlay_rect.width + 16, overlay_rect.height + 16), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 65), (8, 8, overlay_rect.width, overlay_rect.height), border_radius=10)
        screen.blit(shadow, (overlay_rect.x - 8, overlay_rect.y - 4))

        panel = pygame.Surface(overlay_rect.size, pygame.SRCALPHA)
        panel.fill((16, 20, 26, 222))
        screen.blit(panel, overlay_rect.topleft)
        pygame.draw.rect(screen, (76, 92, 110), overlay_rect, width=1, border_radius=10)

        header = self.font_header.render("DEBUG CONSOLE", True, (202, 216, 232))
        screen.blit(header, (overlay_rect.x + 14, overlay_rect.y + 10))

        y = overlay_rect.y + 40
        max_lines = max(1, (overlay_rect.height - 52) // 18)
        entries = list(self.entries)
        max_scroll = max(0, len(entries) - max_lines)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))
        start_index = max(0, len(entries) - max_lines - self.scroll_offset)
        visible_entries = entries[start_index:start_index + max_lines]
        for entry in visible_entries:
            timestamp = time.strftime("%H:%M:%S", time.localtime(entry.created_at))
            line = f"[{timestamp}] {entry.source:<8} {entry.message}"
            rendered = self.font.render(line, True, (196, 208, 221))
            screen.blit(rendered, (overlay_rect.x + 14, y))
            y += 18

        if max_scroll > 0:
            footer_text = f"{start_index + 1}-{start_index + len(visible_entries)} / {len(entries)}"
            footer = self.font.render(footer_text, True, (128, 145, 162))
            screen.blit(footer, footer.get_rect(bottomright=(overlay_rect.right - 12, overlay_rect.bottom - 8)))

    def _update_rect(self, screen_size: tuple[int, int]) -> None:
        width, height = screen_size
        self.overlay_rect = pygame.Rect(18, height - min(260, height - 36), width - 36, min(242, height - 48))

    def _max_scroll(self) -> int:
        max_lines = max(1, (self.overlay_rect.height - 52) // 18)
        return max(0, len(self.entries) - max_lines)

    @staticmethod
    def _pick_font() -> str:
        for candidate in ("Consolas", "Cascadia Mono", "Courier New", "Lucida Console"):
            if pygame.font.match_font(candidate):
                return candidate
        return pygame.font.get_default_font()
