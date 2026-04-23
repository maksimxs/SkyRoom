from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        return


_load_env_file(Path(__file__).resolve().parent / ".env")


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
class ServiceConfig:
    server_name: str = os.getenv("SKYROOM_SERVER_NAME", "My Skyroom Remote")
    public_host: str = os.getenv("SKYROOM_PUBLIC_HOST", "")
    public_port: int = _env_int("SKYROOM_PUBLIC_PORT", _env_int("SKYROOM_PORT", 8765))
    health_port: int = _env_int("SKYROOM_HEALTH_PORT", 8080)


@dataclass(frozen=True)
class EndpointConfig:
    base_url: str = os.getenv("SKYROOM_ENDPOINT_BASE_URL", "https://api.skyroom1337.workers.dev").rstrip("/")
    timeout: float = _env_float("SKYROOM_ENDPOINT_TIMEOUT", 5.0)


NETWORK = NetworkConfig()
SERVER = ServerConfig()
SERVICE = ServiceConfig()
ENDPOINT = EndpointConfig()
