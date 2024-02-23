from __future__ import annotations

import contextlib
import errno
import os
from collections.abc import Callable, Sequence
from selectors import EVENT_READ, EVENT_WRITE
from socket import AF_INET, AF_INET6, AF_UNSPEC, AI_PASSIVE, IPPROTO_UDP, SO_ERROR, SOCK_DGRAM, SOL_SOCKET, AddressFamily
from typing import TYPE_CHECKING, Any, Literal, assert_never

from easynetwork.clients.udp import UDPNetworkClient, _create_udp_socket as create_udp_socket
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel._utils import error_from_errno
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS, MAX_DATAGRAM_BUFSIZE
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from ..._utils import datagram_addrinfo_list
from ...base import UNSUPPORTED_FAMILIES
from .base import BaseTestClient


class TestUDPNetworkClient(BaseTestClient):
    @pytest.fixture(scope="class", params=["AF_INET", "AF_INET6"])
    @staticmethod
    def socket_family(request: Any) -> Any:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture
    @staticmethod
    def socket_fileno() -> int:
        return 12345

    @pytest.fixture(scope="class")
    @staticmethod
    def global_local_address() -> tuple[str, int]:
        return ("local_address", 12345)

    @pytest.fixture(scope="class")
    @staticmethod
    def global_remote_address() -> tuple[str, int]:
        return ("remote_address", 5000)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_create_udp_socket(mocker: MockerFixture, mock_udp_socket: MagicMock) -> MagicMock:
        return mocker.patch(f"{UDPNetworkClient.__module__}._create_udp_socket", autospec=True, return_value=mock_udp_socket)

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        request: Any,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int] | None:
        address: tuple[str, int] | None = getattr(request, "param", global_local_address)
        cls.set_local_address_to_socket_mock(mock_udp_socket, socket_family, address)
        return address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_remote_address_to_socket_mock(mock_udp_socket, socket_family, global_remote_address)
        return global_remote_address

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_udp_socket: MagicMock,
        socket_family: int,
        socket_fileno: int,
    ) -> None:
        mock_udp_socket.family = socket_family
        mock_udp_socket.fileno.return_value = socket_fileno
        mock_udp_socket.gettimeout.return_value = 0
        mock_udp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()
        mock_udp_socket.send.side_effect = lambda data: len(data)
        del mock_udp_socket.sendto
        del mock_udp_socket.sendall
        del mock_udp_socket.recvfrom

    @pytest.fixture  # DO NOT set autouse=True
    @staticmethod
    def setup_protocol_mock(mock_datagram_protocol: MagicMock, mocker: MockerFixture) -> None:
        sentinel = mocker.sentinel

        def make_datagram_side_effect(packet: Any) -> bytes:
            return str(packet).encode("ascii").removeprefix(b"sentinel.")

        def build_packet_from_datagram_side_effect(data: bytes) -> Any:
            return getattr(sentinel, data.decode("ascii"))

        mock_datagram_protocol.make_datagram.side_effect = make_datagram_side_effect
        mock_datagram_protocol.build_packet_from_datagram.side_effect = build_packet_from_datagram_side_effect

    @pytest.fixture(params=["REMOTE_ADDRESS", "EXTERNAL_SOCKET"])
    @staticmethod
    def use_external_socket(request: Any) -> str:
        return request.param

    @pytest.fixture
    @staticmethod
    def retry_interval(request: Any) -> float:
        return getattr(request, "param", float("+inf"))

    @pytest.fixture
    @staticmethod
    def client(
        use_external_socket: str,
        remote_address: tuple[str, int],
        retry_interval: float,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> UDPNetworkClient[Any, Any]:
        try:
            match use_external_socket:
                case "REMOTE_ADDRESS":
                    return UDPNetworkClient(
                        remote_address,
                        protocol=mock_datagram_protocol,
                        retry_interval=retry_interval,
                    )
                case "EXTERNAL_SOCKET":
                    return UDPNetworkClient(
                        mock_udp_socket,
                        protocol=mock_datagram_protocol,
                        retry_interval=retry_interval,
                    )
                case invalid:
                    pytest.fail(f"Invalid fixture param: Got {invalid!r}")
        finally:
            mock_udp_socket.reset_mock()

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(float("+inf"), id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: Any) -> Any:
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
    def send_timeout(request: Any) -> Any:
        return request.param

    def test____dunder_init____create_datagram_endpoint____default(
        self,
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = UDPNetworkClient(remote_address, mock_datagram_protocol)

        # Assert
        mock_create_udp_socket.assert_called_once_with(remote_address=remote_address)
        assert mock_udp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setblocking(False),
        ]

    @pytest.mark.parametrize(
        "local_address", [None, ("local_address", 12345)], ids=lambda p: f"local_address=={p}", indirect=True
    )
    @pytest.mark.parametrize("reuse_port", [False, True], ids=lambda p: f"reuse_port=={p}")
    def test____dunder_init____create_datagram_endpoint____with_parameters(
        self,
        reuse_port: bool,
        socket_family: int,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = UDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            family=socket_family,
            local_address=local_address,
            reuse_port=reuse_port,
        )

        # Assert
        mock_create_udp_socket.assert_called_once_with(
            family=socket_family,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=reuse_port,
        )
        assert mock_udp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setblocking(False),
        ]

    @pytest.mark.parametrize(
        "local_address", [None, ("local_address", 12345)], ids=lambda p: f"local_address=={p}", indirect=True
    )
    @pytest.mark.parametrize("reuse_port", [False, True], ids=lambda p: f"reuse_port=={p}")
    def test____dunder_init____create_datagram_endpoint____with_parameters____explicit_AF_UNSPEC(
        self,
        reuse_port: bool,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        _ = UDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            family=AF_UNSPEC,
            local_address=local_address,
            reuse_port=reuse_port,
        )

        # Assert
        mock_create_udp_socket.assert_called_once_with(
            family=AF_UNSPEC,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=reuse_port,
        )

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
    def test____dunder_init____create_datagram_endpoint____invalid_family(
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

    @pytest.mark.parametrize("bound", [False, True], ids=lambda p: f"bound=={p}")
    def test____dunder_init____use_given_socket____default(
        self,
        bound: bool,
        socket_family: int,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if not bound:
            mock_udp_socket.getsockname.return_value = self.get_resolved_any_addr(socket_family)

        # Act
        _ = UDPNetworkClient(mock_udp_socket, mock_datagram_protocol)

        # Assert
        mock_create_udp_socket.assert_not_called()
        if bound:
            assert mock_udp_socket.mock_calls == [
                mocker.call.getsockname(),
                mocker.call.getpeername(),
                mocker.call.setblocking(False),
            ]
        else:
            mock_udp_socket.bind.assert_called_once_with(("localhost", 0))
            assert mock_udp_socket.mock_calls == [
                mocker.call.getsockname(),
                mocker.call.bind(("localhost", 0)),
                mocker.call.getpeername(),
                mocker.call.setblocking(False),
            ]

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
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

    def test____dunder_init____use_given_socket____invalid_socket_type_error(
        self,
        mock_tcp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = UDPNetworkClient(
                mock_tcp_socket,
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

    def test____dunder_init____protocol____invalid_value(
        self,
        mock_udp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = UDPNetworkClient(
                mock_udp_socket,
                protocol=mock_stream_protocol,
            )

    @pytest.mark.parametrize("retry_interval", [0, -12.34])
    def test____dunder_init____retry_interval____invalid_value(
        self,
        retry_interval: float,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^retry_interval must be a strictly positive float$"):
            _ = UDPNetworkClient(
                mock_udp_socket,
                protocol=mock_datagram_protocol,
                retry_interval=retry_interval,
            )

    def test____close____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()

        # Act
        client.close()

        # Assert
        assert client.is_closed()
        mock_udp_socket.close.assert_called_once_with()

    def test____get_local_address____return_saved_address(
        self,
        client: UDPNetworkClient[Any, Any],
        socket_family: int,
        local_address: tuple[str, int],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

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
        socket_fileno: int,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        fd = client.fileno()

        # Assert
        mock_udp_socket.fileno.assert_called_once_with()
        assert fd == socket_fileno

    def test____fileno____closed_client(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()
        mock_udp_socket.fileno.reset_mock()

        # Act
        fd = client.fileno()

        # Assert
        mock_udp_socket.fileno.assert_called_once()
        assert fd == -1

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet____send_bytes_to_socket(
        self,
        client: UDPNetworkClient[Any, Any],
        send_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.send.assert_called_once_with(b"packet")
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet____send_bytes_to_socket____blocking_operation(
        self,
        client: UDPNetworkClient[Any, Any],
        socket_fileno: int,
        send_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.send.side_effect = [BlockingIOError, len(b"packet")]

        # Act
        with pytest.raises(TimeoutError) if send_timeout == 0 else contextlib.nullcontext():
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        if send_timeout != 0:
            mock_selector_register.assert_called_once_with(socket_fileno, EVENT_WRITE)
            if send_timeout in (None, float("+inf")):
                mock_selector_select.assert_called_once_with()
            else:
                mock_selector_select.assert_called_once_with(send_timeout)
            assert mock_udp_socket.send.call_args_list == [mocker.call(b"packet") for _ in range(2)]
            mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
            mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
        else:
            mock_selector_register.assert_not_called()
            mock_selector_select.assert_not_called()
            assert mock_udp_socket.send.call_args_list == [mocker.call(b"packet")]
            mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
            mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockopt.return_value = errno.ECONNREFUSED

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == errno.ECONNREFUSED
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.send.assert_called_once()
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet____closed_client_error(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: UDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.send.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.send.assert_called_once()
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet____blocking_or_not____receive_bytes_from_socket(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = [b"packet"]

        # Act
        packet = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()

        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()

        mock_udp_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet____blocking_or_not____protocol_parse_error(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = [b"packet"]
        expected_error = DatagramProtocolParseError(DeserializeError("Sorry"))
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_udp_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert exc_info.value is expected_error

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet____blocking_or_not____closed_client_error(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.recv.assert_not_called()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____recv_packet____blocking_or_not____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.parametrize(
        "recv_timeout",
        [
            pytest.param(0, id="null timeout"),
            pytest.param(123456789, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet____no_block____timeout(
        self,
        client: UDPNetworkClient[Any, Any],
        socket_fileno: int,
        recv_timeout: int,
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_selector_register: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = BlockingIOError
        self.selector_timeout_after_n_calls(mock_selector_select, mocker, nb_calls=1)

        # Act & Assert
        with pytest.raises(TimeoutError):
            _ = client.recv_packet(timeout=recv_timeout)

        if recv_timeout == 0:
            assert len(mock_udp_socket.recv.call_args_list) == 1
            mock_selector_register.assert_not_called()
            mock_selector_select.assert_not_called()
        else:
            assert len(mock_udp_socket.recv.call_args_list) == 2
            mock_selector_register.assert_called_with(socket_fileno, EVENT_READ)
            mock_selector_select.assert_any_call(recv_timeout)
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.parametrize(
        "recv_timeout",
        [
            pytest.param(0, id="null timeout"),
            pytest.param(123456789, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets____yields_available_packets_with_given_timeout(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: int,
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = [b"packet_1", b"packet_2", BlockingIOError]
        self.selector_timeout_after_n_calls(mock_selector_select, mocker, nb_calls=0)

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_udp_socket.recv.call_args_list == [mocker.call(MAX_DATAGRAM_BUFSIZE) for _ in range(3)]
        assert mock_datagram_protocol.build_packet_from_datagram.call_args_list == [
            mocker.call(b"packet_1"),
            mocker.call(b"packet_2"),
        ]
        assert packets == [
            mocker.sentinel.packet_1,
            mocker.sentinel.packet_2,
        ]

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets____yields_available_packets_until_error(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = [b"packet_1", b"packet_2", OSError]

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_udp_socket.recv.call_args_list == [mocker.call(MAX_DATAGRAM_BUFSIZE) for _ in range(3)]
        assert mock_datagram_protocol.build_packet_from_datagram.call_args_list == [
            mocker.call(b"packet_1"),
            mocker.call(b"packet_2"),
        ]
        assert packets == [
            mocker.sentinel.packet_1,
            mocker.sentinel.packet_2,
        ]

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets____closed_client_during_iteration(
        self,
        client: UDPNetworkClient[Any, Any],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recv.side_effect = [b"packet_1"]

        # Act & Assert
        iterator = client.iter_received_packets(timeout=recv_timeout)
        packet_1 = next(iterator)
        assert packet_1 is mocker.sentinel.packet_1
        client.close()
        assert client.is_closed()
        with pytest.raises(StopIteration):
            _ = next(iterator)


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
        udp_socket = create_udp_socket()

        # Assert
        assert udp_socket is mock_socket_ipv4
        mock_getaddrinfo.assert_called_once_with("localhost", 0, family=AF_UNSPEC, type=SOCK_DGRAM, flags=AI_PASSIVE)
        mock_socket_cls.assert_called_once_with(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 0))
        mock_socket_ipv4.connect.assert_not_called()
        mock_socket_ipv4.setsockopt.assert_not_called()
        mock_socket_ipv4.close.assert_not_called()

    @pytest.mark.parametrize("with_local_address", [False, True], ids=lambda boolean: f"with_local_address=={boolean}")
    @pytest.mark.parametrize("with_remote_address", [False, True], ids=lambda boolean: f"with_remote_address=={boolean}")
    @pytest.mark.parametrize("set_reuse_port", [False, True], ids=lambda boolean: f"set_reuse_port=={boolean}")
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
        with_remote_address: bool,
        set_reuse_port: bool,
        family: int,
        socket_families: tuple[int, ...],
        mock_socket_cls: MagicMock,
        mock_getaddrinfo: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
        SO_REUSEPORT: int,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] | None = ("remote_address", 12345) if with_remote_address else None
        local_address: tuple[str, int] | None = ("local_address", 11111) if with_local_address else None
        expected_local_address: tuple[str, int] = local_address if local_address is not None else ("localhost", 0)

        # Act
        udp_socket = create_udp_socket(
            local_address=local_address,
            remote_address=remote_address,
            family=family,
            reuse_port=set_reuse_port,
        )

        # Assert
        if remote_address is None:
            mock_getaddrinfo.assert_called_once_with(
                *expected_local_address,
                family=family,
                type=SOCK_DGRAM,
                flags=AI_PASSIVE,
            )
        else:
            mock_getaddrinfo.assert_called_once_with(
                *remote_address,
                family=family,
                type=SOCK_DGRAM,
                flags=0,
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
        if set_reuse_port:
            used_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_REUSEPORT, True)
        else:
            used_socket.setsockopt.assert_not_called()
        if used_socket is mock_socket_ipv4:
            if remote_address is None:
                used_socket.bind.assert_called_once_with(("127.0.0.1", expected_local_address[1]))
                used_socket.connect.assert_not_called()
            else:
                used_socket.bind.assert_called_once_with(expected_local_address)
                used_socket.connect.assert_called_once_with(("127.0.0.1", 12345))
        else:
            if remote_address is None:
                used_socket.bind.assert_called_once_with(("::1", expected_local_address[1], 0, 0))
                used_socket.connect.assert_not_called()
            else:
                used_socket.bind.assert_called_once_with(expected_local_address)
                used_socket.connect.assert_called_once_with(("::1", 12345, 0, 0))
        used_socket.close.assert_not_called()

        not_used_socket.setsockopt.assert_not_called()
        not_used_socket.bind.assert_not_called()
        not_used_socket.connect.assert_not_called()

    @pytest.mark.parametrize("with_remote_address", [False, True], ids=lambda boolean: f"with_remote_address=={boolean}")
    @pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
    def test____create_udp_socket____first_failed(
        self,
        fail_on: Literal["socket", "bind", "connect"],
        with_remote_address: bool,
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] | None = ("remote_address", 12345) if with_remote_address else None
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
            if remote_address is None:
                mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
            else:
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

        if remote_address is None:
            mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
            mock_socket_ipv6.connect.assert_not_called()
        else:
            mock_socket_ipv6.bind.assert_called_once_with(local_address)
            mock_socket_ipv6.connect.assert_called_once_with(("::1", 12345, 0, 0))
        mock_socket_ipv6.close.assert_not_called()

    @pytest.mark.parametrize("with_remote_address", [False, True], ids=lambda boolean: f"with_remote_address=={boolean}")
    @pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
    def test____create_udp_socket____all_failed(
        self,
        fail_on: Literal["socket", "bind", "connect"],
        with_remote_address: bool,
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] | None = ("remote_address", 12345) if with_remote_address else None
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
            if remote_address is None:
                mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
                mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
            else:
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

    @pytest.mark.usefixtures("remove_SO_REUSEPORT_support")
    @pytest.mark.parametrize("with_remote_address", [False, True], ids=lambda boolean: f"with_remote_address=={boolean}")
    def test____create_udp_socket____SO_REUSEPORT_not_supported(
        self,
        with_remote_address: bool,
        mock_socket_ipv4: MagicMock,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] | None = ("remote_address", 12345) if with_remote_address else None
        local_address: tuple[str, int] = ("local_address", 11111)

        # Act
        with pytest.raises(ValueError):
            _ = create_udp_socket(local_address=local_address, remote_address=remote_address, reuse_port=True)

        # Assert
        mock_socket_ipv4.close.assert_called_once_with()

    @pytest.mark.parametrize("with_remote_address", [False, True], ids=lambda boolean: f"with_remote_address=={boolean}")
    @pytest.mark.parametrize("fail_on", ["socket", "bind"], ids=lambda fail_on: f"fail_on=={fail_on}")
    def test____create_udp_socket____unrelated_exception(
        self,
        fail_on: Literal["socket", "bind"],
        with_remote_address: bool,
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] | None = ("remote_address", 12345) if with_remote_address else None
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
    @pytest.mark.parametrize("with_remote_address", [False, True], ids=lambda boolean: f"with_remote_address=={boolean}")
    def test____create_udp_socket____getaddrinfo_returned_empty_list(
        self,
        with_remote_address: bool,
        mock_socket_cls: MagicMock,
        mock_socket_ipv4: MagicMock,
        mock_socket_ipv6: MagicMock,
    ) -> None:
        # Arrange
        remote_address: tuple[str, int] | None = ("remote_address", 12345) if with_remote_address else None
        local_address: tuple[str, int] = ("local_address", 11111)

        host_with_error = "remote_address" if remote_address is not None else "local_address"

        # Act
        with pytest.raises(OSError, match=rf"^getaddrinfo\({host_with_error!r}\) returned empty list$"):
            _ = create_udp_socket(local_address=local_address, remote_address=remote_address)

        # Assert
        mock_socket_cls.assert_not_called()
        mock_socket_ipv4.bind.assert_not_called()
        mock_socket_ipv6.bind.assert_not_called()
