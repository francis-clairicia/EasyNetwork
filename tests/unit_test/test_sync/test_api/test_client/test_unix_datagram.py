from __future__ import annotations

import errno
import os
import pathlib
from collections.abc import Iterator
from socket import SO_ERROR, SOCK_DGRAM, SOL_SOCKET
from typing import TYPE_CHECKING, Any

from easynetwork.clients.unix_datagram import UnixDatagramClient, _create_unix_datagram_socket
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel.api_sync.endpoints.datagram import DatagramEndpoint
from easynetwork.lowlevel.api_sync.transports.socket import SocketDatagramTransport
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS, MAX_DATAGRAM_BUFSIZE
from easynetwork.lowlevel.socket import SocketProxy, UnixSocketAddress, _get_socket_extra

import pytest

from .....fixtures.socket import AF_UNIX_or_skip
from .....tools import PlatformMarkers
from ...._utils import unsupported_families
from ....base import UNIX_FAMILIES
from ...mock_tools import make_transport_mock
from .base import BaseTestClient

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@PlatformMarkers.skipif_platform_win32
class TestUnixDatagramClient(BaseTestClient):
    @pytest.fixture(scope="class", params=UNIX_FAMILIES)
    @staticmethod
    def socket_family(request: pytest.FixtureRequest) -> int:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture(scope="class", params=["/path/to/local_sock", b"\0abstract_local"])
    @staticmethod
    def global_local_address(request: pytest.FixtureRequest) -> str | bytes:
        return request.param

    @pytest.fixture(scope="class", params=["/path/to/sock", b"\0abstract"])
    @staticmethod
    def global_remote_address(request: pytest.FixtureRequest) -> str | bytes:
        return request.param

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        mock_unix_datagram_socket: MagicMock,
        socket_family: int,
        global_local_address: str | bytes,
    ) -> str | bytes:
        if socket_family == AF_UNIX_or_skip():
            cls.set_local_address_to_socket_mock(
                mock_unix_datagram_socket,
                socket_family,
                global_local_address,
            )
        return global_local_address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_unix_datagram_socket: MagicMock,
        socket_family: int,
        global_remote_address: str | bytes,
    ) -> str | bytes:
        if socket_family == AF_UNIX_or_skip():
            cls.set_remote_address_to_socket_mock(
                mock_unix_datagram_socket,
                socket_family,
                global_remote_address,
            )
        return global_remote_address

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_platform_supports_automatic_socket_bind(mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "easynetwork.lowlevel._unix_utils.platform_supports_automatic_socket_bind",
            autospec=True,
            return_value=False,
        )

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
            f"{UnixDatagramClient.__module__}.DatagramEndpoint",
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
    def mock_create_unix_datagram_socket(mocker: MockerFixture, mock_unix_datagram_socket: MagicMock) -> MagicMock:
        return mocker.patch(
            f"{UnixDatagramClient.__module__}._create_unix_datagram_socket",
            autospec=True,
            return_value=mock_unix_datagram_socket,
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_unix_datagram_socket: MagicMock,
        socket_family: int,
    ) -> None:
        mock_unix_datagram_socket.family = socket_family
        mock_unix_datagram_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()

    @pytest.fixture
    @staticmethod
    def client(
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> Iterator[UnixDatagramClient[Any, Any]]:
        client: UnixDatagramClient[Any, Any] = UnixDatagramClient(mock_unix_datagram_socket, protocol=mock_datagram_protocol)
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
        local_address: str | bytes,
        remote_address: str | bytes,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint_cls: MagicMock,
        mock_socket_datagram_transport_cls: MagicMock,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client = UnixDatagramClient[Any, Any](
            remote_address,
            mock_datagram_protocol,
            local_path=local_address,
            retry_interval=retry_interval,
        )
        request.addfinalizer(client.close)

        # Assert
        mock_create_unix_datagram_socket.assert_called_once_with(
            remote_address,
            local_path=local_address,
        )
        mock_socket_datagram_transport_cls.assert_called_once_with(
            mock_unix_datagram_socket,
            retry_interval=retry_interval,
            max_datagram_size=MAX_DATAGRAM_BUFSIZE,
        )
        mock_datagram_endpoint_cls.assert_called_once_with(mock_datagram_transport, mock_datagram_protocol)
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.setblocking(False),
        ]

    @pytest.mark.parametrize("global_remote_address", ["/path/to/sock"], indirect=True)
    @pytest.mark.parametrize("global_local_address", ["/path/to/local_sock"], indirect=True)
    def test____dunder_init____with_remote_address____with_path_like_object(
        self,
        request: pytest.FixtureRequest,
        local_address: str,
        remote_address: str,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client = UnixDatagramClient[Any, Any](
            pathlib.Path(remote_address),
            mock_datagram_protocol,
            local_path=pathlib.Path(local_address),
        )
        request.addfinalizer(client.close)

        # Assert
        mock_create_unix_datagram_socket.assert_called_once_with(
            remote_address,
            local_path=local_address,
        )

    def test____dunder_init____with_remote_address____with_UnixSocketAddress_object(
        self,
        request: pytest.FixtureRequest,
        local_address: str | bytes,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client = UnixDatagramClient[Any, Any](
            UnixSocketAddress.from_raw(remote_address),
            mock_datagram_protocol,
            local_path=UnixSocketAddress.from_raw(local_address),
        )
        request.addfinalizer(client.close)

        # Assert
        mock_create_unix_datagram_socket.assert_called_once_with(
            remote_address,
            local_path=local_address,
        )

    def test____dunder_init____with_remote_address____no_local_address____autobind_supported(
        self,
        request: pytest.FixtureRequest,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = True

        # Act
        client: UnixDatagramClient[Any, Any] = UnixDatagramClient(remote_address, mock_datagram_protocol)
        request.addfinalizer(client.close)

        # Assert
        mock_create_unix_datagram_socket.assert_called_once_with(
            remote_address,
            local_path="",
        )

    def test____dunder_init____with_remote_address____no_local_address____autobind_not_supported(
        self,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = False

        # Act & Assert
        with pytest.raises(
            ValueError,
            match=r"^local_path parameter is required on this platform and cannot be an empty string\.",
        ) as exc_info:
            _ = UnixDatagramClient(remote_address, mock_datagram_protocol)
        assert exc_info.value.__notes__ == ["Automatic socket bind is not supported."]
        mock_create_unix_datagram_socket.assert_not_called()

    def test____dunder_init____with_remote_address____explicit_autobind_local_address____autobind_supported(
        self,
        request: pytest.FixtureRequest,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = True

        # Act
        client: UnixDatagramClient[Any, Any] = UnixDatagramClient(
            remote_address,
            mock_datagram_protocol,
            local_path="",
        )
        request.addfinalizer(client.close)

        # Assert
        mock_create_unix_datagram_socket.assert_called_once_with(
            remote_address,
            local_path="",
        )

    def test____dunder_init____with_remote_address____explicit_autobind_local_address____autobind_not_supported(
        self,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = False

        # Act & Assert
        with pytest.raises(
            ValueError,
            match=r"^local_path parameter is required on this platform and cannot be an empty string\.",
        ) as exc_info:
            _ = UnixDatagramClient(
                remote_address,
                mock_datagram_protocol,
                local_path="",
            )
        assert exc_info.value.__notes__ == ["Automatic socket bind is not supported."]
        mock_create_unix_datagram_socket.assert_not_called()

    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____use_given_socket____default(
        self,
        request: pytest.FixtureRequest,
        retry_interval: float,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_create_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint_cls: MagicMock,
        mock_socket_datagram_transport_cls: MagicMock,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client = UnixDatagramClient[Any, Any](mock_unix_datagram_socket, mock_datagram_protocol, retry_interval=retry_interval)
        request.addfinalizer(client.close)

        # Assert
        mock_create_unix_datagram_socket.assert_not_called()
        mock_socket_datagram_transport_cls.assert_called_once_with(
            mock_unix_datagram_socket,
            retry_interval=retry_interval,
            max_datagram_size=MAX_DATAGRAM_BUFSIZE,
        )
        mock_datagram_endpoint_cls.assert_called_once_with(mock_datagram_transport, mock_datagram_protocol)
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.setblocking(False),
        ]
        assert isinstance(client.socket, SocketProxy)

    def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        self.configure_socket_mock_to_raise_ENOTCONN(mock_unix_datagram_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = UnixDatagramClient(mock_unix_datagram_socket, mock_datagram_protocol)

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.close(),
        ]

    @pytest.mark.parametrize("global_local_address", [""], indirect=True)
    def test____dunder_init____use_given_socket____error_no_local_address(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^UnixDatagramClient requires the socket to be named.$"):
            _ = UnixDatagramClient(mock_unix_datagram_socket, mock_datagram_protocol)

        # Assert
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.close(),
        ]

    @pytest.mark.parametrize("socket_family", list(unsupported_families(UNIX_FAMILIES)), indirect=True)
    def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = UnixDatagramClient(
                mock_unix_datagram_socket,
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
        with pytest.raises(TypeError, match=r"^expected str, bytes or os.PathLike object, not .+$"):
            _ = UnixDatagramClient(
                invalid_object,
                protocol=mock_datagram_protocol,
            )

    def test____dunder_init____invalid_arguments____unknown_overload(
        self,
        local_address: str | bytes,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = UnixDatagramClient(
                mock_unix_datagram_socket,
                protocol=mock_datagram_protocol,
                local_path=local_address,
            )

        assert mock_unix_datagram_socket.mock_calls == []

    def test____dunder_init____protocol____invalid_value(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = UnixDatagramClient(
                mock_unix_datagram_socket,
                protocol=mock_stream_protocol,
            )
        assert mock_datagram_transport.mock_calls == [mocker.call.close()]

    def test____dunder_del____ResourceWarning(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        client: UnixDatagramClient[Any, Any] = UnixDatagramClient(mock_unix_datagram_socket, mock_datagram_protocol)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed client .+$"):
            del client

        mock_datagram_endpoint.close.assert_called_once_with()

    def test____close____default(
        self,
        client: UnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()

        # Act
        client.close()

        # Assert
        assert client.is_closed()
        mock_datagram_endpoint.close.assert_called_once_with()

    def test____get_local_name____return_saved_address(
        self,
        client: UnixDatagramClient[Any, Any],
        local_address: str | bytes,
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getsockname.reset_mock()

        # Act
        address = client.get_local_name()

        # Assert
        assert isinstance(address, UnixSocketAddress)
        mock_unix_datagram_socket.getsockname.assert_called_once()
        assert address.as_raw() == local_address

    def test____get_peer_name____return_saved_address(
        self,
        client: UnixDatagramClient[Any, Any],
        remote_address: str | bytes,
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getpeername.reset_mock()

        # Act
        address = client.get_peer_name()

        # Assert
        assert isinstance(address, UnixSocketAddress)
        mock_unix_datagram_socket.getpeername.assert_called_once()
        assert address.as_raw() == remote_address

    def test____get_local_or_peer_name____closed_client(
        self,
        client: UnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        mock_unix_datagram_socket.reset_mock()

        # Act & Assert
        with pytest.raises(ClientClosedError):
            client.get_local_name()
        with pytest.raises(ClientClosedError):
            client.get_peer_name()

        mock_unix_datagram_socket.getsockname.assert_not_called()
        mock_unix_datagram_socket.getpeername.assert_not_called()

    def test____fileno____default(
        self,
        client: UnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        fd = client.fileno()

        # Assert
        mock_unix_datagram_socket.fileno.assert_called_once_with()
        assert fd == mock_unix_datagram_socket.fileno.return_value

    def test____socket_property____cached_attribute(
        self,
        client: UnixDatagramClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert client.socket is client.socket

    def test____send_packet____send_bytes_to_socket(
        self,
        client: UnixDatagramClient[Any, Any],
        send_timeout: float | None,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_datagram_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_unix_datagram_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: UnixDatagramClient[Any, Any],
        send_timeout: float | None,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getsockopt.return_value = errno.ECONNREFUSED

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.errno == errno.ECONNREFUSED
        mock_datagram_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_unix_datagram_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____closed_client_error(
        self,
        client: UnixDatagramClient[Any, Any],
        send_timeout: float | None,
        mock_unix_datagram_socket: MagicMock,
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
        mock_unix_datagram_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client: UnixDatagramClient[Any, Any],
        send_timeout: float | None,
        mock_unix_datagram_socket: MagicMock,
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
        mock_unix_datagram_socket.getsockopt.assert_not_called()

    def test____recv_packet____receive_bytes_from_socket(
        self,
        client: UnixDatagramClient[Any, Any],
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
        client: UnixDatagramClient[Any, Any],
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
        client: UnixDatagramClient[Any, Any],
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
        client: UnixDatagramClient[Any, Any],
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
        client: UnixDatagramClient[Any, Any],
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
        client: UnixDatagramClient[Any, Any],
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


@PlatformMarkers.skipif_platform_win32
class TestUnixDatagramSocketFactory:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_cls(
        mock_unix_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        return mocker.patch("socket.socket", side_effect=[mock_unix_datagram_socket])

    @pytest.mark.parametrize(
        "local_address",
        [
            None,
            "/path/to/local.sock",
            b"/path/to/local.sock",
            "\0local_sock",
            b"\x00local_sock",
            "",  # <- Arbitrary abstract Unix address given by kernel
            b"",  # <- Arbitrary abstract Unix address given by kernel
        ],
        ids=lambda addr: f"local_address=={addr!r}",
    )
    @pytest.mark.parametrize(
        "remote_address",
        [
            "/path/to/unix.sock",
            b"/path/to/unix.sock",
            "\0unix_sock",
            b"\x00unix_sock",
        ],
        ids=lambda addr: f"remote_address=={addr!r}",
    )
    def test____create_unix_datagram_socket____default(
        self,
        local_address: str | bytes | None,
        remote_address: str | bytes,
        mock_socket_cls: MagicMock,
        mock_unix_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        AF_UNIX = AF_UNIX_or_skip()
        mock_unix_datagram_socket.bind.return_value = None
        mock_unix_datagram_socket.connect.return_value = None

        # Act
        sock = _create_unix_datagram_socket(
            remote_address,
            local_path=local_address,
        )

        # Assert
        assert sock is mock_unix_datagram_socket
        mock_socket_cls.assert_called_once_with(AF_UNIX, SOCK_DGRAM, 0)
        if local_address is None:
            assert mock_unix_datagram_socket.mock_calls == [
                mocker.call.connect(remote_address),
            ]
        else:
            assert mock_unix_datagram_socket.mock_calls == [
                mocker.call.bind(local_address),
                mocker.call.connect(remote_address),
            ]

    @pytest.mark.parametrize(
        "local_address",
        [
            "/path/to/local.sock",
            b"/path/to/local.sock",
            "\0local_sock",
            b"\x00local_sock",
        ],
        ids=lambda addr: f"local_address=={addr!r}",
    )
    @pytest.mark.parametrize(
        "remote_address",
        [
            "/path/to/unix.sock",
            b"/path/to/unix.sock",
            "\0unix_sock",
            b"\x00unix_sock",
        ],
        ids=lambda addr: f"remote_address=={addr!r}",
    )
    @pytest.mark.parametrize(
        "bind_error",
        [
            OSError(errno.EPERM, os.strerror(errno.EPERM)),
            OSError("AF_UNIX path too long."),
        ],
        ids=lambda exc: f"bind_error=={exc!r}",
    )
    def test____create_unix_datagram_socket____bind_error(
        self,
        local_address: str | bytes,
        remote_address: str | bytes,
        bind_error: OSError,
        mock_socket_cls: MagicMock,
        mock_unix_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        AF_UNIX = AF_UNIX_or_skip()
        mock_unix_datagram_socket.bind.side_effect = bind_error
        mock_unix_datagram_socket.connect.return_value = None

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = _create_unix_datagram_socket(
                remote_address,
                local_path=local_address,
            )

        # Assert
        mock_socket_cls.assert_called_once_with(AF_UNIX, SOCK_DGRAM, 0)
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.bind(local_address),
            mocker.call.close(),
        ]
        if bind_error.errno:
            assert exc_info.value.errno == bind_error.errno
        else:
            assert exc_info.value.errno == errno.EINVAL

    @pytest.mark.parametrize(
        "remote_address",
        [
            "/path/to/unix.sock",
            b"/path/to/unix.sock",
            "\0unix_sock",
            b"\x00unix_sock",
        ],
        ids=lambda addr: f"remote_address=={addr!r}",
    )
    @pytest.mark.parametrize(
        "connect_error",
        [
            OSError(errno.ECONNREFUSED, os.strerror(errno.ECONNREFUSED)),
            OSError(errno.EPERM, os.strerror(errno.EPERM)),
        ],
        ids=lambda exc: f"connect_error=={exc!r}",
    )
    def test____create_unix_datagram_socket____connect_error(
        self,
        remote_address: str | bytes,
        connect_error: OSError,
        mock_socket_cls: MagicMock,
        mock_unix_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        AF_UNIX = AF_UNIX_or_skip()
        mock_unix_datagram_socket.connect.side_effect = connect_error

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = _create_unix_datagram_socket(remote_address)

        # Assert
        mock_socket_cls.assert_called_once_with(AF_UNIX, SOCK_DGRAM, 0)
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.connect(remote_address),
            mocker.call.close(),
        ]
        assert exc_info.value.errno == connect_error.errno
