# -*- coding: utf-8 -*-

from __future__ import annotations

import errno
import os
from selectors import EVENT_READ, EVENT_WRITE
from socket import AF_INET, AF_INET6, AF_UNSPEC, AI_PASSIVE, IPPROTO_UDP, SOCK_DGRAM, SOL_SOCKET
from typing import TYPE_CHECKING, Any

from easynetwork.api_sync.client.udp import UDPNetworkClient, UDPNetworkEndpoint
from easynetwork.exceptions import ClientClosedError
from easynetwork.tools.socket import CLOSED_SOCKET_ERRNOS, MAX_DATAGRAM_BUFSIZE, IPv4SocketAddress, IPv6SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from ...base import UNSUPPORTED_FAMILIES
from .base import BaseTestClient


class TestUDPNetworkEndpoint(BaseTestClient):
    @pytest.fixture(scope="class", params=["AF_INET", "AF_INET6"])
    @staticmethod
    def socket_family(request: Any) -> Any:
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
    @staticmethod
    def mock_socket_proxy_cls(mocker: MockerFixture, mock_udp_socket: MagicMock) -> MagicMock:
        return mocker.patch(f"{UDPNetworkClient.__module__}.SocketProxy", return_value=mock_udp_socket)

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

    @pytest.fixture(autouse=True, params=[False, True], ids=lambda p: f"remote_address=={p}")
    @classmethod
    def remote_address(
        cls,
        request: Any,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int] | None:
        match request.param:
            case True:
                cls.set_remote_address_to_socket_mock(mock_udp_socket, socket_family, global_remote_address)
                return global_remote_address
            case False:
                cls.configure_socket_mock_to_raise_ENOTCONN(mock_udp_socket)
                return None
            case invalid:
                pytest.fail(f"Invalid fixture param: Got {invalid!r}")

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_udp_socket: MagicMock,
        socket_family: int,
    ) -> None:
        mock_udp_socket.family = socket_family
        mock_udp_socket.gettimeout.return_value = 0
        mock_udp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet_to()
        mock_udp_socket.send.side_effect = lambda data: len(data)
        mock_udp_socket.sendto.side_effect = lambda data, address: len(data)
        del mock_udp_socket.sendall

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

    @pytest.fixture()
    @staticmethod
    def client(
        use_external_socket: str,
        remote_address: tuple[str, int] | None,
        retry_interval: float,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> UDPNetworkEndpoint[Any, Any]:
        try:
            match use_external_socket:
                case "REMOTE_ADDRESS":
                    mocker.patch("socket.getaddrinfo", return_value=[(AF_INET, SOCK_DGRAM, IPPROTO_UDP, "", ("0.0.0.0", 0))])
                    mocker.patch("socket.socket", return_value=mock_udp_socket)
                    return UDPNetworkEndpoint(
                        protocol=mock_datagram_protocol,
                        remote_address=remote_address,
                        retry_interval=retry_interval,
                    )
                case "EXTERNAL_SOCKET":
                    return UDPNetworkEndpoint(
                        socket=mock_udp_socket,
                        protocol=mock_datagram_protocol,
                        retry_interval=retry_interval,
                    )
                case invalid:
                    pytest.fail(f"Invalid fixture param: Got {invalid!r}")
        finally:
            mock_udp_socket.settimeout.reset_mock()

    @pytest.fixture
    @staticmethod
    def sender_address(request: Any, global_remote_address: tuple[str, int]) -> tuple[str, int]:
        try:
            param: Any = request.param
        except AttributeError:
            return global_remote_address
        if param == "REMOTE":
            return global_remote_address
        host, port = param
        return host, port

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

    def test____dunder_init____create_datagram_endpoint____default(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_getaddrinfo = mocker.patch(
            "socket.getaddrinfo",
            return_value=[
                (AF_INET, SOCK_DGRAM, IPPROTO_UDP, "", ("0.0.0.0", 0)),
                (AF_INET6, SOCK_DGRAM, IPPROTO_UDP, "", ("::", 0)),
            ],
        )
        mock_socket_cls = mocker.patch("socket.socket", return_value=mock_udp_socket)
        mock_socket_proxy_cls.return_value = mocker.sentinel.proxy

        # Act
        endpoint: UDPNetworkEndpoint[Any, Any] = UDPNetworkEndpoint(protocol=mock_datagram_protocol)

        # Assert
        mock_getaddrinfo.assert_called_once_with(None, 0, family=AF_UNSPEC, type=SOCK_DGRAM, flags=AI_PASSIVE)
        mock_socket_cls.assert_called_once_with(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        mock_udp_socket.bind.assert_called_once_with(("0.0.0.0", 0))
        mock_udp_socket.connect.assert_not_called()
        mock_udp_socket.settimeout.assert_called_once_with(0)
        mock_udp_socket.setblocking.assert_not_called()
        mock_udp_socket.getpeername.assert_not_called()
        mock_socket_proxy_cls.assert_called_once_with(mock_udp_socket, lock=mocker.ANY)
        assert endpoint.socket is mocker.sentinel.proxy

    @pytest.mark.parametrize(
        "local_address", [None, ("local_address", 12345), ("", 11111)], ids=lambda p: f"local_address=={p}", indirect=True
    )
    @pytest.mark.parametrize("reuse_port", [False, True], ids=lambda p: f"reuse_port=={p}")
    def test____dunder_init____create_datagram_endpoint____with_parameters(
        self,
        socket_family: int,
        reuse_port: bool,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        SO_REUSEPORT: int = 123456
        monkeypatch.setattr("socket.SO_REUSEPORT", SO_REUSEPORT, raising=False)
        if local_address is None:
            expected_local_address = ("::", 0) if socket_family == AF_INET6 else ("0.0.0.0", 0)
        else:
            expected_local_address = local_address
        mock_getaddrinfo = mocker.patch(
            "socket.getaddrinfo",
            return_value=[
                (AF_INET6, SOCK_DGRAM, IPPROTO_UDP, "", expected_local_address)
                if socket_family == AF_INET6
                else (AF_INET, SOCK_DGRAM, IPPROTO_UDP, "", expected_local_address)
            ],
        )
        mock_socket_cls = mocker.patch("socket.socket", return_value=mock_udp_socket)

        # Act
        _ = UDPNetworkEndpoint(
            protocol=mock_datagram_protocol,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=reuse_port,
        )

        # Assert
        if local_address is None:
            mock_getaddrinfo.assert_called_once_with(None, 0, family=AF_UNSPEC, type=SOCK_DGRAM, flags=AI_PASSIVE)
        else:
            local_host, local_port = local_address
            mock_getaddrinfo.assert_called_once_with(
                local_host if local_host != "" else None,
                local_port,
                family=AF_UNSPEC,
                type=SOCK_DGRAM,
                flags=AI_PASSIVE,
            )
        mock_socket_cls.assert_called_once_with(socket_family, SOCK_DGRAM, IPPROTO_UDP)
        if reuse_port:
            mock_udp_socket.setsockopt.assert_any_call(SOL_SOCKET, SO_REUSEPORT, True)
        mock_udp_socket.bind.assert_called_once_with(expected_local_address)
        if remote_address is None:
            mock_udp_socket.connect.assert_not_called()
            mock_udp_socket.getpeername.assert_not_called()
        else:
            mock_udp_socket.connect.assert_called_once_with(remote_address)
            mock_udp_socket.getpeername.assert_called_once_with()
        mock_udp_socket.settimeout.assert_called_once_with(0)
        mock_udp_socket.setblocking.assert_not_called()
        mock_socket_proxy_cls.assert_called_once_with(mock_udp_socket, lock=mocker.ANY)

    @pytest.mark.parametrize("error_on", ["bind", "connect"])
    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    def test____dunder_init____create_datagram_endpoint____close_socket_if_an_error_occurs____OSError(
        self,
        error_on: str,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch(
            "socket.getaddrinfo",
            return_value=[
                (AF_INET, SOCK_DGRAM, IPPROTO_UDP, "", ("0.0.0.0", 0)),
                (AF_INET6, SOCK_DGRAM, IPPROTO_UDP, "", ("::", 0)),
            ],
        )
        mocker.patch("socket.socket", return_value=mock_udp_socket)
        mock_method: MagicMock = getattr(mock_udp_socket, error_on)
        mock_method.side_effect = OSError()

        # Act & Assert
        with pytest.raises(ExceptionGroup) as exc_info:
            _ = UDPNetworkEndpoint(
                protocol=mock_datagram_protocol,
                local_address=local_address,
                remote_address=remote_address,
            )
        match, exc = exc_info.value.split(OSError)
        assert match is not None and match.exceptions == (mock_method.side_effect, mock_method.side_effect)
        assert exc is None
        assert mock_udp_socket.close.call_count == 2

    @pytest.mark.parametrize("error_on", ["bind", "connect"])
    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    def test____dunder_init____create_datagram_endpoint____close_socket_if_an_error_occurs____any_other_exception(
        self,
        error_on: str,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch(
            "socket.getaddrinfo",
            return_value=[
                (AF_INET, SOCK_DGRAM, IPPROTO_UDP, "", ("0.0.0.0", 0)),
                (AF_INET6, SOCK_DGRAM, IPPROTO_UDP, "", ("::", 0)),
            ],
        )
        mocker.patch("socket.socket", return_value=mock_udp_socket)
        mock_method: MagicMock = getattr(mock_udp_socket, error_on)
        mock_method.side_effect = BaseException()

        # Act & Assert
        with pytest.raises(BaseException) as exc_info:
            _ = UDPNetworkEndpoint(
                protocol=mock_datagram_protocol,
                local_address=local_address,
                remote_address=remote_address,
            )
        assert exc_info.value is mock_method.side_effect
        mock_udp_socket.close.assert_called_once_with()

    def test____dunder_init____create_datagram_endpoint____getaddrinfo_error_empty_list(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_getaddrinfo = mocker.patch("socket.getaddrinfo", return_value=[])
        mock_socket_cls = mocker.patch("socket.socket", return_value=mock_udp_socket)

        # Act
        with pytest.raises(OSError, match=r"^getaddrinfo\('local_address'\) returned empty list$"):
            _ = UDPNetworkEndpoint(protocol=mock_datagram_protocol, local_address=("local_address", 0))

        # Assert
        mock_getaddrinfo.assert_called_once_with("local_address", 0, family=AF_UNSPEC, type=SOCK_DGRAM, flags=AI_PASSIVE)
        mock_socket_cls.assert_not_called()
        mock_udp_socket.bind.assert_not_called()
        mock_udp_socket.connect.assert_not_called()
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_udp_socket.getpeername.assert_not_called()

    @pytest.mark.parametrize("bound", [False, True], ids=lambda p: f"bound=={p}")
    def test____dunder_init____use_given_socket____default(
        self,
        bound: bool,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_socket_proxy_cls.return_value = mocker.sentinel.proxy
        if not bound:
            mock_udp_socket.getsockname.return_value = ("0.0.0.0", 0)

        # Act
        endpoint: UDPNetworkEndpoint[Any, Any] = UDPNetworkEndpoint(
            protocol=mock_datagram_protocol,
            socket=mock_udp_socket,
        )

        # Assert
        if bound:
            mock_udp_socket.bind.assert_not_called()
        else:
            mock_udp_socket.bind.assert_called_once_with(("", 0))
        mock_udp_socket.connect.assert_not_called()
        mock_udp_socket.settimeout.assert_called_once_with(0)
        mock_udp_socket.setblocking.assert_not_called()
        mock_udp_socket.getpeername.assert_called_once_with()
        mock_socket_proxy_cls.assert_called_once_with(mock_udp_socket, lock=mocker.ANY)
        assert endpoint.socket is mocker.sentinel.proxy

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
    def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = UDPNetworkEndpoint(
                protocol=mock_datagram_protocol,
                socket=mock_udp_socket,
            )

    def test____dunder_init____use_given_socket____invalid_socket_type_error(
        self,
        mock_tcp_socket: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^Invalid socket type$"):
            _ = UDPNetworkEndpoint(
                protocol=mock_datagram_protocol,
                socket=mock_tcp_socket,
            )

        # Assert
        mock_socket_proxy_cls.assert_not_called()
        mock_tcp_socket.getsockname.assert_not_called()
        mock_tcp_socket.getpeername.assert_not_called()
        mock_tcp_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("retry_interval", [0, -12.34])
    def test____dunder_init____retry_interval____invalid_value(
        self,
        retry_interval: float,
        mock_udp_socket: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^retry_interval must be a strictly positive float or None$"):
            _ = UDPNetworkEndpoint(
                protocol=mock_datagram_protocol,
                socket=mock_udp_socket,
                retry_interval=retry_interval,
            )

        # Assert
        mock_socket_proxy_cls.assert_not_called()
        mock_udp_socket.getsockname.assert_not_called()
        mock_udp_socket.getpeername.assert_not_called()
        mock_udp_socket.close.assert_not_called()

    def test____context____close_endpoint_at_end(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_close = mocker.patch.object(UDPNetworkEndpoint, "close")

        # Act
        with client:
            mock_close.assert_not_called()

        # Assert
        mock_close.assert_called_once_with()

    def test____close____default(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()

        # Act
        client.close()

        # Assert
        assert client.is_closed()
        mock_udp_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    def test____get_local_address____return_saved_address(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        client_closed: bool,
        socket_family: int,
        local_address: tuple[str, int],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.reset_mock()
        if client_closed:
            client.close()
            assert client.is_closed()

        # Act
        address = client.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_udp_socket.getsockname.assert_not_called()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    def test____get_remote_address____return_saved_address(
        self,
        use_external_socket: str,
        client: UDPNetworkEndpoint[Any, Any],
        client_closed: bool,
        remote_address: tuple[str, int] | None,
        socket_family: int,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        if use_external_socket == "REMOTE_ADDRESS" and remote_address is None:
            mock_udp_socket.getpeername.assert_not_called()
        else:
            mock_udp_socket.getpeername.assert_called_once()
        mock_udp_socket.getpeername.reset_mock()
        if client_closed:
            client.close()
            assert client.is_closed()

        # Act
        address = client.get_remote_address()

        # Assert
        if remote_address is None:
            assert address is None
        else:
            if socket_family == AF_INET6:
                assert isinstance(address, IPv6SocketAddress)
            else:
                assert isinstance(address, IPv4SocketAddress)
            assert address.host == remote_address[0]
            assert address.port == remote_address[1]
        mock_udp_socket.getpeername.assert_not_called()

    def test____fileno____default(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.fileno.return_value = mocker.sentinel.fileno

        # Act
        fd = client.fileno()

        # Assert
        mock_udp_socket.fileno.assert_called_once_with()
        assert fd is mocker.sentinel.fileno

    def test____fileno____closed_client(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        fd = client.fileno()

        # Assert
        mock_udp_socket.fileno.assert_not_called()
        assert fd == -1

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____without_remote____default(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        target_address: tuple[str, int] = ("remote_address", 5000)

        # Act
        client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.send.assert_not_called()
        mock_udp_socket.sendto.assert_called_once_with(b"packet", target_address)
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____without_remote____blocking_operation(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        target_address: tuple[str, int] = ("remote_address", 5000)

        mock_udp_socket.sendto.side_effect = [BlockingIOError, len(b"packet")]

        # Act
        client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_register.assert_called_once_with(mock_udp_socket, EVENT_WRITE)
        mock_selector_select.assert_called_once_with(None)
        mock_udp_socket.send.assert_not_called()
        assert mock_udp_socket.sendto.mock_calls == [mocker.call(b"packet", target_address) for _ in range(2)]
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____without_remote____None_address_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^Invalid address: must not be None$"):
            client.send_packet_to(mocker.sentinel.packet, None)

        # Assert
        mock_udp_socket.send.assert_not_called()
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.sendto.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("target_address", [None, ("remote_address", 5000)], ids=lambda p: f"target_address=={p}")
    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____with_remote____default(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        target_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        # Act
        client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.sendto.assert_not_called()
        mock_udp_socket.send.assert_called_once_with(b"packet")
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("target_address", [None, ("remote_address", 5000)], ids=lambda p: f"target_address=={p}")
    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____with_remote____blocking_operation(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        target_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        mock_udp_socket.send.side_effect = [BlockingIOError, len(b"packet")]

        # Act
        client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_register.assert_called_once_with(mock_udp_socket, EVENT_WRITE)
        mock_selector_select.assert_called_once_with(None)
        mock_udp_socket.sendto.assert_not_called()
        assert mock_udp_socket.send.mock_calls == [mocker.call(b"packet") for _ in range(2)]
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____with_remote____invalid_target_address(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        target_address: tuple[str, int] = ("address_other_than_remote", 9999)

        # Act
        with pytest.raises(ValueError, match=r"^Invalid address: must be None or .+$"):
            client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.sendto.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____raise_error_saved_in_SO_ERROR_option(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        global_remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from errno import ECONNREFUSED
        from socket import SO_ERROR, SOL_SOCKET

        mock_udp_socket.getsockopt.return_value = ECONNREFUSED

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet_to(mocker.sentinel.packet, global_remote_address)

        # Assert
        assert exc_info.value.errno == ECONNREFUSED
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        if client.get_remote_address() is not None:
            mock_udp_socket.sendto.assert_not_called()
            mock_udp_socket.send.assert_called_once()
        else:
            mock_udp_socket.sendto.assert_called_once()
            mock_udp_socket.send.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____closed_client_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        remote_address: tuple[str, int] | None,
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
            client.send_packet_to(mocker.sentinel.packet, remote_address)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.sendto.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_packet_to____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: UDPNetworkEndpoint[Any, Any],
        global_remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if client.get_remote_address() is not None:
            mock_udp_socket.send.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))
        else:
            mock_udp_socket.sendto.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ConnectionAbortedError):
            client.send_packet_to(mocker.sentinel.packet, global_remote_address)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_select.assert_not_called()
        if client.get_remote_address() is not None:
            mock_udp_socket.sendto.assert_not_called()
            mock_udp_socket.send.assert_called_once()
        else:
            mock_udp_socket.sendto.assert_called_once()
            mock_udp_socket.send.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet_from____blocking_or_not____receive_bytes_from_socket(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = [(b"packet", sender_address)]

        # Act
        packet, sender = client.recv_packet_from(timeout=recv_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()

        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()

        mock_udp_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet
        assert (sender.host, sender.port) == sender_address

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet_from____blocking_or_not____protocol_parse_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import DatagramProtocolParseError

        mock_udp_socket.recvfrom.side_effect = [(b"packet", sender_address)]
        expected_error = DatagramProtocolParseError("deserialization", "Sorry")
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = client.recv_packet_from(timeout=recv_timeout)
        exception = exc_info.value

        # Assert
        mock_udp_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet_from____blocking_or_not____closed_client_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
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
            _ = client.recv_packet_from(timeout=recv_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.recvfrom.assert_not_called()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____recv_packet_from____blocking_or_not____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: UDPNetworkEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet_from(timeout=recv_timeout)

        # Assert
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.setblocking.assert_not_called()
        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()
        mock_udp_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.parametrize(
        "recv_timeout",
        [
            pytest.param(0, id="null timeout"),
            pytest.param(123456789, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet_from____no_block____timeout(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        recv_timeout: int,
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_selector_register: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = BlockingIOError
        self.selector_timeout_after_n_calls(mock_selector_select, mocker, nb_calls=1)

        # Act & Assert
        with pytest.raises(TimeoutError, match=r"^recv_packet\(\) timed out$"):
            _ = client.recv_packet_from(timeout=recv_timeout)

        if recv_timeout == 0:
            assert len(mock_udp_socket.recvfrom.mock_calls) == 1
            mock_selector_register.assert_not_called()
            mock_selector_select.assert_not_called()
        else:
            assert len(mock_udp_socket.recvfrom.mock_calls) == 2
            mock_selector_register.assert_called_with(mock_udp_socket, EVENT_READ)
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
    def test____iter_received_packets_from____yields_available_packets_with_given_timeout(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: int,
        mock_udp_socket: MagicMock,
        mock_selector_select: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = [
            (b"packet_1", sender_address),
            (b"packet_2", sender_address),
            BlockingIOError,
        ]
        self.selector_timeout_after_n_calls(mock_selector_select, mocker, nb_calls=0)

        # Act
        packets = [(p, (s.host, s.port)) for p, s in client.iter_received_packets_from(timeout=recv_timeout)]

        # Assert
        assert mock_udp_socket.recvfrom.mock_calls == [mocker.call(MAX_DATAGRAM_BUFSIZE) for _ in range(3)]
        assert mock_datagram_protocol.build_packet_from_datagram.mock_calls == [
            mocker.call(b"packet_1"),
            mocker.call(b"packet_2"),
        ]
        assert packets == [
            (mocker.sentinel.packet_1, sender_address),
            (mocker.sentinel.packet_2, sender_address),
        ]

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets_from____yields_available_packets_until_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = [
            (b"packet_1", sender_address),
            (b"packet_2", sender_address),
            OSError,
        ]

        # Act
        packets = [(p, (s.host, s.port)) for p, s in client.iter_received_packets_from(timeout=recv_timeout)]

        # Assert
        assert mock_udp_socket.recvfrom.mock_calls == [mocker.call(MAX_DATAGRAM_BUFSIZE) for _ in range(3)]
        assert mock_datagram_protocol.build_packet_from_datagram.mock_calls == [
            mocker.call(b"packet_1"),
            mocker.call(b"packet_2"),
        ]
        assert packets == [
            (mocker.sentinel.packet_1, sender_address),
            (mocker.sentinel.packet_2, sender_address),
        ]

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets_from____protocol_parse_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        recv_timeout: float | None,
        sender_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import DatagramProtocolParseError

        mock_udp_socket.recvfrom.side_effect = [(b"packet", sender_address)]
        expected_error = DatagramProtocolParseError("deserialization", "Sorry")
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = next(client.iter_received_packets_from(timeout=recv_timeout))
        exception = exc_info.value

        # Assert
        mock_udp_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets_from____release_internal_lock_before_yield(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from threading import Lock

        mock_acquire = mocker.patch.object(Lock, "acquire", return_value=True)
        mock_release = mocker.patch.object(Lock, "release", return_value=None)
        mock_udp_socket.recvfrom.side_effect = [(b"packet_1", sender_address), (b"packet_2", sender_address)]

        # Act & Assert
        iterator = client.iter_received_packets_from(timeout=recv_timeout)
        mock_acquire.assert_not_called()
        mock_release.assert_not_called()
        packet_1 = next(iterator)
        mock_acquire.assert_called_once_with()
        mock_release.assert_called_once_with()
        mock_acquire.reset_mock()
        mock_release.reset_mock()
        packet_2 = next(iterator)
        mock_acquire.assert_called_once_with()
        mock_release.assert_called_once_with()
        assert packet_1[0] is mocker.sentinel.packet_1
        assert packet_2[0] is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets_from____closed_client_during_iteration(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: float | None,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = [(b"packet_1", sender_address)]

        # Act & Assert
        iterator = client.iter_received_packets_from(timeout=recv_timeout)
        packet_1 = next(iterator)
        assert packet_1[0] is mocker.sentinel.packet_1
        client.close()
        assert client.is_closed()
        with pytest.raises(StopIteration):
            _ = next(iterator)


class TestUDPNetworkClient:
    @pytest.fixture
    @staticmethod
    def mock_udp_endpoint(mock_udp_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=UDPNetworkEndpoint)
        mock.get_local_address.return_value = ("local_address", 12345)
        mock.get_remote_address.return_value = ("remote_address", 5000)
        mock.socket = mock_udp_socket
        return mock

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_udp_endpoint_cls(mocker: MockerFixture, mock_udp_endpoint: MagicMock) -> MagicMock:
        return mocker.patch(f"{UDPNetworkEndpoint.__module__}.UDPNetworkEndpoint", return_value=mock_udp_endpoint)

    @pytest.fixture
    @staticmethod
    def client(
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> UDPNetworkClient[Any, Any]:
        return UDPNetworkClient(
            mock_udp_socket,
            mock_datagram_protocol,
        )

    def test____dunder_init____with_remote_address(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint_cls: MagicMock,
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        remote_address = ("remote_address", 5000)

        # Act
        client: UDPNetworkClient[Any, Any] = UDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            local_address=mocker.sentinel.local_address,
            reuse_port=mocker.sentinel.reuse_port,
            retry_interval=mocker.sentinel.retry_interval,
        )

        # Assert
        mock_udp_endpoint_cls.assert_called_once_with(
            protocol=mock_datagram_protocol,
            remote_address=remote_address,
            local_address=mocker.sentinel.local_address,
            reuse_port=mocker.sentinel.reuse_port,
            retry_interval=mocker.sentinel.retry_interval,
        )
        mock_udp_endpoint.get_remote_address.assert_called_once_with()
        assert client.socket is mock_udp_socket

    def test____dunder_init____with_socket(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint_cls: MagicMock,
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: UDPNetworkClient[Any, Any] = UDPNetworkClient(
            mock_udp_socket,
            mock_datagram_protocol,
            retry_interval=mocker.sentinel.retry_interval,
        )

        # Assert
        mock_udp_endpoint_cls.assert_called_once_with(
            protocol=mock_datagram_protocol,
            socket=mock_udp_socket,
            retry_interval=mocker.sentinel.retry_interval,
        )
        mock_udp_endpoint.get_remote_address.assert_called_once_with()
        assert client.socket is mock_udp_socket

    def test____dunder_init____error_no_remote_address(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.get_remote_address.return_value = None

        # Act & Assert
        with pytest.raises(OSError, match=r"^No remote address configured$"):
            _ = UDPNetworkClient(
                mock_udp_socket,
                mock_datagram_protocol,
            )
        mock_udp_endpoint.close.assert_called_once_with()

    def test____is_closed____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.is_closed.return_value = mocker.sentinel.status

        # Act
        status = client.is_closed()

        # Assert
        mock_udp_endpoint.is_closed.assert_called_once_with()
        assert status is mocker.sentinel.status

    def test____close____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_endpoint.close.return_value = None

        # Act
        client.close()

        # Assert
        mock_udp_endpoint.close.assert_called_once_with()

    def test____get_local_address____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        address = client.get_local_address()

        # Assert
        mock_udp_endpoint.get_local_address.assert_called_once_with()
        assert address == ("local_address", 12345)

    def test____get_remote_address____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        mock_udp_endpoint.get_remote_address.assert_called_once()

        # Act
        address = client.get_remote_address()

        # Assert
        mock_udp_endpoint.get_remote_address.assert_called_once()
        assert address == ("remote_address", 5000)

    def test____send_packet____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.send_packet_to.return_value = None

        # Act
        client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_udp_endpoint.send_packet_to.assert_called_once_with(mocker.sentinel.packet, None)

    def test____recv_packet____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.recv_packet_from.return_value = (mocker.sentinel.packet, ("remote_address", 5000))

        # Act
        packet = client.recv_packet(timeout=mocker.sentinel.timeout)

        # Assert
        mock_udp_endpoint.recv_packet_from.assert_called_once_with(timeout=mocker.sentinel.timeout)
        assert packet is mocker.sentinel.packet

    def test____recv_packet____timeout_error(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.recv_packet_from.side_effect = TimeoutError("recv_packet() timed out")

        # Act
        with pytest.raises(TimeoutError) as exc_info:
            _ = client.recv_packet(timeout=mocker.sentinel.timeout)
        exception = exc_info.value

        # Assert
        mock_udp_endpoint.recv_packet_from.assert_called_once_with(timeout=mocker.sentinel.timeout)
        assert exception is mock_udp_endpoint.recv_packet_from.side_effect

    def test____iter_received_packets____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.iter_received_packets_from.side_effect = lambda timeout: iter(
            [
                (mocker.sentinel.packet_1, ("remote_address", 5000)),
                (mocker.sentinel.packet_2, ("remote_address", 5000)),
                (mocker.sentinel.packet_3, ("remote_address", 5000)),
            ]
        )

        # Act
        packets = list(client.iter_received_packets(timeout=mocker.sentinel.timeout))

        # Assert
        mock_udp_endpoint.iter_received_packets_from.assert_called_once_with(timeout=mocker.sentinel.timeout)
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2, mocker.sentinel.packet_3]

    def test____fileno____default(
        self,
        client: UDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.fileno.return_value = mocker.sentinel.fd

        # Act
        fd = client.fileno()

        # Assert
        mock_udp_endpoint.fileno.assert_called_once_with()
        assert fd is mocker.sentinel.fd
