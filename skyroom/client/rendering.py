from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any, Set, Tuple

import pygame

from ..config import SERVER
from .chrome import draw_custom_cursor
from .state import PlayerView, add_alpha, blend

if TYPE_CHECKING:
    from .app import SkyroomClientApp


PALETTE = {
    "bg_top": (226, 241, 255),
    "bg_bottom": (253, 244, 255),
    "panel": (255, 255, 255),
    "panel_soft": (244, 251, 255),
    "text": (74, 93, 122),
    "muted": (130, 151, 184),
    "outline": (222, 235, 255),
    "primary": (148, 212, 255),
    "water": (168, 221, 255),
    "water_dark": (123, 196, 252),
    "grass": (231, 247, 228),
    "halo": (255, 232, 150),
    "shadow": (94, 125, 169),
}


def pick_font_name() -> str:
    for candidate in ("Segoe UI", "Tahoma", "Leelawadee UI", "Candara", "Trebuchet MS", "Arial Unicode MS"):
        if pygame.font.match_font(candidate):
            return candidate
    return pygame.font.get_default_font()


class SceneRenderer:
    def __init__(self, app: "SkyroomClientApp") -> None:
        self.app = app

    def draw(self) -> None:
        self.draw_background()
        if self.app.scene == "login":
            self.draw_login()
        else:
            self.draw_world()
            self.draw_hud()
        draw_custom_cursor(self.app.screen, pygame.mouse.get_pos(), self.app.cloud_phase)
        pygame.display.flip()

    def draw_background(self) -> None:
        width, height = self.app.screen.get_size()
        for y in range(height):
            t = y / max(1, height - 1)
            color = blend(PALETTE["bg_top"], PALETTE["bg_bottom"], t)
            pygame.draw.line(self.app.screen, color, (0, y), (width, y))

        for spec in self.app.cloud_specs:
            span = width + spec["drift"] + 260.0
            offset = (spec["offset"] + self.app.cloud_phase * spec["speed"]) % span - 180.0
            cloud_y = spec["y"] + math.sin(self.app.cloud_phase * 0.6 + spec["phase"]) * spec["wobble"]
            self.draw_cloud(int(offset), int(cloud_y), spec["scale"])

    def draw_login(self) -> None:
        width, height = self.app.screen.get_size()
        card = pygame.Rect(width // 2 - 260, height // 2 - 170, 520, 340)
        self.draw_shadowed_panel(card, alpha=235)

        title = self.app.font_title.render("Skyroom", True, PALETTE["text"])
        subtitle = self.app.font_body.render("A tiny ethereal multiplayer room", True, PALETTE["muted"])
        blessing = self.app.font_small.render("Jews rule. Crème de la crème", True, PALETTE["muted"])
        self.app.screen.blit(title, title.get_rect(center=(card.centerx, card.y + 62)))
        self.app.screen.blit(subtitle, subtitle.get_rect(center=(card.centerx, card.y + 112)))
        self.app.screen.blit(blessing, blessing.get_rect(center=(card.centerx, card.y + 136)))

        input_rect = pygame.Rect(card.x + 48, card.y + 164, card.width - 96, 58)
        pygame.draw.rect(self.app.screen, add_alpha(PALETTE["panel_soft"], 255), input_rect, border_radius=22)
        pygame.draw.rect(self.app.screen, add_alpha(PALETTE["outline"], 255), input_rect, width=2, border_radius=22)
        name_text = self.app.login_name or "Enter your name"
        text_color = PALETTE["text"] if self.app.login_name else PALETTE["muted"]
        rendered_name = self.app.font_ui.render(name_text, True, text_color)
        self.app.screen.blit(rendered_name, (input_rect.x + 20, input_rect.y + 14))

        self.draw_glossy_button(self.app.login_button_rect(), "Join Room")

        if self.app.connection_message:
            status = self.app.font_small.render(self.app.connection_message, True, PALETTE["muted"])
            self.app.screen.blit(status, status.get_rect(center=(card.centerx, card.bottom - 24)))

    def draw_world(self) -> None:
        self.draw_map_ground()
        players = sorted(self.app.players.values(), key=lambda item: item.display_y + SERVER.player_foot_offset_y)
        for player in players:
            screen_x, screen_y = self.app.world_to_screen((player.display_x, player.display_y))
            self.draw_player_shadow(screen_x, screen_y, player)
        self.draw_map_background()
        for player in players:
            self.draw_player(player)
        self.draw_map_foreground()
        self.draw_handshakes()

    def draw_map_ground(self) -> None:
        if not self.app.map_data:
            return
        map_rect = pygame.Rect(int(-self.app.camera_x), int(-self.app.camera_y), self.app.map_data["width"], self.app.map_data["height"])
        pygame.draw.rect(self.app.screen, PALETTE["grass"], map_rect, border_radius=40)

        accent_surface = pygame.Surface(self.app.screen.get_size(), pygame.SRCALPHA)
        drift_x = math.sin(self.app.cloud_phase * 0.018) * 18.0
        drift_y = math.cos(self.app.cloud_phase * 0.014) * 10.0
        world_start_y = math.floor((self.app.camera_y - 180.0) / 180.0) * 180.0
        for stripe in range(9):
            world_y = world_start_y + stripe * 180.0 + drift_y
            screen_y = world_y - self.app.camera_y
            screen_x = -140.0 - (self.app.camera_x * 0.02) + drift_x
            pygame.draw.ellipse(
                accent_surface,
                (255, 255, 255, 24),
                (screen_x, screen_y, self.app.screen.get_width() + 280, 96),
            )
        self.app.screen.blit(accent_surface, (0, 0))

    def draw_map_background(self) -> None:
        if not self.app.map_data:
            return

        for obstacle in self.app.map_data["obstacles"]:
            if obstacle["shape"] == "circle":
                self.draw_lake(obstacle)
            else:
                self.draw_feature_block_back(obstacle)

    def draw_map_foreground(self) -> None:
        if not self.app.map_data:
            return
        for obstacle in self.app.map_data["obstacles"]:
            if obstacle["shape"] == "rect":
                self.draw_feature_block_front(obstacle)

    def draw_lake(self, obstacle: dict[str, Any]) -> None:
        center = self.app.world_to_screen((obstacle["x"], obstacle["y"]))
        radius = int(obstacle["radius"])
        shadow = pygame.Surface((radius * 3, radius * 3), pygame.SRCALPHA)
        pygame.draw.circle(shadow, (128, 188, 255, 45), (shadow.get_width() // 2, shadow.get_height() // 2 + 12), radius + 22)
        self.app.screen.blit(shadow, (center[0] - shadow.get_width() // 2, center[1] - shadow.get_height() // 2))
        pygame.draw.circle(self.app.screen, PALETTE["water"], center, radius)
        pygame.draw.circle(self.app.screen, PALETTE["water_dark"], center, radius, width=5)
        pygame.draw.circle(self.app.screen, add_alpha((255, 255, 255), 90), (center[0] - radius // 3, center[1] - radius // 3), radius // 3)
        label = self.app.font_small.render(obstacle["label"], True, PALETTE["muted"])
        self.app.screen.blit(label, label.get_rect(center=(center[0], center[1] + radius + 18)))

    def draw_feature_block_back(self, obstacle: dict[str, Any]) -> None:
        rect = pygame.Rect(
            int(obstacle["x"] - self.app.camera_x),
            int(obstacle["y"] - self.app.camera_y),
            int(obstacle["width"]),
            int(obstacle["height"]),
        )
        base_color = {
            "glass_garden": (226, 255, 245),
            "flower_bed": (255, 228, 241),
            "crystal_tree": (225, 241, 255),
            "cloud_pavilion": (236, 238, 255),
        }.get(obstacle["kind"], PALETTE["panel_soft"])
        pygame.draw.rect(self.app.screen, base_color, rect, border_radius=34)
        pygame.draw.rect(self.app.screen, add_alpha((255, 255, 255), 180), rect.inflate(-18, -18), width=4, border_radius=26)
        gloss = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.ellipse(gloss, (255, 255, 255, 85), (-10, -8, rect.width * 0.9, rect.height * 0.65))
        self.app.screen.blit(gloss, rect.topleft)
        label = self.app.font_small.render(obstacle["label"], True, PALETTE["muted"])
        self.app.screen.blit(label, label.get_rect(center=(rect.centerx, rect.bottom + 16)))

    def draw_feature_block_front(self, obstacle: dict[str, Any]) -> None:
        rect = pygame.Rect(
            int(obstacle["x"] - self.app.camera_x),
            int(obstacle["y"] - self.app.camera_y),
            int(obstacle["width"]),
            int(obstacle["height"]),
        )
        lip_height = max(24, int(rect.height * 0.3))
        lip_rect = pygame.Rect(rect.x + 8, rect.bottom - lip_height, rect.width - 16, lip_height + 6)
        front_color = {
            "glass_garden": (214, 247, 236),
            "flower_bed": (255, 214, 233),
            "crystal_tree": (213, 233, 252),
            "cloud_pavilion": (228, 231, 251),
        }.get(obstacle["kind"], (235, 241, 251))
        shadow = pygame.Surface((lip_rect.width + 18, lip_rect.height + 18), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (122, 148, 185, 30), (10, lip_rect.height - 6, lip_rect.width - 2, 12))
        self.app.screen.blit(shadow, (lip_rect.x - 9, lip_rect.y - 8))
        pygame.draw.rect(self.app.screen, front_color, lip_rect, border_radius=24)
        pygame.draw.rect(self.app.screen, add_alpha((255, 255, 255), 170), lip_rect, width=2, border_radius=24)
        front_gloss = pygame.Surface(lip_rect.size, pygame.SRCALPHA)
        pygame.draw.ellipse(front_gloss, (255, 255, 255, 55), (-4, -2, lip_rect.width * 0.8, lip_rect.height * 0.7))
        self.app.screen.blit(front_gloss, lip_rect.topleft)

    def draw_player(self, player: PlayerView) -> None:
        screen_x, screen_y = self.app.world_to_screen((player.display_x, player.display_y))
        is_local = player.player_id == self.app.self_id
        jump_y = screen_y - int(player.jump_offset)

        glow_alpha = int(player.tint_level * 110)
        if glow_alpha > 4:
            aura_surface = pygame.Surface((110, 110), pygame.SRCALPHA)
            pygame.draw.circle(aura_surface, add_alpha(player.color, glow_alpha), (55, 55), int(20 + player.tint_level * 14))
            pygame.draw.circle(aura_surface, add_alpha(player.color, max(0, glow_alpha // 2)), (55, 55), int(28 + player.tint_level * 10), width=3)
            self.app.screen.blit(aura_surface, (screen_x - 55, jump_y - 55))

        body_width = max(42, int(56 * player.body_scale_x))
        body_height = max(40, int(56 * player.body_scale_y))
        body_rect = pygame.Rect(0, 0, body_width, body_height)
        body_rect.center = (screen_x, jump_y)
        body_fill = blend((247, 251, 255), player.color, player.tint_level * 0.82)
        outline = blend((255, 255, 255), player.color, player.tint_level * 0.28)
        pygame.draw.ellipse(self.app.screen, body_fill, body_rect)
        pygame.draw.ellipse(self.app.screen, outline, body_rect, width=3)
        gloss_rect = pygame.Rect(0, 0, max(16, int(body_width * 0.42)), max(10, int(body_height * 0.3)))
        gloss_rect.center = (body_rect.centerx - body_width // 7, body_rect.centery - body_height // 5)
        pygame.draw.ellipse(self.app.screen, add_alpha((255, 255, 255), 185), gloss_rect)

        self.draw_direction_marker(screen_x, jump_y, player.facing, is_local)
        self.draw_halo(screen_x, jump_y, is_local)

        if not is_local:
            name_surface = self.app.font_body.render(player.name, True, PALETTE["text"])
            pill_rect = name_surface.get_rect(center=(screen_x, jump_y - 52)).inflate(18, 12)
            self.draw_pill(pill_rect, add_alpha((255, 255, 255), 205))
            self.app.screen.blit(name_surface, name_surface.get_rect(center=pill_rect.center))

        if player.chat_text:
            self.draw_chat_bubble(screen_x, jump_y - 84, player.chat_text)

    def draw_player_shadow(self, x: int, y: int, player: PlayerView) -> None:
        shadow_width = int(42 * player.shadow_scale)
        shadow_height = int(14 * max(0.7, player.shadow_scale))
        shadow = pygame.Surface((shadow_width + 24, shadow_height + 18), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (PALETTE["shadow"][0], PALETTE["shadow"][1], PALETTE["shadow"][2], 50), (12, 8, shadow_width, shadow_height))
        self.app.screen.blit(shadow, (x - shadow.get_width() // 2, y + 18))

    def draw_halo(self, x: int, y: int, is_local: bool) -> None:
        glow = pygame.Surface((92, 44), pygame.SRCALPHA)
        alpha = 110 if is_local else 78
        pygame.draw.ellipse(glow, add_alpha(PALETTE["halo"], alpha // 2), pygame.Rect(9, 13, 74, 18))
        self.app.screen.blit(glow, (x - 46, y - 66))
        halo_rect = pygame.Rect(x - 22, y - 56, 44, 12)
        pygame.draw.ellipse(self.app.screen, add_alpha((255, 255, 255), 220), halo_rect, width=3)
        pygame.draw.ellipse(self.app.screen, add_alpha(PALETTE["halo"], alpha), halo_rect.inflate(4, 2), width=2)

    def draw_direction_marker(self, x: int, y: int, facing: str, emphasized: bool) -> None:
        distance = 44 if emphasized else 40
        size = 11 if emphasized else 9
        color = (255, 255, 255)
        outline = (240, 244, 252)
        if facing == "up":
            points = [(x, y - distance), (x - size, y - distance + size + 3), (x + size, y - distance + size + 3)]
        elif facing == "down":
            points = [(x, y + distance), (x - size, y + distance - size - 3), (x + size, y + distance - size - 3)]
        elif facing == "left":
            points = [(x - distance, y), (x - distance + size + 3, y - size), (x - distance + size + 3, y + size)]
        else:
            points = [(x + distance, y), (x + distance - size - 3, y - size), (x + distance - size - 3, y + size)]
        pygame.draw.polygon(self.app.screen, color, points)
        pygame.draw.polygon(self.app.screen, outline, points, width=2)

    def draw_handshakes(self) -> None:
        rendered_pairs: Set[Tuple[str, str]] = set()
        for player in self.app.players.values():
            partner_id = player.handshake_partner_id
            if not partner_id or partner_id not in self.app.players:
                continue
            pair = tuple(sorted((player.player_id, partner_id)))
            if pair in rendered_pairs:
                continue
            rendered_pairs.add(pair)
            self.draw_handshake_effect(player, self.app.players[partner_id])

    def draw_handshake_effect(self, player_a: PlayerView, player_b: PlayerView) -> None:
        duration = max(0.001, max(player_a.handshake_duration, player_b.handshake_duration))
        remaining = max(player_a.handshake_remaining, player_b.handshake_remaining)
        progress = min(1.0, 1.0 - remaining / duration)
        converge_portion = 0.22

        ax, ay = self.app.world_to_screen((player_a.display_x, player_a.display_y - player_a.jump_offset + 6))
        bx, by = self.app.world_to_screen((player_b.display_x, player_b.display_y - player_b.jump_offset + 6))
        center_x = int((ax + bx) / 2)
        center_y = int((ay + by) / 2 - 2)

        if progress < converge_portion:
            fly_t = progress / converge_portion
            left_x = int(ax + (center_x - ax) * fly_t)
            left_y = int(ay + (center_y - ay) * fly_t)
            right_x = int(bx + (center_x - bx) * fly_t)
            right_y = int(by + (center_y - by) * fly_t)
            scale = 0.55 + fly_t * 0.55
            self.draw_handshake_glyph(left_x, left_y, scale, 0)
            self.draw_handshake_glyph(right_x, right_y, scale, 0)
        else:
            settle_t = (progress - converge_portion) / (1.0 - converge_portion)
            scale = 0.95 + math.sin(settle_t * math.pi) * 0.18 + settle_t * 0.14
            shadow_alpha = int(18 * min(1.0, settle_t * 5.0))
            self.draw_handshake_glyph(center_x, center_y, scale, shadow_alpha)

    def draw_handshake_glyph(self, x: int, y: int, scale: float, shadow_alpha: int) -> None:
        if shadow_alpha > 0:
            shadow = pygame.Surface((92, 44), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (94, 125, 169, shadow_alpha), (22, 19, 48, 10))
            self.app.screen.blit(shadow, (x - 46, y + 8))
        emoji_surface = self.app.font_emoji.render("\U0001F91D", True, (255, 255, 255))
        emoji_surface = pygame.transform.smoothscale(
            emoji_surface,
            (
                max(18, int(emoji_surface.get_width() * scale)),
                max(18, int(emoji_surface.get_height() * scale)),
            ),
        )
        self.app.screen.blit(emoji_surface, emoji_surface.get_rect(center=(x, y)))

    def draw_chat_bubble(self, x: int, y: int, text: str) -> None:
        bubble = self.app.font_small.render(text, True, PALETTE["text"])
        bubble_rect = bubble.get_rect(center=(x, y)).inflate(24, 18)
        shadow_rect = bubble_rect.move(0, 6)
        bubble_surface = pygame.Surface((shadow_rect.width + 16, shadow_rect.height + 26), pygame.SRCALPHA)
        pygame.draw.rect(bubble_surface, (104, 140, 196, 35), (8, 8, shadow_rect.width, shadow_rect.height), border_radius=20)
        self.app.screen.blit(bubble_surface, (shadow_rect.x - 8, shadow_rect.y - 8))
        self.draw_pill(bubble_rect, add_alpha((255, 255, 255), 238))
        tail = [(x - 8, bubble_rect.bottom - 1), (x + 8, bubble_rect.bottom - 1), (x, bubble_rect.bottom + 12)]
        pygame.draw.polygon(self.app.screen, (255, 255, 255), tail)
        self.app.screen.blit(bubble, bubble.get_rect(center=bubble_rect.center))

    def draw_hud(self) -> None:
        width, height = self.app.screen.get_size()
        top_bar = pygame.Rect(18, 18, min(610, width - 36), 72)
        self.draw_shadowed_panel(top_bar, alpha=214)
        title = self.app.font_ui.render("Skyroom", True, PALETTE["text"])
        local_player = self.app.players.get(self.app.self_id or "")
        hud_line = "WASD | Q | E"
        if local_player:
            hud_line = "You: {0} | WASD | Q | E".format(local_player.name)
        subtitle = self.app.font_small.render(hud_line, True, PALETTE["muted"])
        self.app.screen.blit(title, (top_bar.x + 22, top_bar.y + 14))
        self.app.screen.blit(subtitle, (top_bar.x + 22, top_bar.y + 44))

        room_status = "{0} online | {1}".format(len(self.app.players), self.app.connection_message)
        status_surface = self.app.font_small.render(room_status, True, PALETTE["muted"])
        status_rect = status_surface.get_rect(topright=(width - 28, 38))
        self.app.screen.blit(status_surface, status_rect)

        if self.app.chat_mode:
            chat_rect = pygame.Rect(width // 2 - 260, height - 96, 520, 56)
            self.draw_shadowed_panel(chat_rect, alpha=230)
            prompt = self.app.font_body.render(self.app.chat_input or "Type a short message...", True, PALETTE["text"] if self.app.chat_input else PALETTE["muted"])
            self.app.screen.blit(prompt, (chat_rect.x + 18, chat_rect.y + 16))

        for index, toast in enumerate(self.app.toasts[:3]):
            age = time.time() - toast.created_at
            alpha = 235 if age < toast.duration - 0.5 else int(235 * max(0.0, (toast.duration - age) / 0.5))
            toast_rect = pygame.Rect(width - 380, 96 + index * 66, 340, 52)
            self.draw_pill(toast_rect, add_alpha((255, 255, 255), alpha))
            text_surface = self.app.font_small.render(toast.text, True, PALETTE["text"])
            self.app.screen.blit(text_surface, text_surface.get_rect(center=toast_rect.center))

    def draw_shadowed_panel(self, rect: pygame.Rect, alpha: int) -> None:
        shadow = pygame.Surface((rect.width + 24, rect.height + 24), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (111, 152, 211, 45), (12, 12, rect.width, rect.height), border_radius=28)
        self.app.screen.blit(shadow, (rect.x - 12, rect.y - 4))
        pygame.draw.rect(self.app.screen, add_alpha(PALETTE["panel"], alpha), rect, border_radius=28)
        pygame.draw.rect(self.app.screen, add_alpha(PALETTE["outline"], alpha), rect, width=2, border_radius=28)

    def draw_glossy_button(self, rect: pygame.Rect, text: str) -> None:
        pygame.draw.rect(self.app.screen, PALETTE["primary"], rect, border_radius=24)
        pygame.draw.rect(self.app.screen, add_alpha((255, 255, 255), 160), rect, width=2, border_radius=24)
        gloss = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.ellipse(gloss, (255, 255, 255, 95), (-6, -12, rect.width * 0.96, rect.height * 0.72))
        self.app.screen.blit(gloss, rect.topleft)
        label = self.app.font_ui.render(text, True, (255, 255, 255))
        self.app.screen.blit(label, label.get_rect(center=rect.center))

    def draw_pill(self, rect: pygame.Rect, fill: tuple[int, int, int, int]) -> None:
        pill = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(pill, fill, pill.get_rect(), border_radius=min(rect.height // 2, 22))
        pygame.draw.rect(pill, (255, 255, 255, min(255, fill[3])), pill.get_rect(), width=2, border_radius=min(rect.height // 2, 22))
        self.app.screen.blit(pill, rect.topleft)

    def draw_cloud(self, x: int, y: int, scale: float) -> None:
        surface = pygame.Surface((220, 110), pygame.SRCALPHA)
        cloud_color = (255, 255, 255, 72)
        circles = [
            (58, 58, 34),
            (96, 42, 42),
            (136, 54, 38),
            (170, 60, 26),
        ]
        for cx, cy, radius in circles:
            pygame.draw.circle(surface, cloud_color, (int(cx * scale), int(cy * scale)), int(radius * scale))
        self.app.screen.blit(surface, (x, y))
