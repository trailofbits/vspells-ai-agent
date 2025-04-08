"""JSON-RPC Transport Layer

This module provides the transport layer abstraction for JSON-RPC communication.
The transport layer is responsible for sending and receiving raw JSON-RPC messages
over various protocols and channels.

The module defines:
1. A Protocol class that defines the transport interface
2. A concrete implementation for stream-based transport (e.g. stdin/stdout, TCP)

Custom transports can be implemented by creating classes that implement the
JsonRpcTransport protocol.
"""

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class JsonRpcTransport(Protocol):
    """Protocol defining the transport layer interface.

    This protocol must be implemented by all transport classes. It defines
    the basic operations needed to send and receive JSON-RPC messages.

    Example:
        ```python
        class MyTransport(JsonRpcTransport):
            async def receive_message(self) -> str:
                # Implementation for receiving messages
                ...

            async def send_message(self, body: str):
                # Implementation for sending messages
                ...
        ```
    """

    async def receive_message(self) -> str:
        """Receive a complete JSON-RPC message.

        This method should block until a complete message is received.

        Returns:
            str: The complete JSON-RPC message as a string

        Raises:
            TransportError: If there is an error receiving the message
        """
        ...

    async def send_message(self, body: str):
        """Send a JSON-RPC message.

        Args:
            body (str): The JSON-RPC message to send

        Raises:
            TransportError: If there is an error sending the message
        """
        ...


class JsonRpcStreamTransport:
    """Stream-based transport implementation.

    This transport implements the JSON-RPC transport protocol for stream-based
    communication channels like stdin/stdout, Unix sockets or TCP connections.
    It uses a length-prefixed protocol where each message is preceded by headers
    specifying its length.

    Message Format:
        Content-Length: <length>
        Content-Type: application/json; charset=utf-8

        <message>

    Args:
        reader (asyncio.StreamReader): The stream reader
        writer (asyncio.StreamWriter): The stream writer
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Initialize the stream transport.

        Args:
            reader (asyncio.StreamReader): The stream reader
            writer (asyncio.StreamWriter): The stream writer
        """
        self._reader = reader
        self._writer = writer

    async def _read_headers(self) -> dict[str, str]:
        """Read message headers from the stream.

        Headers are read until an empty line is encountered.

        Returns:
            dict[str, str]: Dictionary of header names to values

        Raises:
            EOFError: If the stream ends before headers are complete
        """
        res: dict[str, str] = {}
        row = await self._reader.readuntil(b"\r\n")
        while row != b"\r\n":
            [name, value] = row.split(b":", 1)
            res[name.strip().lower().decode()] = value.strip().decode()
            row = await self._reader.readuntil(b"\r\n")
        return res

    async def receive_message(self) -> str:
        """Receive a complete JSON-RPC message from the stream.

        Messages must be preceded by headers including Content-Length.

        Returns:
            str: The complete JSON-RPC message

        Raises:
            EOFError: If the stream ends before message is complete
        """
        while True:
            headers = await self._read_headers()
            if "content-length" not in headers:
                logger.warning("Received message with no Content-Length header")
                continue

            length = int(headers["content-length"])
            return (await self._reader.readexactly(length)).decode()

    def _write_headers(self, headers: dict[str, str]):
        """Write message headers to the stream.

        Args:
            headers (dict[str, str]): Headers to write
        """
        for key, value in headers.items():
            self._writer.write(f"{key}: {value}\r\n".encode())
        self._writer.write(b"\r\n")

    async def send_message(self, body: str):
        """Send a JSON-RPC message over the stream.

        The message will be preceded by appropriate headers including
        Content-Length and Content-Type.

        Args:
            body (str): The JSON-RPC message to send

        Raises:
            ConnectionError: If there is an error writing to the stream
        """
        contents = body.encode()
        self._write_headers(
            {
                "Content-Type": "application/json;charset=utf-8",
                "Content-Length": str(len(contents)),
            }
        )
        self._writer.write(contents)
        await self._writer.drain()
