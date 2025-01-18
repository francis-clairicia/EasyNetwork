from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import ClientClosedError
from easynetwork.lowlevel._utils import Flag
from easynetwork.lowlevel.socket import INETSocketAttribute, SocketProxy, new_socket_address
from easynetwork.servers.async_udp import AsyncUDPNetworkServer, _ClientAPI
from easynetwork.servers.handlers import INETClientAttribute

import pytest

from ....base import INET_FAMILIES, BaseTestSocket
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncUDPNetworkServer:
    @pytest.fixture
    @staticmethod
    def server(
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> AsyncUDPNetworkServer[Any, Any]:
        return AsyncUDPNetworkServer(None, 0, mock_datagram_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncUDPNetworkServer("localhost", 0, mock_stream_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncDatagramRequestHandler object, got .*$"):
            _ = AsyncUDPNetworkServer("localhost", 0, mock_datagram_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____backend____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = AsyncUDPNetworkServer(None, 0, mock_datagram_protocol, mock_datagram_request_handler, invalid_backend)

    async def test____get_backend____returns_linked_instance(
        self,
        server: AsyncUDPNetworkServer[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_backend


@pytest.mark.asyncio
class TestClientAPI(BaseTestSocket):
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
    def service_available() -> Flag:
        return Flag()

    @pytest.fixture
    @staticmethod
    def mock_udp_socket(socket_family: int, mock_udp_socket_factory: Callable[[int], MagicMock]) -> MagicMock:
        return mock_udp_socket_factory(socket_family)

    @pytest.fixture
    @classmethod
    def mock_datagram_server(
        cls,
        socket_family: int,
        local_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        from easynetwork.lowlevel.api_async.servers.datagram import AsyncDatagramServer
        from easynetwork.lowlevel.socket import _get_socket_extra

        cls.set_local_address_to_socket_mock(mock_udp_socket, socket_family, local_address)
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_udp_socket)
        mock_datagram_server = make_transport_mock(mocker=mocker, spec=AsyncDatagramServer, backend=mock_backend)
        mock_datagram_server.extra_attributes = {
            **_get_socket_extra(mock_udp_socket, wrap_in_proxy=False),
            # Used to ensure that AsyncDatagramServer specific attributes are *NOT* merged.
            mocker.sentinel.custom_attribute: lambda: mocker.sentinel.custom_value,
        }
        return mock_datagram_server

    @pytest.fixture
    @staticmethod
    def client(
        remote_address: tuple[str, int],
        socket_family: int,
        service_available: Flag,
        mock_udp_socket: MagicMock,
        mock_datagram_server: MagicMock,
    ) -> _ClientAPI[Any]:
        from easynetwork.lowlevel.api_async.servers.datagram import DatagramClientContext

        service_available.set()
        client: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
        )
        mock_udp_socket.reset_mock()
        return client

    async def test____dunder_init____initialize_inner_client(
        self,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        socket_family: int,
        service_available: Flag,
        mock_udp_socket: MagicMock,
        mock_datagram_server: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.servers.datagram import DatagramClientContext

        service_available.set()

        # Act
        client: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
        )

        # Assert
        assert mock_udp_socket.setsockopt.mock_calls == []
        assert client.backend() is mock_backend
        assert isinstance(client.extra(INETClientAttribute.socket), SocketProxy)
        assert client.extra(INETClientAttribute.local_address) == new_socket_address(local_address, socket_family)
        assert client.extra(INETClientAttribute.remote_address) == new_socket_address(remote_address, socket_family)
        assert client.extra(INETSocketAttribute.family) == socket_family
        assert client.extra(mocker.sentinel.custom_attribute, mocker.sentinel.lookup_failed) is mocker.sentinel.lookup_failed

    async def test____uniqueness____using_hash_and_eq(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        service_available: Flag,
        mock_datagram_server: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.servers.datagram import DatagramClientContext

        service_available.set()
        client_1: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
        )
        client_2: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
        )
        client_3: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address((remote_address[0], remote_address[1] + 42), socket_family),
                server=mock_datagram_server,
            ),
            service_available,
        )

        # Act & Assert
        assert hash(client_1) == hash(client_2)
        assert hash(client_1) != hash(client_3)
        assert hash(client_2) != hash(client_3)
        assert client_1 == client_2
        assert client_1 != client_3
        assert client_2 != client_3
        assert client_1 != object()
        assert client_2 != object()
        assert client_3 != object()

    async def test____send_packet____send_bytes_to_socket(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        client: _ClientAPI[Any],
        mock_datagram_server: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_server.send_packet_to.assert_awaited_once_with(
            mocker.sentinel.packet,
            new_socket_address(remote_address, socket_family),
        )

    @pytest.mark.parametrize("method", ["server_close", "service_shutdown"])
    async def test____send_packet____closed_client(
        self,
        method: Literal["server_close", "service_shutdown"],
        client: _ClientAPI[Any],
        mock_datagram_server: MagicMock,
        service_available: Flag,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match method:
            case "server_close":
                await mock_datagram_server.aclose()
            case "service_shutdown":
                service_available.clear()
        assert client.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_server.send_packet_to.assert_not_awaited()
