from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import ClientClosedError
from easynetwork.lowlevel.socket import INETSocketAttribute, SocketProxy, new_socket_address
from easynetwork.servers.async_tcp import AsyncTCPNetworkServer, _ConnectedClientAPI
from easynetwork.servers.handlers import INETClientAttribute

import pytest

from ...._utils import AsyncDummyLock
from ....base import INET_FAMILIES, BaseTestSocket
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncTCPNetworkServer:
    @pytest.fixture
    @staticmethod
    def server(
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> AsyncTCPNetworkServer[Any, Any]:
        return AsyncTCPNetworkServer(None, 0, mock_stream_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_datagram_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncStreamRequestHandler object, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_stream_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____backend____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = AsyncTCPNetworkServer(None, 0, mock_stream_protocol, mock_stream_request_handler, invalid_backend)

    async def test____get_backend____returns_linked_instance(
        self,
        server: AsyncTCPNetworkServer[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_backend


@pytest.mark.asyncio
class TestConnectedClientAPI(BaseTestSocket):
    @pytest.fixture
    @staticmethod
    def local_address() -> tuple[str, int]:
        return ("local_address", 11111)

    @pytest.fixture
    @staticmethod
    def remote_address() -> tuple[str, int]:
        return ("remote_address", 12345)

    @pytest.fixture(scope="class", params=INET_FAMILIES)
    @staticmethod
    def socket_family(request: pytest.FixtureRequest) -> int:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture
    @staticmethod
    def mock_tcp_socket(socket_family: int, mock_tcp_socket_factory: Callable[[int], MagicMock]) -> MagicMock:
        return mock_tcp_socket_factory(socket_family)

    @pytest.fixture
    @classmethod
    def mock_connected_stream_client(
        cls,
        socket_family: int,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        from easynetwork.lowlevel.api_async.servers.stream import ConnectedStreamClient
        from easynetwork.lowlevel.socket import _get_socket_extra

        cls.set_local_address_to_socket_mock(mock_tcp_socket, socket_family, local_address)
        cls.set_remote_address_to_socket_mock(mock_tcp_socket, socket_family, remote_address)
        mock_connected_stream_client = make_transport_mock(mocker=mocker, spec=ConnectedStreamClient, backend=mock_backend)
        mock_connected_stream_client.extra_attributes = {
            **_get_socket_extra(mock_tcp_socket, wrap_in_proxy=False),
            # Used to ensure that ConnectedStreamClient specific attributes are merged.
            mocker.sentinel.custom_attribute: lambda: mocker.sentinel.custom_value,
        }
        return mock_connected_stream_client

    @pytest.fixture
    @staticmethod
    def client(
        remote_address: tuple[str, int],
        socket_family: int,
        mock_tcp_socket: MagicMock,
        mock_connected_stream_client: MagicMock,
    ) -> _ConnectedClientAPI[Any]:
        client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(
            new_socket_address(remote_address, socket_family),
            mock_connected_stream_client,
        )
        mock_tcp_socket.reset_mock()
        return client

    async def test____dunder_init____initialize_inner_client(
        self,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        socket_family: int,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_connected_stream_client: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import IPPROTO_TCP, SO_KEEPALIVE, SOL_SOCKET, TCP_NODELAY

        # Act
        client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(
            new_socket_address(remote_address, socket_family),
            mock_connected_stream_client,
        )

        # Assert
        assert mock_tcp_socket.setsockopt.mock_calls == [
            mocker.call(IPPROTO_TCP, TCP_NODELAY, True),
            mocker.call(SOL_SOCKET, SO_KEEPALIVE, True),
        ]
        assert client.backend() is mock_backend
        assert isinstance(client.extra(INETClientAttribute.socket), SocketProxy)
        assert client.extra(INETClientAttribute.local_address) == new_socket_address(local_address, socket_family)
        assert client.extra(INETClientAttribute.remote_address) == new_socket_address(remote_address, socket_family)
        assert client.extra(INETSocketAttribute.family) == socket_family
        assert client.extra(mocker.sentinel.custom_attribute) is mocker.sentinel.custom_value

    async def test____send_packet____send_bytes_to_socket(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_connected_stream_client.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        ## This client object should not check SO_ERROR
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("method", ["close", "force_disconnect"])
    async def test____send_packet____closed_client(
        self,
        method: Literal["close", "force_disconnect"],
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match method:
            case "close":
                await client.aclose()
            case "force_disconnect":
                await client._on_disconnect()
        assert client.is_closing()
        mock_connected_stream_client.reset_mock()

        # Act
        with pytest.raises(ClientClosedError):
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_connected_stream_client.send_packet.assert_not_awaited()
        mock_tcp_socket.getsockopt.assert_not_called()

    async def test____special_case____close_cancelled_during_lock_acquisition(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_connected_stream_client.aclose.assert_awaited_once_with()

    async def test____special_case____close_cancelled_during_lock_acquisition____endpoint_is_already_closing(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client._on_disconnect()
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_connected_stream_client.aclose.assert_not_awaited()
