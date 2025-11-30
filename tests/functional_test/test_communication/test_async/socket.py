from __future__ import annotations

__all__ = ["AsyncDatagramSocket", "AsyncStreamSocket"]

import asyncio
import asyncio.trsock
import contextlib
import dataclasses
import socket
import ssl
import sys
from collections.abc import Iterable
from errno import ECONNRESET
from typing import TYPE_CHECKING, Any, Self, assert_never, overload

from easynetwork.lowlevel._unix_utils import is_unix_socket_family
from easynetwork.lowlevel.api_async.backend._asyncio import _asyncio_utils
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import DatagramEndpoint as _AsyncIODatagramEndpoint
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend
from easynetwork.lowlevel.constants import MAX_DATAGRAM_BUFSIZE
from easynetwork.serializers.tools import GeneratorStreamReader

import sniffio

if TYPE_CHECKING:
    from socket import _RetAddress

    import trio

if sys.platform != "win32":
    from easynetwork.lowlevel.socket import SocketAncillary

    try:
        from socket import CMSG_SPACE
    except ImportError:
        from socket import CMSG_LEN as CMSG_SPACE

    if TYPE_CHECKING:
        from _socket import _CMSGArg

    _MAX_ANCDATA_SIZE = 8192

    async def _asyncio_sock_recvmsg(sock: socket.socket, bufsize: int) -> tuple[bytes, SocketAncillary, _RetAddress]:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data, cmsgs, flags, address = sock.recvmsg(bufsize, CMSG_SPACE(_MAX_ANCDATA_SIZE))
            except (BlockingIOError, InterruptedError):
                pass
            else:
                assert flags == 0, "messages truncated"
                ancillary = SocketAncillary()
                ancillary.update_from_raw(cmsgs)
                return data, ancillary, address
            await _asyncio_utils.wait_until_readable(sock, loop)

    async def _trio_sock_recvmsg(sock: trio.socket.SocketType, bufsize: int) -> tuple[bytes, SocketAncillary, _RetAddress]:
        data, cmsgs, flags, address = await sock.recvmsg(bufsize, CMSG_SPACE(_MAX_ANCDATA_SIZE))
        assert flags == 0, "messages truncated"
        ancillary = SocketAncillary()
        ancillary.update_from_raw(cmsgs)
        return data, ancillary, address


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _AsyncIOStream:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _AsyncIORawStreamSock:
    sock: socket.socket
    _buffered_stream_reader: GeneratorStreamReader = dataclasses.field(init=False, default_factory=GeneratorStreamReader)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        loop = asyncio.get_running_loop()
        return await loop.sock_sendall(self.sock, data)

    async def _recv_from_stream(self, bufsize: int) -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.sock_recv(self.sock, bufsize)

    async def read(self, bufsize: int) -> bytes:
        with contextlib.closing(self._buffered_stream_reader.read(bufsize)) as generator:
            try:
                next(generator)
                while True:
                    data = await self._recv_from_stream(bufsize)
                    if not data:
                        return b""
                    generator.send(data)
            except StopIteration as exc:
                return exc.value

    async def readline(self) -> bytes:
        with contextlib.closing(self._buffered_stream_reader.read_until(b"\n", limit=65536)) as generator:
            try:
                next(generator)
                while True:
                    data = await self._recv_from_stream(1024)
                    if not data:
                        generator.close()
                        return self._buffered_stream_reader.read_all()
                    generator.send(data)
            except StopIteration as exc:
                return exc.value

    if sys.platform != "win32":

        async def recvmsg(self, bufsize: int) -> tuple[bytes, SocketAncillary]:
            with contextlib.closing(self._buffered_stream_reader.read(bufsize)) as generator:
                try:
                    next(generator)
                except StopIteration as exc:
                    return exc.value, SocketAncillary()
                else:
                    data, ancillary, _ = await _asyncio_sock_recvmsg(self.sock, bufsize)
                    return data, ancillary


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _TrioStream:
    stream: trio.SocketStream | trio.SSLStream[trio.SocketStream]
    ssl_shutdown_timeout: float | None = None
    _buffered_stream_reader: GeneratorStreamReader = dataclasses.field(init=False, default_factory=GeneratorStreamReader)

    async def _recv_from_stream(self, bufsize: int) -> bytes:
        from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

        try:
            with convert_trio_resource_errors(broken_resource_errno=ECONNRESET):
                data = await self.stream.receive_some(bufsize)
        except ssl.SSLEOFError:
            data = b""
        else:
            data = bytes(data)
        return data

    async def read(self, bufsize: int) -> bytes:
        with contextlib.closing(self._buffered_stream_reader.read(bufsize)) as generator:
            try:
                next(generator)
                while True:
                    data = await self._recv_from_stream(bufsize)
                    if not data:
                        return b""
                    generator.send(data)
            except StopIteration as exc:
                return exc.value

    async def readline(self) -> bytes:
        with contextlib.closing(self._buffered_stream_reader.read_until(b"\n", limit=65536)) as generator:
            try:
                next(generator)
                while True:
                    data = await self._recv_from_stream(1024)
                    if not data:
                        generator.close()
                        return self._buffered_stream_reader.read_all()
                    generator.send(data)
            except StopIteration as exc:
                return exc.value

    if sys.platform != "win32":

        async def recvmsg(self, bufsize: int) -> tuple[bytes, SocketAncillary]:
            import trio

            match self.stream:
                case trio.SocketStream(socket=sock):
                    with contextlib.closing(self._buffered_stream_reader.read(bufsize)) as generator:
                        try:
                            next(generator)
                        except StopIteration as exc:
                            return exc.value, SocketAncillary()
                        else:
                            data, ancillary, _ = await _trio_sock_recvmsg(sock, bufsize)
                            return data, ancillary
                case _:
                    raise NotImplementedError


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class AsyncStreamSocket:
    _impl: _AsyncIOStream | _AsyncIORawStreamSock | _TrioStream
    _backend: AsyncBackend
    _read_timeout: float | None = dataclasses.field(init=False, default=None)

    @classmethod
    async def from_connected_stdlib_socket(
        cls,
        sock: socket.socket,
    ) -> Self:
        match sniffio.current_async_library():
            case "asyncio":
                if is_unix_socket_family(sock.family):
                    return cls(_impl=_AsyncIORawStreamSock(sock), _backend=new_builtin_backend("asyncio"))
                reader, writer = await asyncio.open_connection(sock=sock)
                return cls(_impl=_AsyncIOStream(reader, writer), _backend=new_builtin_backend("asyncio"))
            case "trio":
                import trio

                stream = trio.SocketStream(trio.socket.from_stdlib_socket(sock))
                return cls(_impl=_TrioStream(stream), _backend=new_builtin_backend("trio"))
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
        ssl_shutdown_timeout: float | None = None,
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
                    ssl_shutdown_timeout=ssl_shutdown_timeout,
                )
                return cls(_impl=_AsyncIOStream(reader, writer), _backend=backend)
            case "trio":
                import trio

                from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

                backend = new_builtin_backend("trio")
                sock = await TrioDNSResolver().create_stream_connection(backend, host, port)

                stream: trio.SocketStream | trio.SSLStream[trio.SocketStream]
                stream = trio.SocketStream(trio.socket.from_stdlib_socket(sock))
                if ssl is None:
                    return cls(_impl=_TrioStream(stream), _backend=backend)
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
                        return cls(_impl=_TrioStream(stream, ssl_shutdown_timeout=ssl_shutdown_timeout), _backend=backend)
                    raise AssertionError("Expected code to be unreachable.")
                except BaseException:
                    await trio.aclose_forcefully(stream)
                    raise
            case lib_name:
                raise NotImplementedError(lib_name)

    if sys.platform != "win32":

        @classmethod
        async def open_unix_connection(
            cls,
            path: str | bytes,
            *,
            local_path: str | bytes | None = None,
        ) -> Self:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                if local_path is not None:
                    sock.bind(local_path)

                sock.setblocking(False)
                match sniffio.current_async_library():
                    case "asyncio":
                        event_loop = asyncio.get_running_loop()
                        await event_loop.sock_connect(sock, path)

                        return cls(_impl=_AsyncIORawStreamSock(sock), _backend=new_builtin_backend("asyncio"))
                    case "trio":
                        import trio

                        stream = trio.SocketStream(trio.socket.from_stdlib_socket(sock))
                        await stream.socket.connect(path)
                        return cls(_impl=_TrioStream(stream), _backend=new_builtin_backend("trio"))
                    case lib_name:
                        raise NotImplementedError(lib_name)
            except BaseException:
                sock.close()
                raise

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            match self._impl:
                case _AsyncIOStream(writer=writer):
                    writer.close()
                case _AsyncIORawStreamSock(sock):
                    sock.close()
                case _TrioStream(trio_stream):
                    import trio

                    if isinstance(trio_stream, trio.SSLStream):
                        trio_stream = trio_stream.transport_stream
                    trio_stream.socket.close()
                case _:
                    assert_never(self._impl)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        del args
        await self.aclose()

    def backend(self) -> AsyncBackend:
        return self._backend

    def set_read_timeout(self, timeout: float | None) -> None:
        object.__setattr__(self, "_read_timeout", timeout)

    async def aclose(self) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                writer.close()
                with contextlib.suppress(ConnectionError):
                    await writer.wait_closed()
            case _AsyncIORawStreamSock(sock):
                sock.close()
                await asyncio.sleep(0)
            case _TrioStream(trio_stream, ssl_shutdown_timeout=ssl_shutdown_timeout):
                import trio

                with contextlib.nullcontext() if ssl_shutdown_timeout is None else trio.move_on_after(ssl_shutdown_timeout):
                    await trio_stream.aclose()
            case _:
                assert_never(self._impl)

    async def recv(self, bufsize: int) -> bytes:
        with self._backend.timeout(t) if (t := self._read_timeout) is not None else contextlib.nullcontext():
            match self._impl:
                case _AsyncIOStream(reader=reader):
                    return await reader.read(bufsize)
                case _AsyncIORawStreamSock() as reader:
                    return await reader.read(bufsize)
                case _TrioStream() as reader:
                    return await reader.read(bufsize)
                case _:
                    assert_never(self._impl)

    async def readline(self) -> bytes:
        with self._backend.timeout(t) if (t := self._read_timeout) is not None else contextlib.nullcontext():
            match self._impl:
                case _AsyncIOStream(reader=reader):
                    return await reader.readline()
                case _AsyncIORawStreamSock() as reader:
                    return await reader.readline()
                case _TrioStream() as reader:
                    return await reader.readline()
                case _:
                    assert_never(self._impl)

    if sys.platform != "win32":

        async def recvmsg(self, bufsize: int = 1024) -> tuple[bytes, SocketAncillary]:
            with self._backend.timeout(t) if (t := self._read_timeout) is not None else contextlib.nullcontext():
                match self._impl:
                    case _AsyncIORawStreamSock() | _TrioStream() as reader:
                        return await reader.recvmsg(bufsize)
                    case _:
                        raise NotImplementedError

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                writer.write(data)
                await writer.drain()
            case _AsyncIORawStreamSock() as writer:
                await writer.send_all(data)
            case _TrioStream(trio_stream):
                from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

                with convert_trio_resource_errors(broken_resource_errno=ECONNRESET):
                    await trio_stream.send_all(data)
            case _:
                assert_never(self._impl)

    if sys.platform != "win32":

        async def sendmsg(self, data: Iterable[bytes | bytearray | memoryview], ancdata: Iterable[_CMSGArg]) -> None:
            data = list(data)
            ancdata = list(ancdata)
            match self._impl:
                case _AsyncIORawStreamSock(sock):
                    loop = asyncio.get_running_loop()
                    while True:
                        try:
                            sock.sendmsg(data, ancdata)
                        except (BlockingIOError, InterruptedError):
                            pass
                        else:
                            return
                        await _asyncio_utils.wait_until_writable(sock, loop)
                case _TrioStream(trio_stream):
                    import trio

                    if isinstance(trio_stream, trio.SSLStream):
                        raise NotImplementedError

                    await trio_stream.socket.sendmsg(data, ancdata)
                case _:
                    raise NotImplementedError

    async def send_eof(self) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                writer.write_eof()
                await asyncio.sleep(0)
            case _AsyncIORawStreamSock(sock):
                sock.shutdown(socket.SHUT_WR)
                await asyncio.sleep(0)
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    raise NotImplementedError

                from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

                with convert_trio_resource_errors(broken_resource_errno=ECONNRESET):
                    await trio_stream.send_eof()
            case _:
                assert_never(self._impl)

    def getsockname(self) -> socket._RetAddress:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                return writer.get_extra_info("sockname")
            case _AsyncIORawStreamSock(sock):
                return sock.getsockname()
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
            case _AsyncIORawStreamSock(sock):
                return sock.getpeername()
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    trio_stream = trio_stream.transport_stream
                return trio_stream.socket.getpeername()
            case _:
                assert_never(self._impl)

    @overload
    def getsockopt(self, level: int, optname: int, /) -> int: ...

    @overload
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes: ...

    def getsockopt(self, *args: Any) -> int | bytes:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                trsock: asyncio.trsock.TransportSocket = writer.get_extra_info("socket")
                return trsock.getsockopt(*args)
            case _AsyncIORawStreamSock(sock):
                return sock.getsockopt(*args)
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    trio_stream = trio_stream.transport_stream
                return trio_stream.socket.getsockopt(*args)
            case _:
                assert_never(self._impl)

    @overload
    def setsockopt(self, level: int, optname: int, value: int | bytes, /) -> None: ...

    @overload
    def setsockopt(self, level: int, optname: int, value: None, optlen: int, /) -> None: ...

    def setsockopt(self, *args: Any) -> None:
        match self._impl:
            case _AsyncIOStream(writer=writer):
                trsock: asyncio.trsock.TransportSocket = writer.get_extra_info("socket")
                trsock.setsockopt(*args)
            case _AsyncIORawStreamSock(sock):
                sock.setsockopt(*args)
            case _TrioStream(trio_stream):
                import trio

                if isinstance(trio_stream, trio.SSLStream):
                    trio_stream = trio_stream.transport_stream
                trio_stream.socket.setsockopt(*args)
            case _:
                assert_never(self._impl)


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _AsyncIODatagram:
    endpoint: _AsyncIODatagramEndpoint


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _AsyncIORawDatagramSock:
    sock: socket.socket


