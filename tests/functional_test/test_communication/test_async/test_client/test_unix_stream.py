from __future__ import annotations

import sys

if sys.platform != "win32":
    import asyncio
    import contextlib
    import os
    from collections.abc import AsyncIterator
    from socket import socket as Socket
    from typing import TYPE_CHECKING

    from easynetwork.clients.async_unix_stream import AsyncUnixStreamClient
    from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
    from easynetwork.lowlevel.socket import SocketProxy
    from easynetwork.protocol import AnyStreamProtocolType

    import pytest
    import pytest_asyncio

    from .....fixtures.trio import trio_fixture
    from .....tools import AsyncEventScheduling
    from .._utils import delay
    from ..socket import AsyncStreamSocket
    from .common import sock_readline

    if TYPE_CHECKING:
        import trio

        from .....pytest_plugins.unix_sockets import UnixSocketPathFactory

    @pytest.mark.flaky(retries=3, delay=0.1)
    class _BaseTestAsyncUnixStreamClient:
        @pytest.fixture
        @staticmethod
        def is_buffered_protocol(stream_protocol: AnyStreamProtocolType[str, str]) -> bool:
            from easynetwork.protocol import BufferedStreamProtocol

            return isinstance(stream_protocol, BufferedStreamProtocol)

        async def test____aclose____idempotent(self, client: AsyncUnixStreamClient[str, str]) -> None:
            assert not client.is_closing()
            await client.aclose()
            assert client.is_closing()
            await client.aclose()
            assert client.is_closing()

        async def test____send_packet____default(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await client.send_packet("ABCDEF")
            assert await sock_readline(server) == b"ABCDEF\n"

        async def test____send_packet____closed_client(self, client: AsyncUnixStreamClient[str, str]) -> None:
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.send_packet("ABCDEF")

        @pytest.mark.parametrize("stream_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
        async def test____send_packet____protocol_crashed(
            self,
            client: AsyncUnixStreamClient[str, str],
        ) -> None:
            with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$"):
                await client.send_packet("ABCDEF")

        async def test____send_eof____close_write_stream(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await client.send_eof()
            assert await sock_readline(server) == b""
            with pytest.raises(RuntimeError):
                await client.send_packet("ABC")
            await server.send_all(b"ABCDEF\n")
            assert await client.recv_packet() == "ABCDEF"

        async def test____send_eof____closed_client(
            self,
            client: AsyncUnixStreamClient[str, str],
        ) -> None:
            await client.aclose()
            await client.send_eof()

        async def test____send_eof____idempotent(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await client.send_eof()
            assert await sock_readline(server) == b""
            await client.send_eof()
            await client.send_eof()

        async def test____recv_packet____default(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await server.send_all(b"ABCDEF\n")
            assert await client.recv_packet() == "ABCDEF"

        async def test____recv_packet____partial(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            async with client.backend().create_task_group() as tg:
                await server.send_all(b"ABC")
                tg.start_soon(delay, 0.5, server.send_all, b"DEF\n")
                assert await client.recv_packet() == "ABCDEF"

        async def test____recv_packet____buffer(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await server.send_all(b"A\nB\nC\nD\n")
            assert await client.recv_packet() == "A"
            assert await client.recv_packet() == "B"
            assert await client.recv_packet() == "C"
            assert await client.recv_packet() == "D"
            await server.send_all(b"E\nF\nG\nH\nI")
            assert await client.recv_packet() == "E"
            assert await client.recv_packet() == "F"
            assert await client.recv_packet() == "G"
            assert await client.recv_packet() == "H"

            async with client.backend().create_task_group() as tg:
                task = await tg.start(client.recv_packet)
                assert not task.done()
                await server.send_all(b"J\n")

            assert await task.join() == "IJ"

        async def test____recv_packet____eof____closed_remote(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            server.close()
            with pytest.raises(ConnectionAbortedError):
                await client.recv_packet()

        async def test____recv_packet____eof____shutdown_write_only(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await server.send_eof()
            with pytest.raises(ConnectionAbortedError):
                await client.recv_packet()

            await client.send_packet("ABCDEF")
            assert await sock_readline(server) == b"ABCDEF\n"

        async def test____recv_packet____client_close_error(
            self,
            client: AsyncUnixStreamClient[str, str],
        ) -> None:
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.recv_packet()

        async def test____recv_packet____client_close_while_waiting(
            self,
            client: AsyncUnixStreamClient[str, str],
        ) -> None:
            async with client.backend().create_task_group() as tg:
                await tg.start(delay, 0.5, client.aclose)
                with client.backend().timeout(5), pytest.raises(ClientClosedError):
                    assert await client.recv_packet()

        async def test____recv_packet____invalid_data(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await server.send_all("\u00e9\nvalid\n".encode("latin-1"))
            with pytest.raises(StreamProtocolParseError):
                await client.recv_packet()
            assert await client.recv_packet() == "valid"

        @pytest.mark.parametrize(
            "stream_protocol",
            [
                pytest.param("invalid", id="serializer_crash"),
                pytest.param("invalid_buffered", id="buffered_serializer_crash"),
            ],
            indirect=True,
        )
        async def test____recv_packet____protocol_crashed(
            self,
            is_buffered_protocol: bool,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            expected_pattern: str
            if is_buffered_protocol:
                expected_pattern = r"^protocol\.build_packet_from_buffer\(\) crashed$"
            else:
                expected_pattern = r"^protocol\.build_packet_from_chunks\(\) crashed$"
            await server.send_all(b"ABCDEF\n")
            with pytest.raises(RuntimeError, match=expected_pattern):
                await client.recv_packet()

        async def test____iter_received_packets____yields_available_packets_until_eof(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await server.send_all(b"A\nB\nC\nD\nE\nF")
            AsyncEventScheduling.call_soon(server.close)
            assert [p async for p in client.iter_received_packets(timeout=None)] == ["A", "B", "C", "D", "E"]

        async def test____iter_received_packets____yields_available_packets_until_close(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            event_loop = asyncio.get_running_loop()

            await event_loop.sock_sendall(server, b"A\nB\nC\nD\nE\n")
            async with client.backend().create_task_group() as tg:
                await tg.start(delay, 0.5, client.aclose)
                await tg.start(delay, 0.1, event_loop.sock_sendall, server, b"F\n")
                assert [p async for p in client.iter_received_packets(timeout=None)] == ["A", "B", "C", "D", "E", "F"]

        async def test____iter_received_packets____yields_available_packets_until_timeout(
            self,
            client: AsyncUnixStreamClient[str, str],
            server: AsyncStreamSocket,
        ) -> None:
            await server.send_all(b"A\nB\nC\nD\nE\n")
            await server.send_all(b"F\n")
            assert [p async for p in client.iter_received_packets(timeout=1)] == ["A", "B", "C", "D", "E", "F"]

        async def test____get_local_name____consistency(
            self,
            client: AsyncUnixStreamClient[str, str],
        ) -> None:
            from easynetwork.lowlevel.socket import UnixSocketAddress

            address = client.get_local_name()
            assert isinstance(address, UnixSocketAddress)
            assert address.as_raw() == client.socket.getsockname()

        async def test____get_peer_name____consistency(
            self,
            client: AsyncUnixStreamClient[str, str],
        ) -> None:
            from easynetwork.lowlevel.socket import UnixSocketAddress

            address = client.get_peer_name()
            assert isinstance(address, UnixSocketAddress)
            assert address.as_raw() == client.socket.getpeername()

    @pytest.mark.asyncio
    class TestAsyncUnixStreamClientWithAsyncIO(_BaseTestAsyncUnixStreamClient):
        @pytest_asyncio.fixture
        @staticmethod
        async def server(unix_socket_pair: tuple[Socket, Socket]) -> AsyncIterator[AsyncStreamSocket]:
            async with await AsyncStreamSocket.from_connected_stdlib_socket(unix_socket_pair[0]) as server:
                yield server

        @pytest_asyncio.fixture
        @staticmethod
        async def client(
            unix_socket_pair: tuple[Socket, Socket],
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> AsyncIterator[AsyncUnixStreamClient[str, str]]:
            async with AsyncUnixStreamClient(unix_socket_pair[1], stream_protocol, "asyncio") as client:
                assert client.is_connected()
                yield client

    @pytest.mark.feature_trio(async_test_auto_mark=True)
    class TestAsyncUnixStreamClientWithTrio(_BaseTestAsyncUnixStreamClient):
        @trio_fixture
        @staticmethod
        async def server(unix_socket_pair: tuple[Socket, Socket]) -> AsyncIterator[AsyncStreamSocket]:
            async with await AsyncStreamSocket.from_connected_stdlib_socket(unix_socket_pair[0]) as server:
                yield server

        @trio_fixture
        @staticmethod
        async def client(
            unix_socket_pair: tuple[Socket, Socket],
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> AsyncIterator[AsyncUnixStreamClient[str, str]]:
            async with AsyncUnixStreamClient(unix_socket_pair[1], stream_protocol, "trio") as client:
                assert client.is_connected()
                yield client

    class _BaseTestAsyncUnixStreamClientConnection:

        async def test____dunder_init____connect_to_server(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with AsyncUnixStreamClient(remote_address, stream_protocol) as client:
                assert client.is_connected()
                await client.send_packet("Test")
                assert await client.recv_packet() == "Test"

        async def test____wait_connected____idempotent(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                assert not client.is_connected()
                await client.wait_connected()
                assert client.is_connected()
                await client.wait_connected()
                assert client.is_connected()

        async def test____wait_connected____simultaneous(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                await client.backend().gather(*[client.wait_connected() for _ in range(5)])
                assert client.is_connected()

        async def test____wait_connected____is_closing____connection_not_performed_yet(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                assert not client.is_connected()
                assert not client.is_closing()
                await client.wait_connected()
                assert client.is_connected()
                assert not client.is_closing()

        async def test____wait_connected____close_before_trying_to_connect(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            client = AsyncUnixStreamClient(remote_address, stream_protocol)
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.wait_connected()

        async def test____socket_property____connection_not_performed_yet(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                with pytest.raises(AttributeError):
                    _ = client.socket

                await client.wait_connected()

                assert isinstance(client.socket, SocketProxy)
                assert client.socket is client.socket

        async def test____get_local_name____connection_not_performed_yet(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                with pytest.raises(OSError):
                    _ = client.get_local_name()

                await client.wait_connected()

                _ = client.get_local_name()

        async def test____get_peer_name____connection_not_performed_yet(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                with pytest.raises(OSError):
                    _ = client.get_peer_name()

                await client.wait_connected()

                assert client.get_peer_name().as_raw() == remote_address

        async def test____get_peer_credentials____consistency(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with AsyncUnixStreamClient(remote_address, stream_protocol) as client:
                assert client.is_connected()
                peer_credentials = client.get_peer_credentials()

                if sys.platform.startswith(("darwin", "linux", "openbsd", "netbsd")):
                    assert peer_credentials.pid == os.getpid()
                else:
                    assert peer_credentials.pid is None
                assert peer_credentials.uid == os.geteuid()
                assert peer_credentials.gid == os.getegid()

        async def test____get_peer_credentials____cached_result(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with AsyncUnixStreamClient(remote_address, stream_protocol) as client:
                assert client.is_connected()
                assert client.get_peer_credentials() is client.get_peer_credentials()

        async def test____get_peer_credentials____connection_not_performed_yet(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                with pytest.raises(OSError):
                    _ = client.get_peer_credentials()

                await client.wait_connected()

                _ = client.get_peer_credentials()

        async def test____send_packet____recv_packet____implicit_connection(
            self,
            remote_address: str,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            async with contextlib.aclosing(AsyncUnixStreamClient(remote_address, stream_protocol)) as client:
                assert not client.is_connected()

                await client.send_packet("Connected")
                assert await client.recv_packet() == "Connected"

                assert client.is_connected()

    @pytest.mark.asyncio
    class TestAsyncUnixStreamClientConnectionWithAsyncIO(_BaseTestAsyncUnixStreamClientConnection):
        @pytest_asyncio.fixture
        @staticmethod
        async def server(unix_socket_path_factory: UnixSocketPathFactory) -> AsyncIterator[asyncio.Server]:
            async def client_connected_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                with contextlib.closing(writer):
                    data: bytes = await reader.readline()
                    writer.write(data)
                    await writer.drain()

                await writer.wait_closed()

            async with await asyncio.start_unix_server(
                client_connected_cb,
                path=unix_socket_path_factory(),
            ) as server:
                yield server

        @pytest.fixture
        @staticmethod
        def remote_address(server: asyncio.Server) -> str:
            return server.sockets[0].getsockname()

    @pytest.mark.feature_trio(async_test_auto_mark=True)
    class TestAsyncUnixStreamClientConnectionWithTrio(_BaseTestAsyncUnixStreamClientConnection):
        @trio_fixture
        @staticmethod
        async def server(
            unix_socket_path_factory: UnixSocketPathFactory,
            nursery: trio.Nursery,
        ) -> AsyncIterator[trio.SocketListener]:
            from socket import AF_UNIX, SOCK_STREAM

            import trio

            from ..trio_stream import TrioStreamLineReader

            async def client_connected_cb(stream: trio.SocketStream) -> None:
                async with stream:
                    data: bytes = await TrioStreamLineReader(stream).readline()
                    await stream.send_all(data)

            server_socket = trio.socket.socket(AF_UNIX, SOCK_STREAM, 0)
            try:
                await server_socket.bind(unix_socket_path_factory())
                server_socket.listen()
            except BaseException:
                server_socket.close()
                raise

            server = trio.SocketListener(server_socket)
            await nursery.start(trio.serve_listeners, client_connected_cb, [server])
            yield server

        @pytest.fixture
        @staticmethod
        def remote_address(server: trio.SocketListener) -> str:
            return server.socket.getsockname()
