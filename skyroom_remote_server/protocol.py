from __future__ import annotations

import asyncio
import json
from typing import Any


class ProtocolError(RuntimeError):
    pass


def encode_message(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(raw_line: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw_line.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProtocolError("Invalid JSON payload") from exc
    if not isinstance(data, dict):
        raise ProtocolError("Protocol payload must be an object")
    return data


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    raw_line = await reader.readline()
    if not raw_line:
        raise ConnectionError("Socket closed")
    return decode_message(raw_line)


async def send_message(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    writer.write(encode_message(payload))
    await writer.drain()
