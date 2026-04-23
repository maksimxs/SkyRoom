from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import time
from typing import Any, Optional, Union


PALETTE: tuple[tuple[int, int, int], ...] = (
    (255, 164, 199),
    (155, 209, 255),
    (186, 245, 221),
    (255, 210, 160),
    (208, 191, 255),
    (255, 240, 167),
    (164, 240, 255),
    (255, 182, 215),
)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def length(x: float, y: float) -> float:
    return math.hypot(x, y)


def normalize(x: float, y: float) -> tuple[float, float]:
    magnitude = length(x, y)
    if magnitude == 0:
        return 0.0, 0.0
    return x / magnitude, y / magnitude


def facing_from_vector(dx: float, dy: float, fallback: str = "down") -> str:
    if dx == 0 and dy == 0:
        return fallback
    if abs(dx) > abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def facing_towards(source: tuple[float, float], target: tuple[float, float], fallback: str = "down") -> str:
    return facing_from_vector(target[0] - source[0], target[1] - source[1], fallback=fallback)


def color_from_name(name: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    base = PALETTE[digest[0] % len(PALETTE)]
    return (
        clamp_channel(base[0] + (digest[1] % 37) - 18),
        clamp_channel(base[1] + (digest[2] % 37) - 18),
        clamp_channel(base[2] + (digest[3] % 37) - 18),
    )


def clamp_channel(value: int) -> int:
    return max(140, min(255, value))


@dataclass
class RectObstacle:
    x: float
    y: float
    width: float
    height: float
    kind: str
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "shape": "rect",
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "kind": self.kind,
            "label": self.label,
        }


@dataclass
class CircleObstacle:
    x: float
    y: float
    radius: float
    kind: str
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "shape": "circle",
            "x": self.x,
            "y": self.y,
            "radius": self.radius,
            "kind": self.kind,
            "label": self.label,
        }


Obstacle = Union[RectObstacle, CircleObstacle]


@dataclass
class PlayerInput:
    move_x: float = 0.0
    move_y: float = 0.0
    target_x: Optional[float] = None
    target_y: Optional[float] = None

    def clear_target(self) -> None:
        self.target_x = None
        self.target_y = None


@dataclass
class PlayerState:
    player_id: str
    name: str
    x: float
    y: float
    color: tuple[int, int, int]
    facing: str = "down"
    glow_active: bool = False
    joy_started_at: float = 0.0
    joy_until: float = 0.0
    joy_seed: float = 0.0
    chat_text: str = ""
    chat_until: float = 0.0
    handshake_started_at: float = 0.0
    handshake_until: float = 0.0
    handshake_partner_id: Optional[str] = None
    connected_at: float = field(default_factory=time.time)
    input_state: PlayerInput = field(default_factory=PlayerInput)

    def as_dict(self, now: float) -> dict[str, Any]:
        return {
            "id": self.player_id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "color": list(self.color),
            "facing": self.facing,
            "glow_active": self.glow_active,
            "joy_duration": max(0.0, self.joy_until - self.joy_started_at),
            "joy_remaining": max(0.0, self.joy_until - now),
            "joy_seed": self.joy_seed,
            "chat_text": self.chat_text if self.chat_until > now else "",
            "chat_remaining": max(0.0, self.chat_until - now),
            "handshake_active": self.handshake_until > now,
            "handshake_duration": max(0.0, self.handshake_until - self.handshake_started_at),
            "handshake_remaining": max(0.0, self.handshake_until - now),
            "handshake_partner_id": self.handshake_partner_id if self.handshake_until > now else None,
        }
