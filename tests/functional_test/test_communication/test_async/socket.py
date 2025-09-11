from __future__ import annotations

__all__ = ["AsyncDatagramSocket", "AsyncStreamSocket"]

import asyncio
import contextlib
import dataclasses
import socket
import ssl
import sys
from typing import TYPE_CHECKING, Any, Self, assert_never

from easynetwork.lowlevel._unix_utils import is_unix_socket_family
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import DatagramEndpoint as _AsyncIODatagramEndpoint
from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend
from easynetwork.lowlevel.constants import MAX_DATAGRAM_BUFSIZE

import pytest
import sniffio

from ....tools import is_uvloop_event_loop

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


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _AsyncIODatagram:
    endpoint: _AsyncIODatagramEndpoint


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _TrioDatagram:
    socket: trio.socket.SocketType


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class AsyncDatagramSocket:
    _impl: _AsyncIODatagram | _TrioDatagram

    @classmethod
    async def from_stdlib_socket(
        cls,
        sock: socket.socket,
    ) -> Self:
        if sock.type != socket.SOCK_DGRAM:
            raise ValueError(sock)
        match sniffio.current_async_library():
            case "asyncio":
                from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import create_datagram_endpoint

                if sys.platform != "win32" and is_unix_socket_family(sock.family):
                    from easynetwork.lowlevel.socket import UnixSocketAddress

                    local_addr = UnixSocketAddress.from_raw(sock.getsockname())
                    if (
                        sys.platform == "linux"
                        and local_addr.as_abstract_name()
                        and is_uvloop_event_loop(asyncio.get_running_loop())
                    ):
                        # Addresses received through uvloop transports contains extra NULL bytes because the creation of
                        # the bytes object from the sockaddr_un structure does not take into account the real addrlen.
                        # https://github.com/MagicStack/uvloop/blob/v0.21.0/uvloop/includes/compat.h#L34-L55
                        sock.close()
                        pytest.xfail("uvloop translation of abstract unix sockets to python object is wrong.")

                endpoint = await create_datagram_endpoint(sock=sock)
                return cls(_impl=_AsyncIODatagram(endpoint))
            case "trio":
                import trio

                return cls(_impl=_TrioDatagram(trio.socket.from_stdlib_socket(sock)))
            case lib_name:
                raise NotImplementedError(lib_name)

    @classmethod
    async def open_udp_connection(
        cls,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
        family: int = socket.AF_UNSPEC,
    ) -> Self:
        match sniffio.current_async_library():
            case "asyncio":
                from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import create_datagram_endpoint

                endpoint = await create_datagram_endpoint(
                    remote_addr=(host, port),
                    local_addr=local_address,
                    family=family,
                )
                return cls(_impl=_AsyncIODatagram(endpoint))
            case "trio":
                import trio

                from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

                backend = new_builtin_backend("trio")
                sock = await TrioDNSResolver().create_datagram_connection(
                    backend,
                    host,
                    port,
                    local_address=local_address,
                    family=family,
                )
                return cls(_impl=_TrioDatagram(trio.socket.from_stdlib_socket(sock)))
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
            case _AsyncIODatagram(endpoint):
                endpoint.close_nowait()
            case _TrioDatagram(sock):
                sock.close()
            case _:
                assert_never(self._impl)

    async def aclose(self) -> None:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                await endpoint.aclose()
            case _TrioDatagram(sock):
                import trio

                sock.close()
                await trio.lowlevel.checkpoint()
            case _:
                assert_never(self._impl)

    async def recvfrom(self) -> tuple[bytes, socket._RetAddress]:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                return await endpoint.recvfrom()
            case _TrioDatagram(sock):
                return await sock.recvfrom(MAX_DATAGRAM_BUFSIZE)
            case _:
                assert_never(self._impl)

    async def sendto(self, data: bytes | bytearray | memoryview, address: socket._Address | None) -> None:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                await endpoint.sendto(data, address)
            case _TrioDatagram(sock):
                if address is None:
                    await sock.send(data)
                else:
                    await sock.sendto(data, address)
            case _:
                assert_never(self._impl)

    def getsockname(self) -> socket._RetAddress:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                return endpoint.get_extra_info("sockname")
            case _TrioDatagram(sock):
                return sock.getsockname()
            case _:
                assert_never(self._impl)

    def getpeername(self) -> socket._RetAddress:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                return endpoint.get_extra_info("peername")
            case _TrioDatagram(sock):
                return sock.getpeername()
            case _:
                assert_never(self._impl)
