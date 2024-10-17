from __future__ import annotations

import errno
import os
from collections.abc import Callable, Iterator, Sequence
from socket import AF_INET, AF_INET6, AF_UNSPEC, IPPROTO_UDP, SO_ERROR, SOCK_DGRAM, SOL_SOCKET, AddressFamily
from typing import TYPE_CHECKING, Any, Literal, assert_never

from easynetwork.clients.udp import UDPNetworkClient, _create_udp_socket as create_udp_socket
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel._utils import error_from_errno
from easynetwork.lowlevel.api_sync.endpoints.datagram import DatagramEndpoint
from easynetwork.lowlevel.api_sync.transports.socket import SocketDatagramTransport
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS, MAX_DATAGRAM_BUFSIZE
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, _get_socket_extra

import pytest

from ...._utils import datagram_addrinfo_list, unsupported_families
from ....base import INET_FAMILIES
from ...mock_tools import make_transport_mock
from .base import BaseTestClient

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestUDPNetworkClient(BaseTestClient):
    @pytest.fixture(scope="class", params=INET_FAMILIES)
    @staticmethod
    def socket_family(request: pytest.FixtureRequest) -> Any:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture(scope="class")
    @staticmethod
    def global_local_address() -> tuple[str, int]:
        return ("local_address", 12345)

    @pytest.fixture(scope="class")
    @staticmethod
    def global_remote_address() -> tuple[str, int]:
        return ("remote_address", 5000)

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        request: pytest.FixtureRequest,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int] | None:
        address: tuple[str, int] | None = getattr(request, "param", global_local_address)
        if socket_family in (AF_INET, AF_INET6):
            cls.set_local_address_to_socket_mock(mock_udp_socket, socket_family, address or global_local_address)
        return address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int]:
        if socket_family in (AF_INET, AF_INET6):
            cls.set_remote_address_to_socket_mock(mock_udp_socket, socket_family, global_remote_address)
        return global_remote_address

    @pytest.fixture
    @staticmethod
    def mock_datagram_endpoint(mocker: MockerFixture) -> MagicMock:
        mock_datagram_endpoint = make_transport_mock(mocker=mocker, spec=DatagramEndpoint)
        mock_datagram_endpoint.recv_packet.return_value = mocker.sentinel.packet
        mock_datagram_endpoint.send_packet.return_value = None
        return mock_datagram_endpoint

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_datagram_endpoint_cls(mocker: MockerFixture, mock_datagram_endpoint: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._utils import Flag
        from easynetwork.protocol import DatagramProtocol

        was_called = Flag()

        def mock_endpoint_side_effect(transport: MagicMock, protocol: MagicMock) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            if not isinstance(protocol, DatagramProtocol):
                raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
            mock_datagram_endpoint.extra_attributes = transport.extra_attributes
            return mock_datagram_endpoint

        return mocker.patch(
            f"{UDPNetworkClient.__module__}.DatagramEndpoint",
            side_effect=mock_endpoint_side_effect,
        )

    @pytest.fixture
    @staticmethod
    def mock_datagram_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=SocketDatagramTransport)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_datagram_transport_cls(mocker: MockerFixture, mock_datagram_transport: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_transport_side_effect(sock: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            sock.setblocking(False)
            mock_datagram_transport.extra_attributes = _get_socket_extra(sock, wrap_in_proxy=False)
            return mock_datagram_transport

        return mocker.patch(
            f"{SocketDatagramTransport.__module__}.SocketDatagramTransport",
            side_effect=mock_transport_side_effect,
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_create_udp_socket(mocker: MockerFixture, mock_udp_socket: MagicMock) -> MagicMock:
        return mocker.patch(f"{UDPNetworkClient.__module__}._create_udp_socket", autospec=True, return_value=mock_udp_socket)

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_udp_socket: MagicMock,
        socket_family: int,
    ) -> None:
        mock_udp_socket.family = socket_family
        mock_udp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()

    @pytest.fixture
    @staticmethod
    def client(
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> Iterator[UDPNetworkClient[Any, Any]]:
        client: UDPNetworkClient[Any, Any] = UDPNetworkClient(mock_udp_socket, protocol=mock_datagram_protocol)
        with client:
            yield client

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(float("+inf"), id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: pytest.FixtureRequest) -> Any:
        return request.param

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(float("+inf"), id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def send_timeout(request: pytest.FixtureRequest) -> Any:
        return request.param

    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____with_remote_address(
        self,
        request: pytest.FixtureRequest,
        retry_interval: float,
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
        mock_datagram_endpoint_cls: MagicMock,
        mock_socket_datagram_transport_cls: MagicMock,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client = UDPNetworkClient[Any, Any](remote_address, mock_datagram_protocol, retry_interval=retry_interval)
        request.addfinalizer(client.close)

        # Assert
        mock_create_udp_socket.assert_called_once_with(remote_address=remote_address)
        mock_socket_datagram_transport_cls.assert_called_once_with(
            mock_udp_socket,
            retry_interval=retry_interval,
            max_datagram_size=MAX_DATAGRAM_BUFSIZE,
        )
        mock_datagram_endpoint_cls.assert_called_once_with(mock_datagram_transport, mock_datagram_protocol)
        assert mock_udp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.setblocking(False),
        ]

    @pytest.mark.parametrize(
        "local_address", [None, ("local_address", 12345)], ids=lambda p: f"local_address=={p}", indirect=True
    )
    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____with_remote_address____with_parameters(
        self,
        request: pytest.FixtureRequest,
        retry_interval: float,
        socket_family: int,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
        mock_datagram_endpoint_cls: MagicMock,
        mock_socket_datagram_transport_cls: MagicMock,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client = UDPNetworkClient[Any, Any](
            remote_address,
            mock_datagram_protocol,
            family=socket_family,
            local_address=local_address,
            retry_interval=retry_interval,
        )
        request.addfinalizer(client.close)

        # Assert
        mock_create_udp_socket.assert_called_once_with(
            family=socket_family,
            local_address=local_address,
            remote_address=remote_address,
        )
        mock_socket_datagram_transport_cls.assert_called_once_with(
            mock_udp_socket,
            retry_interval=retry_interval,
            max_datagram_size=MAX_DATAGRAM_BUFSIZE,
        )
        mock_datagram_endpoint_cls.assert_called_once_with(mock_datagram_transport, mock_datagram_protocol)
        assert mock_udp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.setblocking(False),
        ]
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize(
        "local_address", [None, ("local_address", 12345)], ids=lambda p: f"local_address=={p}", indirect=True
    )
    def test____dunder_init____with_remote_address____with_parameters____explicit_AF_UNSPEC(
        self,
        request: pytest.FixtureRequest,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client = UDPNetworkClient[Any, Any](
            remote_address,
            mock_datagram_protocol,
            family=AF_UNSPEC,
            local_address=local_address,
        )
        request.addfinalizer(client.close)

        # Assert
        mock_create_udp_socket.assert_called_once_with(
            family=AF_UNSPEC,
            local_address=local_address,
            remote_address=remote_address,
        )

    @pytest.mark.parametrize("socket_family", list(unsupported_families(INET_FAMILIES)), indirect=True)
    def test____dunder_init____with_remote_address____invalid_family(
        self,
        socket_family: int,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = UDPNetworkClient(
                remote_address,
                mock_datagram_protocol,
                family=socket_family,
            )
        mock_create_udp_socket.assert_not_called()

    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____use_given_socket____default(
        self,
        request: pytest.FixtureRequest,
        retry_interval: float,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
        mock_datagram_endpoint_cls: MagicMock,
        mock_socket_datagram_transport_cls: MagicMock,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client = UDPNetworkClient[Any, Any](mock_udp_socket, mock_datagram_protocol, retry_interval=retry_interval)
        request.addfinalizer(client.close)

        # Assert
        mock_create_udp_socket.assert_not_called()
        mock_socket_datagram_transport_cls.assert_called_once_with(
            mock_udp_socket,
            retry_interval=retry_interval,
            max_datagram_size=MAX_DATAGRAM_BUFSIZE,
        )
        mock_datagram_endpoint_cls.assert_called_once_with(mock_datagram_transport, mock_datagram_protocol)
        assert mock_udp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.setblocking(False),
        ]
        assert isinstance(client.socket, SocketProxy)

    def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        self.configure_socket_mock_to_raise_ENOTCONN(mock_udp_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = UDPNetworkClient(mock_udp_socket, mock_datagram_protocol)

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN
        assert mock_udp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.close(),
        ]

    @pytest.mark.parametrize("socket_family", list(unsupported_families(INET_FAMILIES)), indirect=True)
    def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = UDPNetworkClient(
                mock_udp_socket,
                protocol=mock_datagram_protocol,
            )

    def test____dunder_init____invalid_first_argument____invalid_object(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_object = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = UDPNetworkClient(
                invalid_object,
                protocol=mock_datagram_protocol,
            )

    def test____dunder_init____invalid_first_argument____invalid_host_port_pair(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_host = mocker.NonCallableMagicMock(spec=object)
        invalid_port = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = UDPNetworkClient(
                (invalid_host, invalid_port),
                protocol=mock_datagram_protocol,
            )

    def test____dunder_init____invalid_arguments____unknown_overload(
        self,
        local_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = UDPNetworkClient(
                mock_udp_socket,
                protocol=mock_datagram_protocol,
                local_address=local_address,
            )

        assert mock_udp_socket.mock_calls == []

    def test____dunder_init____protocol____invalid_value(
        self,
        mock_udp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = UDPNetworkClient(
                mock_udp_socket,
                protocol=mock_stream_protocol,
            )
        assert mock_datagram_transport.mock_calls == [mocker.call.close()]

    def test____dunder_del____ResourceWarning(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        client: UDPNetworkClient[Any, Any] = UDPNetworkClient(mock_udp_socket, mock_datagram_protocol)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed client .+$"):
            del client

        mock_datagram_endpoint.close.assert_called_once_with()

    def test____close____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()

        # Act
        client.close()

        # Assert
        assert client.is_closed()
        mock_datagram_endpoint.close.assert_called_once_with()

    def test____get_local_address____return_saved_address(
        self,
        client: UDPNetworkClient[Any, Any],
        socket_family: int,
        local_address: tuple[str, int],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.reset_mock()

        # Act
        address = client.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_udp_socket.getsockname.assert_called_once()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    def test____get_remote_address____return_saved_address(
        self,
        client: UDPNetworkClient[Any, Any],
        remote_address: tuple[str, int],
        socket_family: int,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getpeername.reset_mock()

        # Act
        address = client.get_remote_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_udp_socket.getpeername.assert_called_once()
        assert address.host == remote_address[0]
        assert address.port == remote_address[1]

    def test____get_local_or_remote_address____closed_client(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        mock_udp_socket.reset_mock()

        # Act & Assert
        with pytest.raises(ClientClosedError):
            client.get_local_address()
        with pytest.raises(ClientClosedError):
            client.get_remote_address()

        mock_udp_socket.getsockname.assert_not_called()
        mock_udp_socket.getpeername.assert_not_called()

    def test____fileno____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        fd = client.fileno()

        # Assert
        mock_udp_socket.fileno.assert_called_once_with()
        assert fd == mock_udp_socket.fileno.return_value

    def test____socket_property____cached_attribute(
        self,
        client: UDPNetworkClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert client.socket is client.socket

    def test____send_packet____send_bytes_to_socket(
        self,
        client: UDPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_datagram_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: UDPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockopt.return_value = errno.ECONNREFUSED

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.errno == errno.ECONNREFUSED
        mock_datagram_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____closed_client_error(
        self,
        client: UDPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_datagram_endpoint.send_packet.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client: UDPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_endpoint.send_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_datagram_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_datagram_endpoint.close.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    def test____recv_packet____receive_bytes_from_socket(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_endpoint.recv_packet.side_effect = [mocker.sentinel.packet]

        # Act
        packet = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_datagram_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)
        assert packet is mocker.sentinel.packet

    def test____recv_packet____protocol_parse_error(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        expected_error = DatagramProtocolParseError(DeserializeError("Sorry"))
        mock_datagram_endpoint.recv_packet.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is expected_error
        mock_datagram_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)

    def test____recv_packet____closed_client_error(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_datagram_endpoint.recv_packet.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____recv_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_endpoint.recv_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_datagram_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)
        mock_datagram_endpoint.close.assert_not_called()

    def test____special_case____separate_send_and_receive_locks(
        self,
        client: UDPNetworkClient[Any, Any],
        send_timeout: float | None,
        recv_timeout: float | None,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def recv_side_effect(**kwargs: Any) -> bytes:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)
            raise ConnectionAbortedError

        mock_datagram_endpoint.recv_packet.side_effect = recv_side_effect

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_datagram_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____special_case____close_during_recv_call(
        self,
        closed_socket_errno: int,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        def recv_side_effect(**kwargs: Any) -> bytes:
            client.close()
            raise OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        mock_datagram_endpoint.recv_packet.side_effect = recv_side_effect

        # Act & Assert
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)


class TestUDPSocketFactory:
    @pytest.fixture
    @staticmethod
    def socket_families(request: pytest.FixtureRequest) -> tuple[int, ...]:
        return tuple(AddressFamily(f) for f in getattr(request, "param", (AF_INET, AF_INET6)))

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_getaddrinfo(socket_families: Sequence[int], mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "socket.getaddrinfo",
            autospec=True,
            side_effect=lambda host, port, *args, **kwargs: (
                datagram_addrinfo_list(port, socket_families) if socket_families else []
            ),
        )

    @pytest.fixture
    @staticmethod
    def mock_socket_ipv4(mock_udp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_udp_socket_factory()

    @pytest.fixture
    @staticmethod
    def mock_socket_ipv6(mock_udp_socket_factory: Callable[[], MagicMock]) -> MagicMock:
        socket = mock_udp_socket_factory()
        socket.family = AF_INET6
        return socket

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_cls(
        socket_families: Sequence[AddressFamily],
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        socket_dict = {AF_INET: mock_socket_ipv4, AF_INET6: mock_socket_ipv6}
        return mocker.patch("socket.socket", side_effect=[socket_dict[f] for f in socket_families])

    @pytest.mark.parametrize("socket_families", [[AF_INET]], indirect=True)
    def test____create_udp_socket____default(
        self,
        mock_socket_cls: MagicMock,
        mock_getaddrinfo: MagicMock,
        mock_socket_ipv4: MagicMock,
    ) -> None:
        # Arrange

        # Act
        udp_socket = create_udp_socket(("remote_address", 12345))

        # Assert
        assert udp_socket is mock_socket_ipv4
        mock_getaddrinfo.assert_called_once_with("remote_address", 12345, family=AF_UNSPEC, type=SOCK_DGRAM)
        mock_socket_cls.assert_called_once_with(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        mock_socket_ipv4.bind.assert_not_called()
        mock_socket_ipv4.connect.assert_called_once_with(("127.0.0.1", 12345))
        mock_socket_ipv4.setsockopt.assert_not_called()
        mock_socket_ipv4.close.assert_not_called()

    @pytest.mark.parametrize("with_local_address", [False, True], ids=lambda boolean: f"with_local_address=={boolean}")
    @pytest.mark.parametrize(
        ["family", "socket_families"],
        [
            pytest.param(AF_UNSPEC, (AF_INET, AF_INET6), id="AF_UNSPEC"),
            pytest.param(AF_INET, (AF_INET,), id="AF_INET"),
            pytest.param(AF_INET6, (AF_INET6,), id="AF_INET6"),
        ],
        indirect=["socket_families"],
    )
    def test____create_udp_socket____with_parameters(
        self,
        with_local_address: bool,
        family: int,
        socket_families: tuple[int, ...],
        mock_socket_cls: MagicMock,
        mock_getaddrinfo: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] = ("remote_address", 12345)
        local_address: tuple[str, int] | None = ("local_address", 11111) if with_local_address else None

        # Act
        udp_socket = create_udp_socket(
            local_address=local_address,
            remote_address=remote_address,
            family=family,
        )

        # Assert
        mock_getaddrinfo.assert_called_once_with(
            *remote_address,
            family=family,
            type=SOCK_DGRAM,
        )
        if AF_INET in socket_families:
            assert udp_socket is mock_socket_ipv4
            mock_socket_cls.assert_called_once_with(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
            used_socket = mock_socket_ipv4
            not_used_socket = mock_socket_ipv6
        else:
            assert udp_socket is mock_socket_ipv6
            mock_socket_cls.assert_called_once_with(AF_INET6, SOCK_DGRAM, IPPROTO_UDP)
            used_socket = mock_socket_ipv6
            not_used_socket = mock_socket_ipv4
        used_socket.setsockopt.assert_not_called()
        if local_address is None:
            used_socket.bind.assert_not_called()
        else:
            used_socket.bind.assert_called_once_with(local_address)
        if used_socket is mock_socket_ipv4:
            used_socket.connect.assert_called_once_with(("127.0.0.1", 12345))
        else:
            used_socket.connect.assert_called_once_with(("::1", 12345, 0, 0))
        used_socket.close.assert_not_called()

        not_used_socket.setsockopt.assert_not_called()
        not_used_socket.bind.assert_not_called()
        not_used_socket.connect.assert_not_called()

    @pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
    def test____create_udp_socket____first_failed(
        self,
        fail_on: Literal["socket", "bind", "connect"],
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] = ("remote_address", 12345)
        local_address: tuple[str, int] = ("local_address", 11111)

        match fail_on:
            case "socket":
                mock_socket_cls.side_effect = [error_from_errno(errno.EAFNOSUPPORT), mock_socket_ipv6]
            case "bind":
                mock_socket_ipv4.bind.side_effect = error_from_errno(errno.EADDRINUSE)
            case "connect":
                if remote_address is None:
                    pytest.skip("Bad parameter combination")
                mock_socket_ipv4.connect.side_effect = error_from_errno(errno.ECONNREFUSED)
            case _:
                assert_never(fail_on)

        # Act
        udp_socket = create_udp_socket(local_address=local_address, remote_address=remote_address)

        # Assert
        assert udp_socket is mock_socket_ipv6
        assert mock_socket_cls.call_args_list == [
            mocker.call(AF_INET, SOCK_DGRAM, IPPROTO_UDP),
            mocker.call(AF_INET6, SOCK_DGRAM, IPPROTO_UDP),
        ]
        if fail_on != "socket":
            mock_socket_ipv4.bind.assert_called_once_with(local_address)
            match fail_on:
                case "bind":
                    mock_socket_ipv4.connect.assert_not_called()
                case "connect":
                    mock_socket_ipv4.connect.assert_called_once_with(("127.0.0.1", 12345))
                case _:
                    assert_never(fail_on)
            mock_socket_ipv4.close.assert_called_once_with()
        else:
            mock_socket_ipv4.bind.assert_not_called()
            mock_socket_ipv4.connect.assert_not_called()
            mock_socket_ipv4.close.assert_not_called()

        mock_socket_ipv6.bind.assert_called_once_with(local_address)
        mock_socket_ipv6.connect.assert_called_once_with(("::1", 12345, 0, 0))
        mock_socket_ipv6.close.assert_not_called()

    @pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
    def test____create_udp_socket____all_failed(
        self,
        fail_on: Literal["socket", "bind", "connect"],
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] = ("remote_address", 12345)
        local_address: tuple[str, int] = ("local_address", 11111)

        match fail_on:
            case "socket":
                mock_socket_cls.side_effect = error_from_errno(errno.EAFNOSUPPORT)
            case "bind":
                mock_socket_ipv4.bind.side_effect = error_from_errno(errno.EADDRINUSE)
                mock_socket_ipv6.bind.side_effect = error_from_errno(errno.EADDRINUSE)
            case "connect":
                if remote_address is None:
                    pytest.skip("Bad parameter combination")
                mock_socket_ipv4.connect.side_effect = error_from_errno(errno.ECONNREFUSED)
                mock_socket_ipv6.connect.side_effect = error_from_errno(errno.ECONNREFUSED)
            case _:
                assert_never(fail_on)

        # Act
        with pytest.raises(ExceptionGroup) as exc_info:
            _ = create_udp_socket(local_address=local_address, remote_address=remote_address)

        # Assert
        os_errors, exc = exc_info.value.split(OSError)
        assert exc is None
        assert os_errors is not None
        assert len(os_errors.exceptions) == 2
        assert all(isinstance(exc, OSError) for exc in os_errors.exceptions)
        del os_errors

        assert mock_socket_cls.call_args_list == [
            mocker.call(AF_INET, SOCK_DGRAM, IPPROTO_UDP),
            mocker.call(AF_INET6, SOCK_DGRAM, IPPROTO_UDP),
        ]
        if fail_on != "socket":
            mock_socket_ipv4.bind.assert_called_once_with(local_address)
            mock_socket_ipv6.bind.assert_called_once_with(local_address)
            match fail_on:
                case "bind":
                    mock_socket_ipv4.connect.assert_not_called()
                    mock_socket_ipv6.connect.assert_not_called()
                case "connect":
                    mock_socket_ipv4.connect.assert_called_once_with(("127.0.0.1", 12345))
                    mock_socket_ipv6.connect.assert_called_once_with(("::1", 12345, 0, 0))
                case _:
                    assert_never(fail_on)
            mock_socket_ipv4.close.assert_called_once_with()
            mock_socket_ipv6.close.assert_called_once_with()
        else:
            mock_socket_ipv4.bind.assert_not_called()
            mock_socket_ipv4.connect.assert_not_called()
            mock_socket_ipv4.close.assert_not_called()

            mock_socket_ipv6.bind.assert_not_called()
            mock_socket_ipv6.connect.assert_not_called()
            mock_socket_ipv6.close.assert_not_called()

    @pytest.mark.parametrize("fail_on", ["socket", "bind"], ids=lambda fail_on: f"fail_on=={fail_on}")
    def test____create_udp_socket____unrelated_exception(
        self,
        fail_on: Literal["socket", "bind"],
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] = ("remote_address", 12345)
        local_address: tuple[str, int] = ("local_address", 11111)

        expected_failure_exception = BaseException()

        match fail_on:
            case "socket":
                mock_socket_cls.side_effect = expected_failure_exception
            case "bind":
                mock_socket_ipv4.bind.side_effect = expected_failure_exception
            case _:
                assert_never(fail_on)

        # Act
        with pytest.raises(BaseException) as exc_info:
            _ = create_udp_socket(local_address=local_address, remote_address=remote_address)

        # Assert
        assert exc_info.value is expected_failure_exception
        if fail_on != "socket":
            mock_socket_ipv4.close.assert_called_once_with()

    @pytest.mark.parametrize("socket_families", [[]], indirect=True)
    def test____create_udp_socket____getaddrinfo_returned_empty_list(
        self,
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] = ("remote_address", 12345)
        local_address: tuple[str, int] = ("local_address", 11111)

        host_with_error = "remote_address" if remote_address is not None else "local_address"

        # Act
        with pytest.raises(OSError, match=rf"^getaddrinfo\({host_with_error!r}\) returned empty list$"):
            _ = create_udp_socket(local_address=local_address, remote_address=remote_address)

        # Assert
        mock_socket_cls.assert_not_called()
        mock_socket_ipv4.bind.assert_not_called()
        mock_socket_ipv6.bind.assert_not_called()
