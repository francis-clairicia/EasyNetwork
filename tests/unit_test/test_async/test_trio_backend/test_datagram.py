from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend
from easynetwork.lowlevel.socket import SocketAttribute, SocketProxy

import pytest

from ....fixtures.trio import trio_fixture
from ...base import BaseTestSocket

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter


@pytest.mark.feature_trio
class TestTrioDatagramSocketAdapter(BaseTestSocket):
    @pytest.fixture
    @classmethod
    def mock_trio_udp_socket(cls, mock_trio_udp_socket: MagicMock) -> MagicMock:
        cls.set_local_address_to_socket_mock(mock_trio_udp_socket, mock_trio_udp_socket.family, ("127.0.0.1", 11111))
        cls.set_remote_address_to_socket_mock(mock_trio_udp_socket, mock_trio_udp_socket.family, ("127.0.0.1", 12345))
        return mock_trio_udp_socket

    @trio_fixture
    @staticmethod
    async def transport(
        trio_backend: TrioBackend,
        mock_trio_udp_socket: MagicMock,
    ) -> AsyncIterator[TrioDatagramSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        transport = TrioDatagramSocketAdapter(trio_backend, mock_trio_udp_socket)
        async with transport:
            yield transport

    async def test____dunder_init____invalid_socket_type(
        self,
        trio_backend: TrioBackend,
        mock_trio_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = TrioDatagramSocketAdapter(trio_backend, mock_trio_tcp_socket)

    async def test____dunder_del____ResourceWarning(
        self,
        trio_backend: TrioBackend,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        transport = TrioDatagramSocketAdapter(trio_backend, mock_trio_udp_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_trio_udp_socket.close.assert_called()

    async def test____aclose____close_transport_and_wait(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        import trio.testing

        assert not transport.is_closing()

        # Act
        with trio.testing.assert_checkpoints():
            await transport.aclose()

        # Assert
        mock_trio_udp_socket.close.assert_called_once()
        assert transport.is_closing()

    async def test____recv____read_from_reader(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        mock_trio_udp_socket.recv.return_value = b"data"

        # Act
        data: bytes = await transport.recv()

        # Assert
        mock_trio_udp_socket.recv.assert_awaited_once_with(TrioDatagramSocketAdapter.MAX_DATAGRAM_BUFSIZE)
        assert data == b"data"

    async def test____send____use_stream_send_all(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_udp_socket.send.side_effect = lambda data: memoryview(data).nbytes

        # Act
        await transport.send(b"data to send")

        # Assert
        mock_trio_udp_socket.send.assert_awaited_once_with(b"data to send")

    async def test____get_backend____returns_linked_instance(
        self,
        transport: TrioDatagramSocketAdapter,
        trio_backend: TrioBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert transport.backend() is trio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_trio_udp_socket.family
        assert transport.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert transport.extra(SocketAttribute.peername) == ("127.0.0.1", 12345)

        mock_trio_udp_socket.reset_mock()
        transport.extra(SocketAttribute.socket).fileno()
        mock_trio_udp_socket.fileno.assert_called_once()
