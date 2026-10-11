from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import ClientClosedError, UnsupportedOperation
from easynetwork.lowlevel._lock import RWLock
from easynetwork.lowlevel.socket import INETSocketAttribute, SocketProxy, new_socket_address
from easynetwork.servers.handlers import INETClientAttribute
from easynetwork.servers.threaded_udp import ThreadedUDPNetworkServer, _ClientAPI

import pytest

from ....base import BaseTestIPv4v6SocketTransport
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestThreadedUDPNetworkServer:

    def test____dunder_init____protocol____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = ThreadedUDPNetworkServer("localhost", 0, mock_stream_protocol, mock_datagram_request_handler)

    def test____dunder_init____request_handler____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a BlockingDatagramRequestHandler object, got .*$"):
            _ = ThreadedUDPNetworkServer("localhost", 0, mock_datagram_protocol, mock_stream_request_handler)


class TestClientAPI(BaseTestIPv4v6SocketTransport):

    @pytest.fixture
    @staticmethod
    def service_available() -> threading.Event:
        return threading.Event()

    @pytest.fixture
    @staticmethod
    def service_close_lock() -> RWLock:
        return RWLock()

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
        mocker: MockerFixture,
    ) -> MagicMock:
        from easynetwork.lowlevel.api_sync.servers.selector_datagram import SelectorDatagramServer
        from easynetwork.lowlevel.socket import _get_socket_extra

        cls.set_local_address_to_socket_mock(mock_udp_socket, socket_family, local_address)
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_udp_socket)
        mock_datagram_server = make_transport_mock(mocker=mocker, spec=SelectorDatagramServer)
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
        service_available: threading.Event,
        service_close_lock: RWLock,
        mock_udp_socket: MagicMock,
        mock_datagram_server: MagicMock,
    ) -> _ClientAPI[Any]:
        from easynetwork.lowlevel.api_sync.servers.selector_datagram import DatagramClientContext

        service_available.set()
        client: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
            service_close_lock,
        )
        mock_udp_socket.reset_mock()
        return client

    def test____dunder_init____initialize_inner_client(
        self,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        socket_family: int,
        service_available: threading.Event,
        service_close_lock: RWLock,
        mock_udp_socket: MagicMock,
        mock_datagram_server: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_sync.servers.selector_datagram import DatagramClientContext

        service_available.set()

        # Act
        client: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
            service_close_lock,
        )

        # Assert
        assert mock_udp_socket.setsockopt.mock_calls == []
        assert isinstance(client.extra(INETClientAttribute.socket), SocketProxy)
        assert client.extra(INETClientAttribute.local_address) == new_socket_address(local_address, socket_family)
        assert client.extra(INETClientAttribute.remote_address) == new_socket_address(remote_address, socket_family)
        assert client.extra(INETSocketAttribute.family) == socket_family
        assert client.extra(mocker.sentinel.custom_attribute, mocker.sentinel.lookup_failed) is mocker.sentinel.lookup_failed

    def test____uniqueness____using_hash_and_eq(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        service_available: threading.Event,
        service_close_lock: RWLock,
        mock_datagram_server: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_sync.servers.selector_datagram import DatagramClientContext

        service_available.set()
        client_1: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
            service_close_lock,
        )
        client_2: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address(remote_address, socket_family),
                server=mock_datagram_server,
            ),
            service_available,
            service_close_lock,
        )
        client_3: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=new_socket_address((remote_address[0], remote_address[1] + 42), socket_family),
                server=mock_datagram_server,
            ),
            service_available,
            service_close_lock,
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

    def test____send_packet____send_bytes_to_socket(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        client: _ClientAPI[Any],
        mock_datagram_server: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_server.send_packet_to.assert_called_once_with(
            mocker.sentinel.packet,
            new_socket_address(remote_address, socket_family),
            timeout=None,
        )

    def test____send_packet____send_bytes_to_socket____with_timeout(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        client: _ClientAPI[Any],
        mock_datagram_server: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=mocker.sentinel.timeout)

        # Assert
        mock_datagram_server.send_packet_to.assert_called_once_with(
            mocker.sentinel.packet,
            new_socket_address(remote_address, socket_family),
            timeout=mocker.sentinel.timeout,
        )

    @pytest.mark.parametrize("method", ["server_close", "service_shutdown"])
    def test____send_packet____closed_client(
        self,
        method: Literal["server_close", "service_shutdown"],
        client: _ClientAPI[Any],
        mock_datagram_server: MagicMock,
        service_available: threading.Event,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match method:
            case "server_close":
                mock_datagram_server.close()
            case "service_shutdown":
                service_available.clear()
        assert client.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_server.send_packet_to.assert_not_called()

    def test____send_packet_with_ancillary____unsupported(
        self,
        client: _ClientAPI[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(UnsupportedOperation):
            client.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata)
