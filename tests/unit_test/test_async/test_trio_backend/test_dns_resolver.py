from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest

from ....fixtures.trio import trio_fixture

if TYPE_CHECKING:
    from trio import SocketListener, SocketStream

    from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioDNSResolver:
    @trio_fixture
    @staticmethod
    async def listener() -> AsyncIterator[SocketListener]:
        import trio

        async with (await trio.open_tcp_listeners(0, host="127.0.0.1"))[0] as listener:
            yield listener

    @pytest.fixture
    @staticmethod
    def listener_address(listener: SocketListener) -> tuple[str, int]:
        return listener.socket.getsockname()

    @pytest.fixture
    @staticmethod
    def client_sock(listener: SocketListener) -> socket.socket:
        sock = socket.socket(family=listener.socket.family, type=listener.socket.type)
        sock.setblocking(False)
        return sock

    @pytest.fixture
    @staticmethod
    def dns_resolver() -> TrioDNSResolver:
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

        return TrioDNSResolver()

    async def test____connect_socket____works(
        self,
        dns_resolver: TrioDNSResolver,
        listener: SocketListener,
        listener_address: tuple[str, int],
        client_sock: socket.socket,
    ) -> None:
        # Arrange
        import trio

        # Act
        server_stream: SocketStream | None = None
        async with trio.open_nursery() as nursery:
            nursery.cancel_scope.deadline = trio.current_time() + 1
            nursery.start_soon(dns_resolver.connect_socket, client_sock, listener_address)

            await trio.sleep(0.5)
            server_stream = await listener.accept()

        # Assert
        assert server_stream is not None
        assert client_sock.fileno() > 0

        async with server_stream, trio.SocketStream(trio.socket.from_stdlib_socket(client_sock)) as client_stream:
            await client_stream.send_all(b"data")
            assert (await server_stream.receive_some()) == b"data"

    async def test____connect_socket____close_on_cancel(
        self,
        dns_resolver: TrioDNSResolver,
        listener_address: tuple[str, int],
        client_sock: socket.socket,
    ) -> None:
        # Arrange
        import trio

        # Act
        with trio.move_on_after(0) as scope:
            await dns_resolver.connect_socket(client_sock, listener_address)

        # Assert
        assert scope.cancelled_caught
        assert client_sock.fileno() < 0

    async def test____connect_socket____close_on_error(
        self,
        dns_resolver: TrioDNSResolver,
        client_sock: socket.socket,
    ) -> None:
        # Arrange
        listener_address = ("unknown_address", 12345)

        # Act
        with pytest.raises(OSError):
            await dns_resolver.connect_socket(client_sock, listener_address)

        # Assert
        assert client_sock.fileno() < 0
