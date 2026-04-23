from __future__ import annotations

from dataclasses import dataclass
import os


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


@dataclass(frozen=True)
class NetworkConfig:
    host: str = os.getenv("SKYROOM_HOST", "127.0.0.1")
    port: int = _env_int("SKYROOM_PORT", 8765)


@dataclass(frozen=True)
class ServerConfig:
    tick_rate: int = _env_int("SKYROOM_TICK_RATE", 30)
    player_speed: float = _env_float("SKYROOM_PLAYER_SPEED", 220.0)
    player_radius: float = _env_float("SKYROOM_PLAYER_RADIUS", 28.0)
    player_foot_radius: float = _env_float("SKYROOM_PLAYER_FOOT_RADIUS", 15.0)
    player_foot_offset_y: float = _env_float("SKYROOM_PLAYER_FOOT_OFFSET_Y", 16.0)
    handshake_distance: float = _env_float("SKYROOM_HANDSHAKE_DISTANCE", 92.0)
    handshake_duration: float = _env_float("SKYROOM_HANDSHAKE_DURATION", 1.8)
    chat_duration: float = _env_float("SKYROOM_CHAT_DURATION", 5.0)


@dataclass(frozen=True)
class ClientConfig:
    width: int = _env_int("SKYROOM_WIDTH", 1280)
    height: int = _env_int("SKYROOM_HEIGHT", 800)
    fps: int = _env_int("SKYROOM_FPS", 60)
    camera_lerp: float = _env_float("SKYROOM_CAMERA_LERP", 0.12)
    move_send_interval: float = _env_float("SKYROOM_MOVE_SEND_INTERVAL", 0.04)


NETWORK = NetworkConfig()
SERVER = ServerConfig()
CLIENT = ClientConfig()
