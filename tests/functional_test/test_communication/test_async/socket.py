from __future__ import annotations

__all__ = ["AsyncStreamSocket"]

import asyncio
import contextlib
import dataclasses
import socket
import ssl
from typing import TYPE_CHECKING, Any, Self, assert_never

from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend

import sniffio

if TYPE_CHECKING:
    import trio


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _AsyncIOStream:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _TrioStream:
    stream: trio.SocketStream | trio.SSLStream[trio.SocketStream]


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class AsyncStreamSocket:
    _impl: _AsyncIOStream | _TrioStream

    @classmethod
    async def from_connected_stdlib_socket(
        cls,
        sock: socket.socket,
    ) -> Self:
        match sniffio.current_async_library():
            case "asyncio":
                reader, writer = await asyncio.open_connection(sock=sock)
                return cls(_impl=_AsyncIOStream(reader, writer))
            case "trio":
                import trio

                stream = trio.SocketStream(trio.socket.from_stdlib_socket(sock))
                return cls(_impl=_TrioStream(stream))
            case lib_name:
                raise NotImplementedError(lib_name)

    @classmethod
    async def open_tcp_connection(
        cls,
        host: str,
        port: int,
        *,
        ssl: ssl.SSLContext | None = None,
        server_hostname: str | None = None,
        ssl_handshake_timeout: float | None = None,
    ) -> Self:
        match sniffio.current_async_library():
            case "asyncio":
                from easynetwork.lowlevel.api_async.backend._asyncio.dns_resolver import AsyncIODNSResolver

                backend = new_builtin_backend("asyncio")
                sock = await AsyncIODNSResolver().create_stream_connection(backend, host, port)
                reader, writer = await asyncio.open_connection(
                    sock=sock,
                    ssl=ssl,
                    server_hostname=server_hostname,
                    ssl_handshake_timeout=ssl_handshake_timeout,
                )
                return cls(_impl=_AsyncIOStream(reader, writer))
            case "trio":
                import trio

                stream: trio.SocketStream | trio.SSLStream[trio.SocketStream]
                stream = await trio.open_tcp_stream(host, port)
                if ssl is None:
                    return cls(_impl=_TrioStream(stream))
                try:
                    stream = trio.SSLStream(
                        stream,
                        ssl,
                        server_side=False,
                        server_hostname=host if server_hostname is None else server_hostname,
                    )
                    with (
                        trio.fail_after(ssl_handshake_timeout) if ssl_handshake_timeout is not None else contextlib.nullcontext()
                    ):
                        await stream.do_handshake()
                        return cls(_impl=_TrioStream(stream))
                    raise AssertionError("Expected code to be unreachable.")
                except BaseException:
                    await trio.aclose_forcefully(stream)
                    raise
            case lib_name:
                raise NotImplementedError(lib_name)

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        del args
        await self.aclose()

    def close(self) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                writer.close()
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    trio_stream = trio_stream.transport_stream
                trio_stream.socket.close()
            case _:
                assert_never(self._impl)

    async def aclose(self) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                writer.close()
                await writer.wait_closed()
            case _TrioStream(trio_stream):
                await trio_stream.aclose()
            case _:
                assert_never(self._impl)

    async def recv(self, bufsize: int) -> bytes:
        match self._impl:
            case _AsyncIOStream(reader=reader):
                return await reader.read(bufsize)
            case _TrioStream(trio_stream):
                return bytes(await trio_stream.receive_some(bufsize))
            case _:
                assert_never(self._impl)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                writer.write(data)
                await writer.drain()
            case _TrioStream(trio_stream):
                await trio_stream.send_all(data)
            case _:
                assert_never(self._impl)

    async def send_eof(self) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                writer.write_eof()
                await asyncio.sleep(0)
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    raise NotImplementedError
                await trio_stream.send_eof()
            case _:
                assert_never(self._impl)

    def getsockname(self) -> socket._RetAddress:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                return writer.get_extra_info("sockname")
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    trio_stream = trio_stream.transport_stream
                return trio_stream.socket.getsockname()
            case _:
                assert_never(self._impl)

    def getpeername(self) -> socket._RetAddress:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                return writer.get_extra_info("peername")
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    trio_stream = trio_stream.transport_stream
                return trio_stream.socket.getpeername()
            case _:
                assert_never(self._impl)
