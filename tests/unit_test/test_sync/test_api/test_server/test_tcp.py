from __future__ import annotations

import errno
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import ClientClosedError, UnsupportedOperation
from easynetwork.lowlevel.socket import INETSocketAttribute, SocketProxy, new_socket_address
from easynetwork.servers.handlers import INETClientAttribute
from easynetwork.servers.threaded_tcp import ThreadedTCPNetworkServer, _ConnectedClientAPI

import pytest

from ....base import BaseTestIPv4v6SocketTransport
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestThreadedTCPNetworkServer:

    def test____dunder_init____protocol____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = ThreadedTCPNetworkServer(None, 0, mock_datagram_protocol, mock_stream_request_handler)

    def test____dunder_init____request_handler____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a BlockingStreamRequestHandler object, got .*$"):
            _ = ThreadedTCPNetworkServer(None, 0, mock_stream_protocol, mock_datagram_request_handler)

    @pytest.mark.parametrize("ssl_parameter", ["ssl_handshake_timeout", "ssl_shutdown_timeout", "ssl_standard_compatible"])
    def test____dunder_init____useless_parameter_if_no_ssl_context(
        self,
        ssl_parameter: str,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        kwargs: dict[str, Any] = {ssl_parameter: mocker.sentinel.value}
        with pytest.raises(ValueError, match=rf"^{ssl_parameter} is only meaningful with ssl$"):
            _ = ThreadedTCPNetworkServer(
                None,
                0,
                mock_stream_protocol,
                mock_stream_request_handler,
                ssl=None,
                **kwargs,
            )

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size__{p}")
    def test____dunder_init____max_recv_size____invalid_value(
        self,
        max_recv_size: Any,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
    ) -> None:
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = ThreadedTCPNetworkServer(
                None,
                0,
                mock_stream_protocol,
                mock_stream_request_handler,
                max_recv_size=max_recv_size,
            )


class TestConnectedClientAPI(BaseTestIPv4v6SocketTransport):
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
        mocker: MockerFixture,
    ) -> MagicMock:
        from easynetwork.lowlevel.api_sync.servers.selector_stream import ConnectedStreamClient
        from easynetwork.lowlevel.socket import _get_socket_extra

        cls.set_local_address_to_socket_mock(mock_tcp_socket, socket_family, local_address)
        cls.set_remote_address_to_socket_mock(mock_tcp_socket, socket_family, remote_address)
        mock_connected_stream_client = make_transport_mock(mocker=mocker, spec=ConnectedStreamClient)
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

    def test____dunder_init____initialize_inner_client(
        self,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        socket_family: int,
        mock_tcp_socket: MagicMock,
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
        assert isinstance(client.extra(INETClientAttribute.socket), SocketProxy)
        assert client.extra(INETClientAttribute.local_address) == new_socket_address(local_address, socket_family)
        assert client.extra(INETClientAttribute.remote_address) == new_socket_address(remote_address, socket_family)
        assert client.extra(INETSocketAttribute.family) == socket_family
        assert client.extra(mocker.sentinel.custom_attribute) is mocker.sentinel.custom_value

    def test____send_packet____send_bytes_to_socket(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_connected_stream_client.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=None)
        ## This client object should not check SO_ERROR
        mock_tcp_socket.getsockopt.assert_not_called()

    def test____send_packet____send_bytes_to_socket____with_timeout(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=mocker.sentinel.timeout)

        # Assert
        mock_connected_stream_client.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=mocker.sentinel.timeout)
        ## This client object should not check SO_ERROR
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("method", ["close", "abort", "force_disconnect"])
    def test____send_packet____closed_client(
        self,
        method: Literal["close", "abort", "force_disconnect"],
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match method:
            case "close":
                client.close()
                mock_connected_stream_client.close.assert_called_once_with()
                mock_connected_stream_client.abort.assert_not_called()
            case "abort":
                client.abort()
                mock_connected_stream_client.abort.assert_called_once_with()
                mock_connected_stream_client.close.assert_not_called()
            case "force_disconnect":
                client._on_disconnect()
                mock_connected_stream_client.abort.assert_not_called()
                mock_connected_stream_client.close.assert_not_called()
        assert client.is_closing()
        mock_connected_stream_client.reset_mock()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_connected_stream_client.send_packet.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    def test____send_packet_with_ancillary____unsupported(
        self,
        client: _ConnectedClientAPI[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(UnsupportedOperation):
            client.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata)

    @pytest.mark.parametrize("method", ["close", "abort", "force_disconnect"])
    def test____socket_proxy____closed_client(
        self,
        method: Literal["close", "abort", "force_disconnect"],
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        from socket import SO_KEEPALIVE, SOL_SOCKET

        match method:
            case "close":
                client.close()
                mock_connected_stream_client.close.assert_called_once_with()
                mock_connected_stream_client.abort.assert_not_called()
            case "abort":
                client.abort()
                mock_connected_stream_client.abort.assert_called_once_with()
                mock_connected_stream_client.close.assert_not_called()
            case "force_disconnect":
                client._on_disconnect()
                mock_connected_stream_client.abort.assert_not_called()
                mock_connected_stream_client.close.assert_not_called()
        assert client.is_closing()
        mock_connected_stream_client.reset_mock()
        mock_tcp_socket.reset_mock()
        mock_tcp_socket.fileno.__name__ = "fileno"

        # Act & Assert
        socket = client.extra(INETClientAttribute.socket)
        assert socket.fileno() == -1
        with pytest.raises(OSError, check=lambda exc: exc.errno == errno.EBADF):
            socket.setsockopt(SOL_SOCKET, SO_KEEPALIVE, False)
        mock_tcp_socket.fileno.assert_not_called()
        mock_tcp_socket.setsockopt.assert_not_called()
