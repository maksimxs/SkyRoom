from __future__ import annotations

from typing import Any

import pytest

from skyroom.config import SERVER
from skyroom.models import CircleObstacle, PlayerState, RectObstacle
from skyroom.world import MapLayout, _obstacles_overlap


def make_player(player_id: str, x: float, y: float) -> PlayerState:
    return PlayerState(player_id=player_id, name=player_id, x=x, y=y, color=(200, 220, 255))


def test_build_default_generates_spaced_airy_layout() -> None:
    for _ in range(8):
        layout = MapLayout.build_default()
        lakes = [item for item in layout.obstacles if isinstance(item, CircleObstacle)]
        blocks = [item for item in layout.obstacles if isinstance(item, RectObstacle)]

        assert layout.width == 2200
        assert layout.height == 1450
        assert len(lakes) <= 4
        assert len(blocks) <= 8
        assert len(layout.spawn_points) == 10

        for index, first in enumerate(layout.obstacles):
            for second in layout.obstacles[index + 1 :]:
                if isinstance(first, CircleObstacle) and isinstance(second, CircleObstacle):
                    assert not _obstacles_overlap(first, second, 209.0)
                else:
                    assert not _obstacles_overlap(first, second, 89.0)


def test_collides_detects_boundaries_obstacles_and_other_players() -> None:
    layout = MapLayout(
        width=400,
        height=300,
        obstacles=[
            CircleObstacle(200, 160, 40, "mint_lagoon", "Mint Lagoon"),
            RectObstacle(40, 30, 100, 140, "flower_bed", "Bloom Path"),
        ],
        spawn_points=[],
    )
    other = make_player("other", 320, 140)

    assert layout.collides(20, 20, SERVER.player_radius, [other], skip_id="self") is True
    assert layout.collides(200, 140, SERVER.player_radius, [other], skip_id="self") is True
    assert layout.collides(90, 105, SERVER.player_radius, [other], skip_id="self") is True
    assert layout.collides(320, 140, SERVER.player_radius, [other], skip_id="self") is True
    assert layout.collides(370, 140, SERVER.player_radius, [other], skip_id="self") is False


def test_choose_spawn_falls_back_to_spawn_points_after_random_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    layout = MapLayout(width=500, height=400, obstacles=[], spawn_points=[(120, 150), (220, 260)])
    call_count = {"count": 0}

    def fake_collides(*args: Any, **kwargs: Any) -> bool:
        call_count["count"] += 1
        return call_count["count"] <= 160

    monkeypatch.setattr(layout, "collides", fake_collides)

    assert layout.choose_spawn([]) == (120, 150)


def test_choose_spawn_falls_back_to_center_when_everything_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    layout = MapLayout(width=500, height=400, obstacles=[], spawn_points=[(120, 150), (220, 260)])
    monkeypatch.setattr(layout, "collides", lambda *args, **kwargs: True)

    assert layout.choose_spawn([]) == (250.0, 200.0)
