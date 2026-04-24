from __future__ import annotations

import asyncio

import pytest

from skyroom.protocol import ProtocolError, decode_message, encode_message, read_message, send_message


class FakeWriter:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.drained = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        self.drained = True


def test_encode_message_uses_compact_json_and_newline() -> None:
    assert encode_message({"type": "hello", "name": "User"}) == b'{"type":"hello","name":"User"}\n'


def test_decode_message_rejects_invalid_json() -> None:
    with pytest.raises(ProtocolError, match="Invalid JSON payload"):
        decode_message(b"{oops}\n")


def test_decode_message_rejects_non_object_payloads() -> None:
    with pytest.raises(ProtocolError, match="Protocol payload must be an object"):
        decode_message(b'["not","an","object"]\n')


def test_read_message_reads_single_json_line() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b'{"type":"ping"}\n')
    reader.feed_eof()

    assert asyncio.run(read_message(reader)) == {"type": "ping"}


def test_read_message_raises_when_socket_is_closed() -> None:
    async def run() -> None:
        reader = asyncio.StreamReader()
        reader.feed_eof()

        with pytest.raises(ConnectionError, match="Socket closed"):
            await read_message(reader)

    asyncio.run(run())


def test_send_message_writes_encoded_payload_and_drains() -> None:
    writer = FakeWriter()

    asyncio.run(send_message(writer, {"type": "pong", "server": "skyroom"}))

    assert bytes(writer.buffer) == b'{"type":"pong","server":"skyroom"}\n'
    assert writer.drained is True
