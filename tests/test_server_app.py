from __future__ import annotations

import asyncio

from skyroom.models import PlayerState
from skyroom.server.app import ClientSession, GameServer
from skyroom.world import MapLayout


def make_player(player_id: str, name: str, x: float, y: float) -> PlayerState:
    return PlayerState(player_id=player_id, name=name, x=x, y=y, color=(200, 220, 255))


def make_server_with_players(*players: PlayerState) -> GameServer:
    server = GameServer()
    server.map_layout = MapLayout(width=400, height=300, obstacles=[], spawn_points=[])
    server.sessions = {
        player.player_id: ClientSession(player=player, writer=object())  # type: ignore[arg-type]
        for player in players
    }
    return server


def test_try_handshake_picks_nearest_player_and_updates_both_sides() -> None:
    initiator = make_player("a1", "User", 100, 100)
    near = make_player("b2", "Mint", 136, 104)
    far = make_player("c3", "Cloud", 180, 100)
    server = make_server_with_players(initiator, near, far)

    payload = server.try_handshake(initiator)

    assert payload == {
        "type": "handshake",
        "initiator_id": "a1",
        "initiator_name": "User",
        "partner_id": "b2",
        "partner_name": "Mint",
    }
    assert initiator.handshake_partner_id == "b2"
    assert near.handshake_partner_id == "a1"
    assert initiator.handshake_until > initiator.handshake_started_at > 0
    assert near.handshake_until > near.handshake_started_at > 0
    assert initiator.facing == "right"
    assert near.facing == "left"


def test_handle_client_message_normalizes_move_and_clears_click_target() -> None:
    player = make_player("a1", "User", 100, 100)
    player.input_state.target_x = 300
    player.input_state.target_y = 220
    server = make_server_with_players(player)

    asyncio.run(server.handle_client_message("a1", {"type": "move", "x": 3, "y": 4}))

    assert player.input_state.move_x == 0.6
    assert player.input_state.move_y == 0.8
    assert player.input_state.target_x is None
    assert player.input_state.target_y is None
    assert player.facing == "down"


def test_handle_client_message_clamps_click_move_to_map_bounds() -> None:
    player = make_player("a1", "User", 100, 100)
    server = make_server_with_players(player)
    server.map_layout = MapLayout(width=320, height=240, obstacles=[], spawn_points=[])

    asyncio.run(server.handle_client_message("a1", {"type": "click_move", "x": 999, "y": -25}))

    assert player.input_state.target_x == 320
    assert player.input_state.target_y == 0.0


def test_handle_client_message_sanitizes_chat_and_broadcasts_raw_event() -> None:
    player = make_player("a1", "User", 100, 100)
    server = make_server_with_players(player)
    events: list[dict[str, object]] = []

    async def fake_broadcast(payload: dict[str, object]) -> None:
        events.append(payload)

    server.broadcast_event = fake_broadcast  # type: ignore[method-assign]
    long_text = ("hello\n" * 30).strip()

    asyncio.run(server.handle_client_message("a1", {"type": "chat", "text": long_text}))

    assert "\n" not in player.chat_text
    assert len(player.chat_text) <= 80
    assert player.chat_text == events[0]["text"]
    assert events[0]["type"] == "chat"
    assert events[0]["player_id"] == "a1"


def test_handle_client_message_triggers_glow_and_broadcasts_event() -> None:
    player = make_player("a1", "User", 100, 100)
    server = make_server_with_players(player)
    events: list[dict[str, object]] = []

    async def fake_broadcast(payload: dict[str, object]) -> None:
        events.append(payload)

    server.broadcast_event = fake_broadcast  # type: ignore[method-assign]

    asyncio.run(server.handle_client_message("a1", {"type": "toggle_glow"}))

    assert player.glow_active is True
    assert events == [
        {
            "type": "glow",
            "player_id": "a1",
            "name": "User",
            "active": True,
        }
    ]


def test_compute_velocity_clears_target_when_player_arrives() -> None:
    player = make_player("a1", "User", 100, 100)
    player.input_state.target_x = 105
    player.input_state.target_y = 105
    server = make_server_with_players(player)

    velocity = server.compute_velocity(player)

    assert velocity == (0.0, 0.0)
    assert player.input_state.target_x is None
    assert player.input_state.target_y is None
