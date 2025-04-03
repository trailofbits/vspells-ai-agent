from typing import Protocol
import logging
import asyncio

logger = logging.getLogger(__name__)


class JsonRpcTransport(Protocol):
    async def receive_message(self) -> str: ...
    async def send_message(self, body: str): ...


class JsonRpcStreamTransport:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer

    async def _read_headers(self) -> dict[str, str]:
        res: dict[str, str] = {}
        row = await self._reader.readuntil(b"\r\n")
        while row != b"\r\n":
            [name, value] = row.split(b":", 1)
            res[name.strip().lower().decode()] = value.strip().decode()
            row = await self._reader.readuntil(b"\r\n")
        return res

    async def receive_message(self) -> str:
        while True:
            headers = await self._read_headers()
            if "content-length" not in headers:
                logger.warning("Received message with no Content-Length header")
                continue

            length = int(headers["content-length"])
            return await self._reader.readexactly(length)

    def _write_headers(self, headers: dict[str, str]):
        for key, value in headers.items():
            self._writer.write(f"{key}: {value}\r\n".encode())
        self._writer.write(b"\r\n")

    async def send_message(self, body: str):
        contents = body.encode()
        self._write_headers(
            {
                "Content-Type": "application/json;charset=utf-8",
                "Content-Length": str(len(contents)),
            }
        )
        self._writer.write(contents)
        await self._writer.drain()
