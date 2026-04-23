from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Iterable, List, Tuple

from config import SERVER
from models import CircleObstacle, Obstacle, PlayerState, RectObstacle, clamp, length


def _circle_hits_rect(circle_x: float, circle_y: float, radius: float, rect: RectObstacle) -> bool:
    nearest_x = clamp(circle_x, rect.x, rect.x + rect.width)
    nearest_y = clamp(circle_y, rect.y, rect.y + rect.height)
    return length(circle_x - nearest_x, circle_y - nearest_y) < radius


def _inflate_rect(rect: RectObstacle, padding: float) -> RectObstacle:
    return RectObstacle(
        rect.x - padding,
        rect.y - padding,
        rect.width + padding * 2,
        rect.height + padding * 2,
        rect.kind,
        rect.label,
    )


def _player_foot_position(x: float, y: float) -> Tuple[float, float]:
    return x, y + SERVER.player_foot_offset_y


def _obstacle_collision_rect(rect: RectObstacle) -> RectObstacle:
    depth_ratio = {
        "glass_garden": 0.34,
        "cloud_pavilion": 0.34,
        "crystal_tree": 0.28,
        "flower_bed": 0.46,
    }.get(rect.kind, 0.38)
    inset_ratio = {
        "glass_garden": 0.1,
        "cloud_pavilion": 0.08,
        "crystal_tree": 0.16,
        "flower_bed": 0.04,
    }.get(rect.kind, 0.08)
    inset_x = rect.width * inset_ratio
    depth_height = rect.height * depth_ratio
    return RectObstacle(
        rect.x + inset_x,
        rect.y + rect.height - depth_height,
        rect.width - inset_x * 2,
        depth_height,
        rect.kind,
        rect.label,
    )


def _obstacles_overlap(first: Obstacle, second: Obstacle, padding: float = 60.0) -> bool:
    if isinstance(first, CircleObstacle) and isinstance(second, CircleObstacle):
        return length(first.x - second.x, first.y - second.y) < first.radius + second.radius + padding

    if isinstance(first, RectObstacle) and isinstance(second, RectObstacle):
        first_right = first.x + first.width + padding
        second_right = second.x + second.width + padding
        first_bottom = first.y + first.height + padding
        second_bottom = second.y + second.height + padding
        return not (
            first_right < second.x - padding
            or second_right < first.x - padding
            or first_bottom < second.y - padding
            or second_bottom < first.y - padding
        )

    if isinstance(first, CircleObstacle) and isinstance(second, RectObstacle):
        return _circle_hits_rect(first.x, first.y, first.radius + padding, _inflate_rect(second, padding))

    if isinstance(first, RectObstacle) and isinstance(second, CircleObstacle):
        return _circle_hits_rect(second.x, second.y, second.radius + padding, _inflate_rect(first, padding))

    return False


def _player_overlap(candidate_x: float, candidate_y: float, other: PlayerState, radius: float) -> bool:
    foot_x, foot_y = _player_foot_position(candidate_x, candidate_y)
    other_foot_x, other_foot_y = _player_foot_position(other.x, other.y)
    return abs(foot_x - other_foot_x) < radius * 1.75 and abs(foot_y - other_foot_y) < radius * 0.92


@dataclass
class MapLayout:
    width: int = 1800
    height: int = 1200
    obstacles: List[Obstacle] = field(default_factory=list)
    spawn_points: List[Tuple[float, float]] = field(default_factory=list)

    @classmethod
    def build_default(cls) -> "MapLayout":
        rng = random.Random()
        obstacles: List[Obstacle] = []
        lake_candidates = [
            (320, 300, 130, "Pearl Lake"),
            (540, 900, 120, "Sky Mirror"),
            (930, 220, 125, "Mint Lagoon"),
            (1320, 320, 115, "Halo Water"),
            (1450, 860, 140, "Soft Basin"),
            (1040, 930, 130, "Glass Tide"),
        ]
        block_candidates = [
            (220, 520, 220, 120, "flower_bed", "Bloom Path"),
            (700, 420, 190, 130, "glass_garden", "Glasshouse"),
            (1080, 520, 140, 240, "crystal_tree", "Crystal Grove"),
            (1360, 640, 210, 130, "cloud_pavilion", "Cloud Deck"),
            (600, 720, 220, 120, "flower_bed", "Ribbon Garden"),
            (1220, 180, 200, 120, "glass_garden", "Dew Court"),
            (880, 820, 170, 220, "crystal_tree", "Pearl Arbor"),
        ]

        for x, y, radius, label in rng.sample(lake_candidates, len(lake_candidates)):
            candidate = CircleObstacle(x + rng.randint(-35, 35), y + rng.randint(-35, 35), radius + rng.randint(-16, 16), "lake", label)
            if any(_obstacles_overlap(candidate, placed, 85.0) for placed in obstacles):
                continue
            obstacles.append(candidate)
            if len([item for item in obstacles if isinstance(item, CircleObstacle)]) == 3:
                break

        for x, y, width, height, kind, label in rng.sample(block_candidates, len(block_candidates)):
            candidate = RectObstacle(x + rng.randint(-40, 40), y + rng.randint(-40, 40), width, height, kind, label)
            if any(_obstacles_overlap(candidate, placed, 90.0) for placed in obstacles):
                continue
            obstacles.append(candidate)
            if len([item for item in obstacles if isinstance(item, RectObstacle)]) == 4:
                break

        spawn_points = [
            (220, 180),
            (300, 160),
            (220, 1040),
            (1560, 200),
            (1620, 980),
            (920, 1080),
        ]
        return cls(obstacles=obstacles, spawn_points=spawn_points)

    def as_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "obstacles": [obstacle.as_dict() for obstacle in self.obstacles],
        }

    def collides(self, x: float, y: float, radius: float, other_players: Iterable[PlayerState], *, skip_id: str) -> bool:
        foot_x, foot_y = _player_foot_position(x, y)
        foot_radius = SERVER.player_foot_radius

        if x - radius < 0 or y - radius < 0 or x + radius > self.width or foot_y + foot_radius > self.height:
            return True

        for obstacle in self.obstacles:
            if isinstance(obstacle, CircleObstacle):
                if length(foot_x - obstacle.x, foot_y - obstacle.y) < foot_radius + obstacle.radius:
                    return True
            else:
                if _circle_hits_rect(foot_x, foot_y, foot_radius, _obstacle_collision_rect(obstacle)):
                    return True

        for player in other_players:
            if player.player_id == skip_id:
                continue
            if _player_overlap(x, y, player, radius):
                return True
        return False

    def choose_spawn(self, players: Iterable[PlayerState]) -> tuple[float, float]:
        player_list = list(players)
        radius = SERVER.player_radius
        rng = random.Random()
        for _ in range(160):
            x = rng.uniform(radius + 40, self.width - radius - 40)
            y = rng.uniform(radius + 40, self.height - radius - 40)
            if not self.collides(x, y, radius, player_list, skip_id=""):
                return x, y
        for x, y in self.spawn_points:
            if not self.collides(x, y, radius, player_list, skip_id=""):
                return x, y
        return self.width * 0.5, self.height * 0.5
