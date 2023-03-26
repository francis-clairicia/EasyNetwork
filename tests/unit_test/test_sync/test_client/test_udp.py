# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import AF_INET6, SOCK_DGRAM
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import ClientClosedError
from easynetwork.sync_api.client.udp import UDPNetworkClient, UDPNetworkEndpoint
from easynetwork.tools.socket import MAX_DATAGRAM_BUFSIZE, IPv4SocketAddress, IPv6SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from .base import BaseTestClient


@pytest.fixture(scope="module", autouse=True)
def setup_dummy_lock(module_mocker: MockerFixture, dummy_lock_cls: Any) -> None:
    module_mocker.patch(f"{UDPNetworkEndpoint.__module__}._Lock", new=dummy_lock_cls)


def _get_all_socket_families() -> list[str]:
    import socket

    return [v for v in dir(socket) if v.startswith("AF_")]


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
    def mock_socket_cls(mocker: MockerFixture, mock_udp_socket: MagicMock, original_socket_cls: type[Any]) -> MagicMock:
        mock_socket_cls = mocker.patch("socket.socket", return_value=mock_udp_socket, autospec=True)

        def patch_isinstance(obj: Any, type: Any) -> bool:
            if type is mock_socket_cls:
                type = original_socket_cls
            return isinstance(obj, type)

        mocker.patch(f"{UDPNetworkEndpoint.__module__}.isinstance", patch_isinstance)
        return mock_socket_cls

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_proxy_cls(mocker: MockerFixture, mock_udp_socket: MagicMock) -> MagicMock:
        return mocker.patch(f"{UDPNetworkClient.__module__}.SocketProxy", return_value=mock_udp_socket)

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_local_address_to_socket_mock(mock_udp_socket, socket_family, global_local_address)
        return global_local_address

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
        mocker: MockerFixture,
    ) -> None:
        mock_udp_socket.family = socket_family
        mock_udp_socket.gettimeout.return_value = mocker.sentinel.default_timeout
        mock_udp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet_to()

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

    @pytest.fixture(params=["REMOTE_ADDRESS", "SOCKET_WITH_EXPLICIT_GIVE"])
    @staticmethod
    def client_with_socket_ownership(
        request: Any,
        remote_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> UDPNetworkEndpoint[Any, Any]:
        match request.param:
            case "REMOTE_ADDRESS":
                return UDPNetworkEndpoint(protocol=mock_datagram_protocol, remote_address=remote_address)
            case "SOCKET_WITH_EXPLICIT_GIVE":
                return UDPNetworkEndpoint(socket=mock_udp_socket, protocol=mock_datagram_protocol, give=True)
            case invalid:
                pytest.fail(f"Invalid fixture param: Got {invalid!r}")

    @pytest.fixture
    @staticmethod
    def client_without_socket_ownership(
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> UDPNetworkEndpoint[Any, Any]:
        return UDPNetworkEndpoint(mock_datagram_protocol, socket=mock_udp_socket, give=False)

    @pytest.fixture
    @staticmethod
    def client(client_without_socket_ownership: UDPNetworkEndpoint[Any, Any]) -> UDPNetworkEndpoint[Any, Any]:
        return client_without_socket_ownership

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
            pytest.param(None, id="blocking"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: Any) -> Any:
        return request.param

    def test____dunder_init____create_datagram_endpoint____default(
        self,
        socket_family: int,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_socket_cls: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_socket_proxy_cls.return_value = mocker.sentinel.proxy

        # Act
        endpoint: UDPNetworkEndpoint[Any, Any] = UDPNetworkEndpoint(protocol=mock_datagram_protocol, family=socket_family)

        # Assert
        mock_socket_cls.assert_called_once_with(socket_family, SOCK_DGRAM)
        mock_udp_socket.bind.assert_called_once_with(("", 0))
        mock_udp_socket.connect.assert_not_called()
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.getpeername.assert_not_called()
        mock_socket_proxy_cls.assert_called_once_with(mock_udp_socket, lock=mocker.ANY)
        assert endpoint.socket is mocker.sentinel.proxy

    @pytest.mark.parametrize("source_address", [None, ("local_address", 12345)], ids=lambda p: f"source_address=={p}")
    def test____dunder_init____create_datagram_endpoint____with_parameters(
        self,
        socket_family: int,
        source_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_socket_cls: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = UDPNetworkEndpoint(
            protocol=mock_datagram_protocol,
            family=socket_family,
            source_address=source_address,
            remote_address=remote_address,
        )

        # Assert
        mock_socket_cls.assert_called_once_with(socket_family, SOCK_DGRAM)
        if source_address is None:
            mock_udp_socket.bind.assert_called_once_with(("", 0))
        else:
            mock_udp_socket.bind.assert_called_once_with(source_address)
        if remote_address is None:
            mock_udp_socket.connect.assert_not_called()
            mock_udp_socket.getpeername.assert_not_called()
        else:
            mock_udp_socket.connect.assert_called_once_with(remote_address)
            mock_udp_socket.getpeername.assert_called_once_with()
        mock_udp_socket.settimeout.assert_not_called()
        mock_socket_proxy_cls.assert_called_once_with(mock_udp_socket, lock=mocker.ANY)

    @pytest.mark.parametrize(
        "socket_family", list(set(_get_all_socket_families()).difference(["AF_INET", "AF_INET6"])), indirect=True
    )
    def test____dunder_init____create_datagram_endpoint____invalid_socket_family(
        self,
        socket_family: int,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only AF_INET and AF_INET6 families are supported$"):
            _ = UDPNetworkEndpoint(protocol=mock_datagram_protocol, family=socket_family)

    @pytest.mark.parametrize("error_on", ["bind", "connect"])
    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    def test____dunder_init____create_datagram_endpoint____close_socket_if_an_error_occurs(
        self,
        error_on: str,
        local_address: tuple[str, int],
        remote_address: tuple[str, int],
        socket_family: int,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_method: MagicMock = getattr(mock_udp_socket, error_on)
        mock_method.side_effect = OSError()

        # Act & Assert
        with pytest.raises(type(mock_method.side_effect)) as exc_info:
            _ = UDPNetworkEndpoint(
                protocol=mock_datagram_protocol,
                family=socket_family,
                source_address=local_address,
                remote_address=remote_address,
            )
        assert exc_info.value is mock_method.side_effect
        mock_udp_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("give_ownership", [False, True], ids=lambda p: f"give=={p}")
    @pytest.mark.parametrize("bound", [False, True], ids=lambda p: f"bound=={p}")
    def test____dunder_init____use_given_socket____default(
        self,
        give_ownership: bool,
        bound: bool,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_socket_cls: MagicMock,
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
            give=give_ownership,
        )

        # Assert
        mock_socket_cls.assert_not_called()
        if bound:
            mock_udp_socket.bind.assert_not_called()
        else:
            mock_udp_socket.bind.assert_called_once_with(("", 0))
        mock_udp_socket.connect.assert_not_called()
        mock_udp_socket.settimeout.assert_not_called()
        mock_udp_socket.getpeername.assert_called_once_with()
        mock_socket_proxy_cls.assert_called_once_with(mock_udp_socket, lock=mocker.ANY)
        assert endpoint.socket is mocker.sentinel.proxy

    @pytest.mark.parametrize(
        "socket_family", list(set(_get_all_socket_families()).difference(["AF_INET", "AF_INET6"])), indirect=True
    )
    def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only AF_INET and AF_INET6 families are supported$"):
            _ = UDPNetworkEndpoint(
                protocol=mock_datagram_protocol,
                socket=mock_udp_socket,
                give=False,
            )

    @pytest.mark.parametrize("give_ownership", [False, True], ids=lambda p: f"give=={p}")
    def test____dunder_init____use_given_socket____invalid_socket_type_error(
        self,
        give_ownership: bool,
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
                give=give_ownership,
            )

        # Assert
        mock_socket_proxy_cls.assert_not_called()
        mock_tcp_socket.getsockname.assert_not_called()
        mock_tcp_socket.getpeername.assert_not_called()
        ## If ownership was given, the socket must be closed
        if give_ownership:
            mock_tcp_socket.close.assert_called_once_with()
        else:
            mock_tcp_socket.close.assert_not_called()

    def test____dunder_init____use_given_socket____ownership_parameter_missing(
        self,
        mock_udp_socket: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(TypeError, match=r"^Missing keyword argument 'give'$"):
            _ = UDPNetworkEndpoint(  # type: ignore[call-overload]
                protocol=mock_datagram_protocol,
                socket=mock_udp_socket,
            )

        # Assert
        mock_socket_proxy_cls.assert_not_called()
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

    def test____close____with_ownership(
        self,
        client_with_socket_ownership: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client_with_socket_ownership.is_closed()

        # Act
        client_with_socket_ownership.close()

        # Assert
        assert client_with_socket_ownership.is_closed()
        mock_udp_socket.close.assert_called_once_with()

    def test____close____without_ownership(
        self,
        client_without_socket_ownership: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client_without_socket_ownership.is_closed()

        # Act
        client_without_socket_ownership.close()

        # Assert
        assert client_without_socket_ownership.is_closed()
        mock_udp_socket.close.assert_not_called()

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
        client: UDPNetworkEndpoint[Any, Any],
        client_closed: bool,
        remote_address: tuple[str, int] | None,
        socket_family: int,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        mock_udp_socket.getpeername.assert_called_once()
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
            mock_udp_socket.getpeername.assert_called_once()
            assert address.host == remote_address[0]
            assert address.port == remote_address[1]

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
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        target_address: tuple[str, int] = ("remote_address", 5000)

        # Act
        client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        assert mock_udp_socket.settimeout.mock_calls == [mocker.call(None), mocker.call(mocker.sentinel.default_timeout)]
        mock_udp_socket.sendto.assert_called_once_with(b"packet", target_address)
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____without_remote____None_address_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
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
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        # Act
        client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        assert mock_udp_socket.settimeout.mock_calls == [mocker.call(None), mocker.call(mocker.sentinel.default_timeout)]
        mock_udp_socket.sendto.assert_not_called()
        mock_udp_socket.send.assert_called_once_with(b"packet")
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____send_bytes_to_socket____with_remote____invalid_target_address(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
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
        mock_udp_socket.sendto.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____send_packet_to____raise_error_saved_in_SO_ERROR_option(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        global_remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
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
        assert mock_udp_socket.settimeout.mock_calls == [mocker.call(None), mocker.call(mocker.sentinel.default_timeout)]
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
        mock_udp_socket.sendto.assert_not_called()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet_from____blocking_or_not____receive_bytes_from_socket(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: int | None,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = [(b"packet", sender_address)]

        # Act
        packet, sender = client.recv_packet_from(timeout=recv_timeout)

        # Assert
        assert mock_udp_socket.settimeout.mock_calls == [mocker.call(recv_timeout), mocker.call(mocker.sentinel.default_timeout)]
        mock_udp_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet
        assert (sender.host, sender.port) == sender_address

    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet_from____blocking_or_not____protocol_parse_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: int | None,
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
        recv_timeout: int | None,
        mock_udp_socket: MagicMock,
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
        mock_udp_socket.recvfrom.assert_not_called()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.parametrize(
        ["recv_timeout", "recv_exception"],
        [
            pytest.param(0, BlockingIOError, id="null timeout"),
            pytest.param(123456789, TimeoutError, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____recv_packet_from____no_block____timeout(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        recv_timeout: int,
        recv_exception: type[BaseException],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = recv_exception

        # Act & Assert
        with pytest.raises(TimeoutError, match=r"^recv_packet\(\) timed out$"):
            _ = client.recv_packet_from(timeout=recv_timeout)

        mock_udp_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.parametrize(
        ["recv_timeout", "recv_exception"],
        [
            pytest.param(0, BlockingIOError, id="null timeout"),
            pytest.param(123456789, TimeoutError, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_protocol_mock")
    def test____iter_received_packets_from____yields_available_packets_with_given_timeout(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: int,
        recv_exception: type[BaseException],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.recvfrom.side_effect = [
            (b"packet_1", sender_address),
            (b"packet_2", sender_address),
            recv_exception,
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
    def test____iter_received_packets_from____yields_available_packets_until_error(
        self,
        client: UDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        recv_timeout: int | None,
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
        recv_timeout: int | None,
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
        recv_timeout: int | None,
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
        recv_timeout: int | None,
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
            give=False,
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
            family=mocker.sentinel.family,
            source_address=mocker.sentinel.source_address,
        )

        # Assert
        mock_udp_endpoint_cls.assert_called_once_with(
            protocol=mock_datagram_protocol,
            remote_address=remote_address,
            family=mocker.sentinel.family,
            source_address=mocker.sentinel.source_address,
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
            give=mocker.sentinel.give_ownership,
        )

        # Assert
        mock_udp_endpoint_cls.assert_called_once_with(
            protocol=mock_datagram_protocol,
            socket=mock_udp_socket,
            give=mocker.sentinel.give_ownership,
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
                give=mocker.sentinel.give_ownership,
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