@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class _TrioDatagram:
    socket: trio.socket.SocketType


@dataclasses.dataclass(kw_only=True, eq=False, frozen=True, slots=True)
class AsyncDatagramSocket:
    _impl: _AsyncIODatagram | _AsyncIORawDatagramSock | _TrioDatagram
    _backend: AsyncBackend
    _read_timeout: float | None = dataclasses.field(init=False, default=None)

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

                if is_unix_socket_family(sock.family):
                    return cls(_impl=_AsyncIORawDatagramSock(sock), _backend=new_builtin_backend("asyncio"))

                endpoint = await create_datagram_endpoint(sock=sock)
                return cls(_impl=_AsyncIODatagram(endpoint), _backend=new_builtin_backend("asyncio"))
            case "trio":
                import trio

                return cls(_impl=_TrioDatagram(trio.socket.from_stdlib_socket(sock)), _backend=new_builtin_backend("trio"))
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
                return cls(_impl=_AsyncIODatagram(endpoint), _backend=new_builtin_backend("asyncio"))
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
                return cls(_impl=_TrioDatagram(trio.socket.from_stdlib_socket(sock)), _backend=backend)
            case lib_name:
                raise NotImplementedError(lib_name)

    if sys.platform != "win32":

        @classmethod
        async def open_unix_connection(
            cls,
            path: str | bytes,
            *,
            local_path: str | bytes | None = None,
        ) -> Self:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                if local_path is not None:
                    sock.bind(local_path)

                sock.setblocking(False)
                match sniffio.current_async_library():
                    case "asyncio":
                        event_loop = asyncio.get_running_loop()
                        await event_loop.sock_connect(sock, path)
                        return cls(_impl=_AsyncIORawDatagramSock(sock), _backend=new_builtin_backend("asyncio"))
                    case "trio":
                        import trio

                        from easynetwork.lowlevel.api_async.backend._trio._trio_utils import connect_sock_to_resolved_address

                        backend = new_builtin_backend("trio")
                        await connect_sock_to_resolved_address(sock, path)
                        return cls(_impl=_TrioDatagram(trio.socket.from_stdlib_socket(sock)), _backend=backend)
                    case lib_name:
                        raise NotImplementedError(lib_name)
            except BaseException:
                sock.close()
                raise

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            match self._impl:
                case _AsyncIODatagram(endpoint):
                    endpoint.close_nowait()
                case _AsyncIORawDatagramSock(sock):
                    sock.close()
                case _TrioDatagram(sock):
                    sock.close()
                case _:
                    assert_never(self._impl)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        del args
        await self.aclose()

    def backend(self) -> AsyncBackend:
        return self._backend

    def set_read_timeout(self, timeout: float | None) -> None:
        object.__setattr__(self, "_read_timeout", timeout)

    async def aclose(self) -> None:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                await endpoint.aclose()
            case _AsyncIORawDatagramSock(sock):
                sock.close()
                await asyncio.sleep(0)
            case _TrioDatagram(sock):
                import trio

                sock.close()
                await trio.lowlevel.checkpoint()
            case _:
                assert_never(self._impl)

    async def recvfrom(self) -> tuple[bytes, socket._RetAddress]:
        with self._backend.timeout(t) if (t := self._read_timeout) is not None else contextlib.nullcontext():
            match self._impl:
                case _AsyncIODatagram(endpoint):
                    return await endpoint.recvfrom()
                case _AsyncIORawDatagramSock(sock):
                    loop = asyncio.get_running_loop()
                    # https://github.com/MagicStack/uvloop/issues/561
                    while True:
                        try:
                            return sock.recvfrom(MAX_DATAGRAM_BUFSIZE)
                        except (BlockingIOError, InterruptedError):
                            pass
                        await _asyncio_utils.wait_until_readable(sock, loop)
                case _TrioDatagram(sock):
                    return await sock.recvfrom(MAX_DATAGRAM_BUFSIZE)
                case _:
                    assert_never(self._impl)

    if sys.platform != "win32":

        async def recvmsg(self) -> tuple[bytes, SocketAncillary, _RetAddress]:
            with self._backend.timeout(t) if (t := self._read_timeout) is not None else contextlib.nullcontext():
                match self._impl:
                    case _AsyncIORawDatagramSock(sock):
                        return await _asyncio_sock_recvmsg(sock, MAX_DATAGRAM_BUFSIZE)
                    case _TrioDatagram(sock):
                        return await _trio_sock_recvmsg(sock, MAX_DATAGRAM_BUFSIZE)
                    case _:
                        raise NotImplementedError

    async def sendto(self, data: bytes | bytearray | memoryview, address: socket._Address | None) -> None:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                await endpoint.sendto(data, address)
            case _AsyncIORawDatagramSock(sock):
                loop = asyncio.get_running_loop()
                # https://github.com/MagicStack/uvloop/issues/561
                while True:
                    try:
                        if address is None:
                            sock.send(data)
                        else:
                            sock.sendto(data, address)
                    except (BlockingIOError, InterruptedError):
                        pass
                    else:
                        return
                    await _asyncio_utils.wait_until_writable(sock, loop)
            case _TrioDatagram(sock):
                if address is None:
                    await sock.send(data)
                else:
                    await sock.sendto(data, address)
            case _:
                assert_never(self._impl)

    if sys.platform != "win32":

        async def sendmsg(
            self,
            data: Iterable[bytes | bytearray | memoryview],
            ancdata: Iterable[_CMSGArg],
            address: socket._Address | None,
        ) -> None:
            data = list(data)
            ancdata = list(ancdata)
            match self._impl:
                case _AsyncIORawDatagramSock(sock):
                    loop = asyncio.get_running_loop()
                    while True:
                        try:
                            sock.sendmsg(data, ancdata, 0, address)
                        except (BlockingIOError, InterruptedError):
                            pass
                        else:
                            return
                        await _asyncio_utils.wait_until_writable(sock, loop)
                case _TrioDatagram(sock):
                    await sock.sendmsg(data, ancdata, 0, address)
                case _:
                    raise NotImplementedError

    def getsockname(self) -> socket._RetAddress:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                return endpoint.get_extra_info("sockname")
            case _AsyncIORawDatagramSock(sock):
                return sock.getsockname()
            case _TrioDatagram(sock):
                return sock.getsockname()
            case _:
                assert_never(self._impl)

    def getpeername(self) -> socket._RetAddress:
        match self._impl:
            case _AsyncIODatagram(endpoint):
                return endpoint.get_extra_info("peername")
            case _AsyncIORawDatagramSock(sock):
                return sock.getpeername()
            case _TrioDatagram(sock):
                return sock.getpeername()
            case _:
                assert_never(self._impl)
                assert_never(self._impl)
