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
    host: str = os.getenv("SKYROOM_HOST", "0.0.0.0")
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
class RegistryConfig:
    server_name: str = os.getenv("SKYROOM_SERVER_NAME", "Skyroom Remote")
    public_host: str = os.getenv("SKYROOM_PUBLIC_HOST", "")
    public_port: int = _env_int("SKYROOM_PUBLIC_PORT", _env_int("SKYROOM_PORT", 8765))
    registry_url: str = os.getenv("SKYROOM_REGISTRY_URL", "").strip()
    shared_secret: str = os.getenv("SKYROOM_REGISTRY_SHARED_SECRET", "").strip()
    heartbeat_interval: float = _env_float("SKYROOM_REGISTRY_HEARTBEAT", 60.0)


NETWORK = NetworkConfig()
SERVER = ServerConfig()
REGISTRY = RegistryConfig()
