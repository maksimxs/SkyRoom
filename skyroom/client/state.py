from __future__ import annotations

from dataclasses import dataclass
import math

from ..models import lerp


@dataclass
class Toast:
    text: str
    created_at: float
    duration: float = 2.2


@dataclass
class PlayerView:
    player_id: str
    name: str
    x: float
    y: float
    color: tuple[int, int, int]
    facing: str
    glow_active: bool
    joy_duration: float
    joy_remaining: float
    joy_seed: float
    chat_text: str
    chat_remaining: float
    handshake_active: bool
    handshake_duration: float
    handshake_remaining: float
    handshake_partner_id: str
    display_x: float
    display_y: float
    tint_level: float = 0.0
    jump_offset: float = 0.0
    body_scale_x: float = 1.0
    body_scale_y: float = 1.0
    shadow_scale: float = 1.0

    def absorb(self, payload: dict) -> None:
        self.name = payload["name"]
        self.x = float(payload["x"])
        self.y = float(payload["y"])
        self.color = tuple(payload["color"])
        self.facing = payload["facing"]
        self.glow_active = bool(payload["glow_active"])
        self.joy_duration = float(payload.get("joy_duration", 0.0))
        self.joy_remaining = float(payload.get("joy_remaining", 0.0))
        self.joy_seed = float(payload.get("joy_seed", 0.0))
        self.chat_text = payload.get("chat_text", "")
        self.chat_remaining = float(payload.get("chat_remaining", 0.0))
        self.handshake_active = bool(payload.get("handshake_active", False))
        self.handshake_duration = float(payload.get("handshake_duration", 0.0))
        self.handshake_remaining = float(payload.get("handshake_remaining", 0.0))
        self.handshake_partner_id = payload.get("handshake_partner_id", "") or ""

    def tick(self, dt: float, is_local: bool) -> None:
        position_lerp = 0.35 if is_local else 0.2
        self.display_x = lerp(self.display_x, self.x, 1 - math.pow(1 - position_lerp, dt * 60))
        self.display_y = lerp(self.display_y, self.y, 1 - math.pow(1 - position_lerp, dt * 60))
        active_duration = max(0.001, self.joy_duration)
        elapsed = max(0.0, active_duration - self.joy_remaining)
        progress = min(1.0, elapsed / active_duration)
        if self.glow_active:
            energy = math.pow(max(0.0, 1.0 - progress), 0.55)
            phase = elapsed * (7.0 + self.joy_seed * 3.0)
            self.jump_offset = max(0.0, math.sin(phase) * (10.0 + self.joy_seed * 8.0) * energy)
            stretch = math.sin(phase - 0.55) * 0.1 * energy
            self.body_scale_x = 1.0 + max(0.0, self.jump_offset / 40.0) * 0.16 + stretch
            self.body_scale_y = 1.0 - max(0.0, self.jump_offset / 40.0) * 0.12 - stretch * 0.55
            self.shadow_scale = 1.0 - max(0.0, self.jump_offset / 26.0) * 0.22
        else:
            self.jump_offset = lerp(self.jump_offset, 0.0, 1 - math.pow(0.02, dt))
            self.body_scale_x = lerp(self.body_scale_x, 1.0, 1 - math.pow(0.02, dt))
            self.body_scale_y = lerp(self.body_scale_y, 1.0, 1 - math.pow(0.02, dt))
            self.shadow_scale = lerp(self.shadow_scale, 1.0, 1 - math.pow(0.02, dt))
        target_tint = 1.0 if self.glow_active else 0.0
        self.tint_level = lerp(self.tint_level, target_tint, 1 - math.pow(0.04, dt))


def blend(color_a: tuple[int, int, int], color_b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(lerp(color_a[0], color_b[0], t)),
        int(lerp(color_a[1], color_b[1], t)),
        int(lerp(color_a[2], color_b[2], t)),
    )


def add_alpha(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return color[0], color[1], color[2], alpha
