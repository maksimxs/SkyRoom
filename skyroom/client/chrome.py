from __future__ import annotations

import ctypes
from pathlib import Path
import math
import sys
from typing import Optional

import pygame


ASSETS_DIR = Path("assets")
ICON_ASSET = Path("assets/icon_bubble.png")
WINDOWS_APP_ID = "skyroom.app"


def _resource_path(relative_path: Path) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base_path / relative_path


def _asset_track_path(filename: str) -> Optional[Path]:
    candidate = _resource_path(ASSETS_DIR / filename)
    return candidate if candidate.exists() else None


LOGIN_TRACK = _asset_track_path("login_music.mp3")
WORLD_TRACK = _asset_track_path("world_music.mp3")


def apply_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def _make_circular_icon(icon: pygame.Surface, size: int) -> pygame.Surface:
    working = pygame.Surface((size, size), pygame.SRCALPHA)
    working.blit(icon, (0, 0))
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    radius = max(6, size // 2 - max(1, size // 18))
    pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), radius)
    working.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return working


def create_window_icon(size: int = 64) -> pygame.Surface:
    icon_path = _resource_path(ICON_ASSET)
    if icon_path.exists():
        try:
            icon = pygame.image.load(str(icon_path))
            if size > 0 and icon.get_size() != (size, size):
                icon = pygame.transform.smoothscale(icon, (size, size))
            icon = icon.convert_alpha() if icon.get_alpha() is not None else icon.convert_alpha()
            return _make_circular_icon(icon, size)
        except pygame.error:
            pass

    return pygame.Surface((size, size), pygame.SRCALPHA)


def draw_custom_cursor(screen: pygame.Surface, position: tuple[int, int], phase: float) -> None:
    x, y = position
    halo = pygame.Surface((34, 34), pygame.SRCALPHA)
    halo_alpha = 44 + int((math.sin(phase * 2.2) * 0.5 + 0.5) * 20)
    pygame.draw.circle(halo, (255, 242, 196, halo_alpha), (17, 17), 11)
    screen.blit(halo, (x - 17, y - 17))

    star_points = [
        (x, y - 10),
        (x + 3, y - 3),
        (x + 10, y),
        (x + 3, y + 3),
        (x, y + 10),
        (x - 3, y + 3),
        (x - 10, y),
        (x - 3, y - 3),
    ]
    pygame.draw.polygon(screen, (14, 14, 22), star_points, width=4)
    pygame.draw.polygon(screen, (255, 234, 145), star_points)
    pygame.draw.circle(screen, (255, 255, 255), (x + 7, y - 7), 2)


class AudioController:
    def __init__(self) -> None:
        self.available = False
        self.current_track: Optional[Path] = None
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self.available = True
        except pygame.error:
            self.available = False

    def set_scene(self, scene: str) -> None:
        if not self.available:
            return

        track = LOGIN_TRACK if scene == "login" else WORLD_TRACK
        if not track:
            return
        volume = 0.04 if scene == "login" else 0.06
        if self.current_track == track:
            return
        if not track.exists():
            return

        try:
            pygame.mixer.music.load(str(track))
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play(-1, fade_ms=900)
            self.current_track = track
        except pygame.error:
            self.current_track = None

    def stop(self) -> None:
        if self.available and pygame.mixer.get_init():
            pygame.mixer.music.stop()
