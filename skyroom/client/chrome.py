from __future__ import annotations

from pathlib import Path
import math
import os
from typing import Optional

import pygame


LOGIN_TRACK = Path(
    os.getenv(
        "SKYROOM_LOGIN_MUSIC",
        r"C:\Users\Blossom\Downloads\Aexion - Velvet - ArpWire TV (192k).mp3",
    )
)
WORLD_TRACK = Path(
    os.getenv(
        "SKYROOM_WORLD_MUSIC",
        r"C:\Users\Blossom\Downloads\Mom and Dad's Computer - Couch Meditation - thanksforloitering (192k).mp3",
    )
)


def _triangle_points(center_x: int, center_y: int, radius: int, inverted: bool) -> list[tuple[int, int]]:
    points = []
    offset = math.pi / 2 if inverted else -math.pi / 2
    for index in range(3):
        angle = offset + index * (math.tau / 3)
        points.append((int(center_x + math.cos(angle) * radius), int(center_y + math.sin(angle) * radius)))
    return points


def create_window_icon(size: int = 64) -> pygame.Surface:
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    center = size // 2
    radius = int(size * 0.38)
    width = max(4, size // 10)

    up = _triangle_points(center, center, radius, False)
    down = _triangle_points(center, center, radius, True)

    pygame.draw.lines(surface, (10, 10, 16), True, up, width + 4)
    pygame.draw.lines(surface, (10, 10, 16), True, down, width + 4)
    pygame.draw.lines(surface, (58, 132, 255), True, up, width)
    pygame.draw.lines(surface, (255, 220, 96), True, down, width)
    return surface


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
