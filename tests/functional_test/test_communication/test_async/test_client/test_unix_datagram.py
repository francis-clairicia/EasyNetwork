from __future__ import annotations

import asyncio
import contextlib
import pathlib
import sys
from collections.abc import AsyncIterator, Callable
from socket import socket as Socket
from typing import TYPE_CHECKING, NoReturn

import pytest
import pytest_asyncio

from .....fixtures.trio import trio_fixture
from .....tools import PlatformMarkers
from .._utils import delay
from ..socket import AsyncDatagramSocket

if sys.platform != "win32":
    from easynetwork.clients.async_unix_datagram import AsyncUnixDatagramClient
    from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
    from easynetwork.lowlevel.socket import SocketProxy
    from easynetwork.protocol import DatagramProtocol

    if TYPE_CHECKING:
        import trio

        from .....pytest_plugins.unix_sockets import UnixSocketPathFactory

    @pytest.fixture
    def bound_unix_datagram_socket_factory(
        request: pytest.FixtureRequest,
        unix_datagram_socket_factory: Callable[[], Socket],
        unix_socket_path_factory: UnixSocketPathFactory,
    ) -> Callable[[], Socket]:
        use_unix_address_type: str | None = getattr(request, "param", None)

        def bound_unix_datagram_socket_factory() -> Socket:
            sock = unix_datagram_socket_factory()
            match use_unix_address_type:
                case "PATHNAME" | None:
                    sock.bind(unix_socket_path_factory())
                case "ABSTRACT":
                    sock.bind("")
                case _:
                    sock.close()
                    pytest.fail(f"Invalid use_unix_address_type parameter: {request.param}")
            return sock

        return bound_unix_datagram_socket_factory

    @pytest.mark.flaky(retries=3, delay=0.1)
    class _BaseTestAsyncUnixDatagramClient:

        async def test____aclose____idempotent(self, client: AsyncUnixDatagramClient[str, str]) -> None:
            assert not client.is_closing()
            await client.aclose()
            assert client.is_closing()
            await client.aclose()
            assert client.is_closing()

        async def test____send_packet____default(
            self,
            client: AsyncUnixDatagramClient[str, str],
            server: AsyncDatagramSocket,
        ) -> None:
            await client.send_packet("ABCDEF")
            with client.backend().timeout(3):
                assert await server.recvfrom() == (b"ABCDEF", client.get_local_name().as_raw())

        async def test____send_packet____closed_client(
            self,
            client: AsyncUnixDatagramClient[str, str],
        ) -> None:
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.send_packet("ABCDEF")

        @pytest.mark.parametrize("datagram_protocol", [pytest.param("bad_serialize", id="serializer_crash")], indirect=True)
        async def test____send_packet____protocol_crashed(
            self,
            client: AsyncUnixDatagramClient[str, str],
        ) -> None:
            with pytest.raises(RuntimeError, match=r"^protocol\.make_datagram\(\) crashed$"):
                await client.send_packet("ABCDEF")

        async def test____recv_packet____default(
            self,
            client: AsyncUnixDatagramClient[str, str],
            server: AsyncDatagramSocket,
        ) -> None:
            await server.sendto(b"ABCDEF", client.get_local_name().as_raw())
            with client.backend().timeout(3):
                assert await client.recv_packet() == "ABCDEF"

        async def test____recv_packet____closed_client(
            self,
            client: AsyncUnixDatagramClient[str, str],
        ) -> None:
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.recv_packet()

        async def test____recv_packet____client_close_while_waiting(
            self,
            client: AsyncUnixDatagramClient[str, str],
        ) -> None:
            async with client.backend().create_task_group() as tg:
                await tg.start(delay, 0.5, client.aclose)
                with client.backend().timeout(5), pytest.raises(ClientClosedError):
                    assert await client.recv_packet()

        async def test____recv_packet____invalid_data(
            self, client: AsyncUnixDatagramClient[str, str], server: AsyncDatagramSocket
        ) -> None:
            await server.sendto("\u00e9".encode("latin-1"), client.get_local_name().as_raw())
            with pytest.raises(DatagramProtocolParseError):
                with client.backend().timeout(3):
                    await client.recv_packet()

        @pytest.mark.parametrize("datagram_protocol", [pytest.param("invalid", id="serializer_crash")], indirect=True)
        async def test____recv_packet____protocol_crashed(
            self,
            client: AsyncUnixDatagramClient[str, str],
            server: AsyncDatagramSocket,
        ) -> None:
            await server.sendto(b"ABCDEF", client.get_local_name().as_raw())
            try:
                await client.recv_packet()
            except NotImplementedError:
                raise
            except Exception:
                with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_datagram\(\) crashed$"):
                    raise

        async def test____iter_received_packets____yields_available_packets_until_close(
            self,
            client: AsyncUnixDatagramClient[str, str],
            server: AsyncDatagramSocket,
        ) -> None:
            for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
                await server.sendto(p, client.get_local_name().as_raw())

            async with client.backend().create_task_group() as tg:
                await tg.start(delay, 0.5, client.aclose)
                # NOTE: Comparison using set because equality check does not verify order
                assert {p async for p in client.iter_received_packets(timeout=None)} == {"A", "B", "C", "D", "E", "F"}

        async def test____iter_received_packets____yields_available_packets_until_timeout(
            self,
            client: AsyncUnixDatagramClient[str, str],
            server: AsyncDatagramSocket,
        ) -> None:
            for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
                await server.sendto(p, client.get_local_name().as_raw())

            # NOTE: Comparison using set because equality check does not verify order
            assert {p async for p in client.iter_received_packets(timeout=1)} == {"A", "B", "C", "D", "E", "F"}

        async def test____get_local_name____consistency(self, client: AsyncUnixDatagramClient[str, str]) -> None:
            from easynetwork.lowlevel.socket import UnixSocketAddress

            address = client.get_local_name()
            assert isinstance(address, UnixSocketAddress)
            assert address.as_raw() == client.socket.getsockname()

        async def test____get_peer_name____consistency(self, client: AsyncUnixDatagramClient[str, str]) -> None:
            from easynetwork.lowlevel.socket import UnixSocketAddress

            address = client.get_peer_name()
            assert isinstance(address, UnixSocketAddress)
            assert address.as_raw() == client.socket.getpeername()

    @pytest.mark.asyncio
    class TestAsyncUnixDatagramClientWithAsyncIO(_BaseTestAsyncUnixDatagramClient):
        @pytest_asyncio.fixture
        @staticmethod
        async def server(bound_unix_datagram_socket_factory: Callable[[], Socket]) -> AsyncIterator[AsyncDatagramSocket]:
            async with await AsyncDatagramSocket.from_stdlib_socket(bound_unix_datagram_socket_factory()) as server:
                yield server

        @pytest_asyncio.fixture
        @staticmethod
        async def client(
            server: AsyncDatagramSocket,
            bound_unix_datagram_socket_factory: Callable[[], Socket],
            datagram_protocol: DatagramProtocol[str, str],
        ) -> AsyncIterator[AsyncUnixDatagramClient[str, str]]:
            remote_address: str | bytes = server.getsockname()
            socket = bound_unix_datagram_socket_factory()
            socket.connect(remote_address)

            async with AsyncUnixDatagramClient(socket, datagram_protocol, "asyncio") as client:
                assert client.is_connected()
                yield client

    @pytest.mark.feature_trio(async_test_auto_mark=True)
    class TestAsyncUnixDatagramClientWithTrio(_BaseTestAsyncUnixDatagramClient):
        @trio_fixture
        @staticmethod
        async def server(bound_unix_datagram_socket_factory: Callable[[], Socket]) -> AsyncIterator[AsyncDatagramSocket]:
            async with await AsyncDatagramSocket.from_stdlib_socket(bound_unix_datagram_socket_factory()) as server:
                yield server

        @trio_fixture
        @staticmethod
        async def client(
            server: AsyncDatagramSocket,
            bound_unix_datagram_socket_factory: Callable[[], Socket],
            datagram_protocol: DatagramProtocol[str, str],
        ) -> AsyncIterator[AsyncUnixDatagramClient[str, str]]:
            remote_address: str | bytes = server.getsockname()
            socket = bound_unix_datagram_socket_factory()
            socket.connect(remote_address)

            async with AsyncUnixDatagramClient(socket, datagram_protocol, "trio") as client:
                assert client.is_connected()
                yield client

    @pytest.mark.parametrize(
        "bound_unix_datagram_socket_factory",
        [
            pytest.param("PATHNAME"),
            pytest.param("ABSTRACT", marks=PlatformMarkers.supports_abstract_sockets),
        ],
        indirect=True,
    )
    class _BaseTestAsyncUnixDatagramClientConnection:

        @pytest.fixture
        @staticmethod
        def local_path(unix_socket_path_factory: UnixSocketPathFactory) -> str:
            return unix_socket_path_factory()

        @PlatformMarkers.supports_abstract_sockets
        async def test____dunder_init____automatic_local_name(
            self,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with AsyncUnixDatagramClient(remote_address, datagram_protocol) as client:
                assert client.is_connected()
                assert not client.get_local_name().is_unnamed()

                with client.backend().timeout(3):
                    await client.send_packet("Test")
                    assert await client.recv_packet() == "Test"

        @PlatformMarkers.abstract_sockets_unsupported
        async def test____dunder_init____automatic_local_name____unsupported_by_current_platform(
            self,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            with pytest.raises(
                ValueError,
                match=r"^local_path parameter is required on this platform and cannot be an empty string\.",
            ):
                _ = AsyncUnixDatagramClient(remote_address, datagram_protocol)

        async def test____dunder_init____with_local_name(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with AsyncUnixDatagramClient(remote_address, datagram_protocol, local_path=local_path) as client:
                assert client.is_connected()
                assert client.get_local_name().as_pathname() == pathlib.Path(local_path)

                with client.backend().timeout(5):
                    await client.send_packet("Test")
                    assert await client.recv_packet() == "Test"

        async def test____dunder_init____peer_name____not_set(
            self,
            bound_unix_datagram_socket_factory: Callable[[], Socket],
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            from easynetwork.clients.async_unix_datagram import AsyncUnixDatagramClient

            with pytest.raises(OSError):
                _ = AsyncUnixDatagramClient(bound_unix_datagram_socket_factory(), datagram_protocol)

        async def test____dunder_init____local_name____not_set(
            self,
            remote_address: str | bytes,
            unix_datagram_socket_factory: Callable[[], Socket],
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            sock = unix_datagram_socket_factory()
            sock.connect(remote_address)
            assert not sock.getsockname()
            with pytest.raises(ValueError, match=r"^AsyncUnixDatagramClient requires the socket to be named.$"):
                _ = AsyncUnixDatagramClient(sock, datagram_protocol)

        async def test____wait_connected____idempotent(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with contextlib.aclosing(
                AsyncUnixDatagramClient(
                    remote_address,
                    datagram_protocol,
                    local_path=local_path,
                )
            ) as client:
                await client.wait_connected()
                assert client.is_connected()
                await client.wait_connected()
                assert client.is_connected()

        async def test____wait_connected____simultaneous(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with contextlib.aclosing(
                AsyncUnixDatagramClient(
                    remote_address,
                    datagram_protocol,
                    local_path=local_path,
                )
            ) as client:
                await client.backend().gather(*[client.wait_connected() for _ in range(5)])
                assert client.is_connected()

        async def test____wait_connected____is_closing____connection_not_performed_yet(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with contextlib.aclosing(
                AsyncUnixDatagramClient(
                    remote_address,
                    datagram_protocol,
                    local_path=local_path,
                )
            ) as client:
                assert not client.is_connected()
                assert not client.is_closing()
                await client.wait_connected()
                assert client.is_connected()
                assert not client.is_closing()

        async def test____wait_connected____close_before_trying_to_connect(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            client = AsyncUnixDatagramClient(
                remote_address,
                datagram_protocol,
                local_path=local_path,
            )
            await client.aclose()
            with pytest.raises(ClientClosedError):
                await client.wait_connected()

        async def test____socket_property____connection_not_performed_yet(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with contextlib.aclosing(
                AsyncUnixDatagramClient(
                    remote_address,
                    datagram_protocol,
                    local_path=local_path,
                )
            ) as client:
                with pytest.raises(AttributeError):
                    _ = client.socket

                await client.wait_connected()

                assert isinstance(client.socket, SocketProxy)
                assert client.socket is client.socket

        async def test____get_local_name____connection_not_performed_yet(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with contextlib.aclosing(
                AsyncUnixDatagramClient(
                    remote_address,
                    datagram_protocol,
                    local_path=local_path,
                )
            ) as client:
                with pytest.raises(OSError):
                    _ = client.get_local_name()

                await client.wait_connected()

                assert client.get_local_name().as_raw() == local_path

        async def test____get_peer_name____connection_not_performed_yet(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with contextlib.aclosing(
                AsyncUnixDatagramClient(
                    remote_address,
                    datagram_protocol,
                    local_path=local_path,
                )
            ) as client:
                with pytest.raises(OSError):
                    _ = client.get_peer_name()

                await client.wait_connected()

                assert client.get_peer_name().as_raw() == remote_address

        async def test____send_packet____recv_packet____implicit_connection(
            self,
            local_path: str,
            remote_address: str | bytes,
            datagram_protocol: DatagramProtocol[str, str],
        ) -> None:
            async with contextlib.aclosing(
                AsyncUnixDatagramClient(
                    remote_address,
                    datagram_protocol,
                    local_path=local_path,
                )
            ) as client:
                assert not client.is_connected()

                with client.backend().timeout(3):
                    await client.send_packet("Connected")
                    assert await client.recv_packet() == "Connected"

                assert client.is_connected()

    @pytest.mark.asyncio
    class TestAsyncUnixDatagramClientConnectionWithAsyncIO(_BaseTestAsyncUnixDatagramClientConnection):
        @pytest_asyncio.fixture
        @classmethod
        async def server(
            cls,
            bound_unix_datagram_socket_factory: Callable[[], Socket],
        ) -> AsyncIterator[Socket]:
            event_loop = asyncio.get_running_loop()

            async def echo_server_coroutine(sock: Socket) -> NoReturn:
                def echo_server(sock: Socket) -> None:
                    data, addr = sock.recvfrom(65536)
                    sock.sendto(data, addr)

                await cls.__infinite_serve(sock, echo_server)

            with contextlib.closing(bound_unix_datagram_socket_factory()) as sock:
                sock.setblocking(False)

                task: asyncio.Task[NoReturn] = event_loop.create_task(echo_server_coroutine(sock))

                yield sock

                task.cancel()
                await asyncio.wait({task}, timeout=1.0)

        @staticmethod
        def __infinite_serve(
            listener_sock: Socket,
            listener_ready_callback: Callable[[Socket], None],
        ) -> asyncio.Future[NoReturn]:
            loop = asyncio.get_running_loop()

            def on_fut_done(f: asyncio.Future[NoReturn]) -> None:
                loop.remove_reader(listener_sock)

            def listener_ready(f: asyncio.Future[NoReturn]) -> None:
                if f.done():
                    # I/O callbacks are always called before asyncio.Future done callbacks.
                    return
                try:
                    listener_ready_callback(listener_sock)
                except (BlockingIOError, InterruptedError):
                    return
                except OSError:
                    raise
                except BaseException as exc:
                    f.set_exception(exc)
                    # Break reference cycle with exception set.
                    del f

            f: asyncio.Future[NoReturn] = loop.create_future()
            loop.add_reader(listener_sock, listener_ready, f)

            f.add_done_callback(on_fut_done)
            return f

        @pytest.fixture
        @staticmethod
        def remote_address(server: Socket) -> str | bytes:
            return server.getsockname()

    @pytest.mark.feature_trio(async_test_auto_mark=True)
    class TestAsyncUnixDatagramClientConnectionWithTrio(_BaseTestAsyncUnixDatagramClientConnection):
        @trio_fixture
        @classmethod
        async def server(
            cls,
            bound_unix_datagram_socket_factory: Callable[[], Socket],
            nursery: trio.Nursery,
        ) -> AsyncIterator[trio.socket.SocketType]:
            import trio

            async def echo_server(*, task_status: trio.TaskStatus[trio.socket.SocketType] = trio.TASK_STATUS_IGNORED) -> NoReturn:
                with trio.socket.from_stdlib_socket(bound_unix_datagram_socket_factory()) as server:
                    task_status.started(server)
                    while True:
                        data, addr = await server.recvfrom(65536)
                        await server.sendto(data, addr)
                        del data, addr

            yield await nursery.start(echo_server)

        @pytest.fixture
        @staticmethod
        def remote_address(server: trio.socket.SocketType) -> str | bytes:
            return server.getsockname()
