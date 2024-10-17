from __future__ import annotations

import copy
import errno
import os
import pathlib
from collections.abc import Iterator
from socket import SO_ERROR, SOCK_STREAM, SOL_SOCKET
from typing import TYPE_CHECKING, Any

from easynetwork.clients.unix_stream import UnixStreamClient, _create_unix_stream_connection
from easynetwork.exceptions import ClientClosedError, IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel.api_sync.endpoints.stream import StreamEndpoint
from easynetwork.lowlevel.api_sync.transports.socket import SocketStreamTransport
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS, DEFAULT_STREAM_BUFSIZE
from easynetwork.lowlevel.socket import SocketProxy, UnixCredentials, UnixSocketAddress, _get_socket_extra

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
class TestUnixStreamClient(BaseTestClient):
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
        mock_unix_stream_socket: MagicMock,
        socket_family: int,
        global_local_address: str | bytes,
    ) -> str | bytes:
        if socket_family == AF_UNIX_or_skip():
            cls.set_local_address_to_socket_mock(
                mock_unix_stream_socket,
                socket_family,
                global_local_address,
            )
        return global_local_address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_unix_stream_socket: MagicMock,
        socket_family: int,
        global_remote_address: str | bytes,
    ) -> str | bytes:
        if socket_family == AF_UNIX_or_skip():
            cls.set_remote_address_to_socket_mock(
                mock_unix_stream_socket,
                socket_family,
                global_remote_address,
            )
        return global_remote_address

    @pytest.fixture
    @staticmethod
    def mock_stream_endpoint(mocker: MockerFixture) -> MagicMock:
        mock_stream_endpoint = make_transport_mock(mocker=mocker, spec=StreamEndpoint)
        mock_stream_endpoint.recv_packet.return_value = mocker.sentinel.packet
        mock_stream_endpoint.send_packet.return_value = None
        mock_stream_endpoint.send_eof.return_value = None
        return mock_stream_endpoint

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_endpoint_cls(mocker: MockerFixture, mock_stream_endpoint: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._stream import _check_any_protocol
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_endpoint_side_effect(transport: MagicMock, protocol: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            _check_any_protocol(protocol)
            mock_stream_endpoint.extra_attributes = transport.extra_attributes
            return mock_stream_endpoint

        return mocker.patch(
            f"{UnixStreamClient.__module__}.StreamEndpoint",
            side_effect=mock_endpoint_side_effect,
        )

    @pytest.fixture
    @staticmethod
    def mock_socket_stream_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=SocketStreamTransport)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_stream_transport_cls(mocker: MockerFixture, mock_socket_stream_transport: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_transport_side_effect(sock: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            sock.setblocking(False)
            mock_socket_stream_transport.extra_attributes = _get_socket_extra(sock, wrap_in_proxy=False)
            return mock_socket_stream_transport

        return mocker.patch(
            f"{SocketStreamTransport.__module__}.SocketStreamTransport",
            side_effect=mock_transport_side_effect,
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_create_connection(mocker: MockerFixture, mock_unix_stream_socket: MagicMock) -> MagicMock:
        return mocker.patch(
            f"{UnixStreamClient.__module__}._create_unix_stream_connection",
            autospec=True,
            side_effect=[mock_unix_stream_socket],
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_unix_stream_socket: MagicMock,
        socket_family: int,
        mock_get_peer_credentials: MagicMock,
        fake_ucred: UnixCredentials,
    ) -> None:
        mock_unix_stream_socket.family = socket_family
        mock_unix_stream_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()

        mock_get_peer_credentials.side_effect = lambda sock: copy.copy(fake_ucred)

    @pytest.fixture
    @staticmethod
    def client(
        mock_unix_stream_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> Iterator[UnixStreamClient[Any, Any]]:
        client: UnixStreamClient[Any, Any] = UnixStreamClient(
            mock_unix_stream_socket,
            mock_stream_protocol,
        )

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
    def recv_timeout(request: pytest.FixtureRequest) -> float:
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
    def send_timeout(request: pytest.FixtureRequest) -> float:
        return request.param

    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____connect_to_remote(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        retry_interval: float,
        local_address: str | bytes,
        remote_address: str | bytes,
        mock_unix_stream_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_socket_stream_transport_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_max_recv_size: int = DEFAULT_STREAM_BUFSIZE if max_recv_size is None else max_recv_size

        # Act
        client = UnixStreamClient[Any, Any](
            remote_address,
            protocol=mock_stream_protocol,
            connect_timeout=mocker.sentinel.timeout,
            local_path=local_address,
            max_recv_size=max_recv_size,
            retry_interval=retry_interval,
        )
        request.addfinalizer(client.close)

        # Assert
        mock_socket_create_connection.assert_called_once_with(
            remote_address,
            connect_timeout=mocker.sentinel.timeout,
            local_path=local_address,
        )
        mock_socket_stream_transport_cls.assert_called_once_with(mock_unix_stream_socket, retry_interval=retry_interval)
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_socket_stream_transport,
            mock_stream_protocol,
            max_recv_size=expected_max_recv_size,
        )
        assert mock_unix_stream_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setblocking(False),
        ]
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("global_remote_address", ["/path/to/sock"], indirect=True)
    @pytest.mark.parametrize("global_local_address", ["/path/to/local_sock"], indirect=True)
    def test____dunder_init____connect_to_remote____with_path_like_object(
        self,
        request: pytest.FixtureRequest,
        local_address: str,
        remote_address: str,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: UnixStreamClient[Any, Any] = UnixStreamClient(
            pathlib.Path(remote_address),
            protocol=mock_stream_protocol,
            local_path=pathlib.Path(local_address),
        )
        request.addfinalizer(client.close)

        # Assert
        mock_socket_create_connection.assert_called_once_with(
            remote_address,
            local_path=local_address,
        )

    def test____dunder_init____connect_to_remote____with_UnixSocketAddress_object(
        self,
        request: pytest.FixtureRequest,
        local_address: str | bytes,
        remote_address: str | bytes,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: UnixStreamClient[Any, Any] = UnixStreamClient(
            UnixSocketAddress.from_raw(remote_address),
            protocol=mock_stream_protocol,
            local_path=UnixSocketAddress.from_raw(local_address),
        )
        request.addfinalizer(client.close)

        # Assert
        mock_socket_create_connection.assert_called_once_with(
            remote_address,
            local_path=local_address,
        )

    def test____dunder_init____connect_to_remote____no_local_address(
        self,
        request: pytest.FixtureRequest,
        remote_address: str | bytes,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: UnixStreamClient[Any, Any] = UnixStreamClient(
            remote_address,
            protocol=mock_stream_protocol,
        )
        request.addfinalizer(client.close)

        # Assert
        mock_socket_create_connection.assert_called_once_with(remote_address, local_path=None)

    def test____dunder_init____connect_to_remote____explicit_autobind_local_address(
        self,
        request: pytest.FixtureRequest,
        remote_address: str | bytes,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: UnixStreamClient[Any, Any] = UnixStreamClient(
            remote_address,
            protocol=mock_stream_protocol,
            local_path="",
        )
        request.addfinalizer(client.close)

        # Assert
        mock_socket_create_connection.assert_called_once_with(remote_address, local_path="")

    @pytest.mark.parametrize("max_recv_size", [None, 123456789], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("retry_interval", [1.0, float("+inf")], ids=lambda p: f"retry_interval=={p}")
    def test____dunder_init____use_given_socket(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        retry_interval: float,
        mock_unix_stream_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_endpoint_cls: MagicMock,
        mock_socket_stream_transport_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_max_recv_size: int = DEFAULT_STREAM_BUFSIZE if max_recv_size is None else max_recv_size

        # Act
        client = UnixStreamClient[Any, Any](
            mock_unix_stream_socket,
            protocol=mock_stream_protocol,
            max_recv_size=max_recv_size,
            retry_interval=retry_interval,
        )
        request.addfinalizer(client.close)

        mock_socket_create_connection.assert_not_called()
        mock_socket_stream_transport_cls.assert_called_once_with(mock_unix_stream_socket, retry_interval=retry_interval)
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_socket_stream_transport,
            mock_stream_protocol,
            max_recv_size=expected_max_recv_size,
        )
        assert mock_unix_stream_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.setblocking(False),
        ]
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("socket_family", list(unsupported_families(UNIX_FAMILIES)), indirect=True)
    def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_unix_stream_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = UnixStreamClient(
                mock_unix_stream_socket,
                protocol=mock_stream_protocol,
            )

        assert mock_unix_stream_socket.mock_calls == [mocker.call.close()]

    def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        mock_unix_stream_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        enotconn_exception = self.configure_socket_mock_to_raise_ENOTCONN(mock_unix_stream_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = UnixStreamClient(
                mock_unix_stream_socket,
                protocol=mock_stream_protocol,
            )

        # Assert
        assert exc_info.value.errno == enotconn_exception.errno
        mock_socket_create_connection.assert_not_called()
        assert mock_unix_stream_socket.mock_calls == [mocker.call.getpeername(), mocker.call.close()]

    def test____dunder_init____invalid_first_argument____invalid_object(
        self,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_object = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^expected str, bytes or os.PathLike object, not .+$"):
            _ = UnixStreamClient(
                invalid_object,
                protocol=mock_stream_protocol,
            )

    def test____dunder_init____invalid_arguments____unknown_overload(
        self,
        local_address: str | bytes,
        mock_unix_stream_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = UnixStreamClient(
                mock_unix_stream_socket,
                protocol=mock_stream_protocol,
                local_path=local_address,
                connect_timeout=123,
            )

        assert mock_unix_stream_socket.mock_calls == []

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____protocol____invalid_value(
        self,
        use_socket: bool,
        remote_address: str | bytes,
        mock_unix_stream_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            if use_socket:
                _ = UnixStreamClient(
                    mock_unix_stream_socket,
                    protocol=mock_datagram_protocol,
                )
            else:
                _ = UnixStreamClient(
                    remote_address,
                    protocol=mock_datagram_protocol,
                )

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____max_recv_size____invalid_value(
        self,
        max_recv_size: Any,
        use_socket: bool,
        remote_address: str | bytes,
        mock_stream_endpoint_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mock_socket_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        ## The check is performed by the StreamEndpoint constructor, so we simulate an error raised.
        mock_stream_endpoint_cls.side_effect = ValueError("'max_recv_size' must be a strictly positive integer")

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            if use_socket:
                _ = UnixStreamClient(
                    mock_unix_stream_socket,
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )
            else:
                _ = UnixStreamClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )
        mock_stream_endpoint_cls.assert_called_once_with(
            mock_socket_stream_transport,
            mock_stream_protocol,
            max_recv_size=max_recv_size,
        )
        mock_socket_stream_transport.close.assert_called_once()

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_endpoint: MagicMock,
        mock_stream_protocol: MagicMock,
        remote_address: str | bytes,
    ) -> None:
        # Arrange
        client: UnixStreamClient[Any, Any] = UnixStreamClient(remote_address, mock_stream_protocol)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed client .+$"):
            del client

        mock_stream_endpoint.close.assert_called_once_with()

    def test____close____default(
        self,
        client: UnixStreamClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closed()

        # Act
        client.close()

        # Assert
        assert client.is_closed()
        mock_stream_endpoint.close.assert_called_once_with()

    def test____get_local_name____ask_for_address(
        self,
        client: UnixStreamClient[Any, Any],
        local_address: str | bytes,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_stream_socket.getsockname.reset_mock()

        # Act
        address = client.get_local_name()

        # Assert
        assert isinstance(address, UnixSocketAddress)
        mock_unix_stream_socket.getsockname.assert_called_once()
        assert address.as_raw() == local_address

    def test____get_peer_name____ask_for_address(
        self,
        client: UnixStreamClient[Any, Any],
        remote_address: str | bytes,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_stream_socket.getpeername.reset_mock()

        # Act
        address = client.get_peer_name()

        # Assert
        assert isinstance(address, UnixSocketAddress)
        mock_unix_stream_socket.getpeername.assert_called_once()
        assert address.as_raw() == remote_address

    def test____get_local_or_peer_name____closed_client(
        self,
        client: UnixStreamClient[Any, Any],
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        mock_unix_stream_socket.reset_mock()

        # Act & Assert
        with pytest.raises(ClientClosedError):
            client.get_local_name()
        with pytest.raises(ClientClosedError):
            client.get_peer_name()

        mock_unix_stream_socket.getsockname.assert_not_called()
        mock_unix_stream_socket.getpeername.assert_not_called()

    def test____get_peer_credentials____lazy_peer_creds(
        self,
        client: UnixStreamClient[Any, Any],
        fake_ucred: UnixCredentials,
        mock_get_peer_credentials: MagicMock,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_peer_credentials.assert_not_called()

        # Act
        peer_creds = client.get_peer_credentials()

        # Assert
        assert peer_creds == fake_ucred
        mock_get_peer_credentials.assert_called_once_with(mock_unix_stream_socket)

    def test____get_peer_credentials____cache_result(
        self,
        client: UnixStreamClient[Any, Any],
        mock_get_peer_credentials: MagicMock,
    ) -> None:
        # Arrange
        _ = client.get_peer_credentials()
        mock_get_peer_credentials.reset_mock()

        # Act
        for _ in range(3):
            assert client.get_peer_credentials() is client.get_peer_credentials()

        # Assert
        mock_get_peer_credentials.assert_not_called()

    def test____get_peer_credentials____closed_client(
        self,
        client: UnixStreamClient[Any, Any],
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        mock_unix_stream_socket.reset_mock()

        # Act & Assert
        with pytest.raises(ClientClosedError):
            client.get_peer_credentials()

        mock_unix_stream_socket.getsockname.assert_not_called()
        mock_unix_stream_socket.getpeername.assert_not_called()

    def test____fileno____default(
        self,
        client: UnixStreamClient[Any, Any],
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        fd = client.fileno()

        # Assert
        mock_unix_stream_socket.fileno.assert_called_once_with()
        assert fd == mock_unix_stream_socket.fileno.return_value

    def test____socket_property____cached_attribute(
        self,
        client: UnixStreamClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert client.socket is client.socket

    def test____send_packet____send_bytes_to_socket(
        self,
        client: UnixStreamClient[Any, Any],
        send_timeout: float | None,
        mock_unix_stream_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_unix_stream_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: UnixStreamClient[Any, Any],
        send_timeout: float | None,
        mock_unix_stream_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_unix_stream_socket.getsockopt.return_value = errno.EBUSY

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.errno == errno.EBUSY
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_unix_stream_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    def test____send_packet____closed_client_error(
        self,
        client: UnixStreamClient[Any, Any],
        send_timeout: float | None,
        mock_unix_stream_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_not_called()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    def test____send_packet____convert_connection_errors(
        self,
        client: UnixStreamClient[Any, Any],
        send_timeout: float | None,
        mock_unix_stream_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_stream_endpoint.close.assert_not_called()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: UnixStreamClient[Any, Any],
        send_timeout: float | None,
        mock_unix_stream_socket: MagicMock,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)
        mock_stream_endpoint.close.assert_not_called()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    def test____send_eof____socket_send_eof(
        self,
        client: UnixStreamClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client.send_eof()

        # Assert
        mock_stream_endpoint.send_eof.assert_called_once_with()
        mock_stream_endpoint.close.assert_not_called()

    def test____send_eof____closed_client(
        self,
        client: UnixStreamClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        client.close()

        # Act
        client.send_eof()

        # Assert
        mock_stream_endpoint.send_eof.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____send_eof____closed_socket_error(
        self,
        closed_socket_errno: int,
        client: UnixStreamClient[Any, Any],
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.send_eof.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_eof()

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_stream_endpoint.send_eof.assert_called_once_with()
        mock_stream_endpoint.close.assert_not_called()

    def test____recv_packet____receive_bytes_from_socket(
        self,
        client: UnixStreamClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = [mocker.sentinel.packet]

        # Act
        packet: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)
        assert packet is mocker.sentinel.packet

    def test____recv_packet____protocol_parse_error(
        self,
        client: UnixStreamClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Sorry", b""))
        mock_stream_endpoint.recv_packet.side_effect = [expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is expected_error

    def test____recv_packet____closed_client_error(
        self,
        client: UnixStreamClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.recv_packet.assert_not_called()

    def test____recv_packet____convert_connection_errors(
        self,
        client: UnixStreamClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = ConnectionError

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____recv_packet____convert_closed_socket_errors(
        self,
        closed_socket_errno: int,
        client: UnixStreamClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_endpoint.recv_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client.is_closed()
        mock_stream_endpoint.recv_packet.assert_called_once_with(timeout=recv_timeout)
        mock_stream_endpoint.close.assert_not_called()

    def test____special_case____separate_send_and_receive_locks(
        self,
        client: UnixStreamClient[Any, Any],
        send_timeout: float | None,
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def recv_side_effect(**kwargs: Any) -> bytes:
            client.send_packet(mocker.sentinel.packet, timeout=send_timeout)
            raise ConnectionAbortedError

        mock_stream_endpoint.recv_packet.side_effect = recv_side_effect

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_endpoint.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=send_timeout)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    def test____special_case____close_during_recv_call(
        self,
        closed_socket_errno: int,
        client: UnixStreamClient[Any, Any],
        recv_timeout: float | None,
        mock_stream_endpoint: MagicMock,
    ) -> None:
        # Arrange
        def recv_side_effect(**kwargs: Any) -> bytes:
            client.close()
            raise OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        mock_stream_endpoint.recv_packet.side_effect = recv_side_effect

        # Act & Assert
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)


@PlatformMarkers.skipif_platform_win32
class TestUnixStreamSocketFactory:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_cls(
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        return mocker.patch("socket.socket", side_effect=[mock_unix_stream_socket])

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
    @pytest.mark.parametrize("connect_timeout", [None, 10.4], ids=lambda p: f"connect_timeout=={p}")
    def test____create_unix_stream_connection____default(
        self,
        local_address: str | bytes | None,
        remote_address: str | bytes,
        connect_timeout: float | None,
        mock_socket_cls: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        AF_UNIX = AF_UNIX_or_skip()
        mock_unix_stream_socket.bind.return_value = None
        mock_unix_stream_socket.connect.return_value = None

        # Act
        sock = _create_unix_stream_connection(
            remote_address,
            connect_timeout=connect_timeout,
            local_path=local_address,
        )

        # Assert
        assert sock is mock_unix_stream_socket
        mock_socket_cls.assert_called_once_with(AF_UNIX, SOCK_STREAM, 0)
        if local_address is None:
            assert mock_unix_stream_socket.mock_calls == [
                mocker.call.settimeout(connect_timeout),
                mocker.call.connect(remote_address),
            ]
        else:
            assert mock_unix_stream_socket.mock_calls == [
                mocker.call.bind(local_address),
                mocker.call.settimeout(connect_timeout),
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
    @pytest.mark.parametrize("connect_timeout", [None, 10.4], ids=lambda p: f"connect_timeout=={p}")
    @pytest.mark.parametrize(
        "bind_error",
        [
            OSError(errno.EPERM, os.strerror(errno.EPERM)),
            OSError("AF_UNIX path too long."),
        ],
        ids=lambda exc: f"bind_error=={exc!r}",
    )
    def test____create_unix_stream_connection____bind_error(
        self,
        local_address: str | bytes,
        remote_address: str | bytes,
        connect_timeout: float | None,
        bind_error: OSError,
        mock_socket_cls: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        AF_UNIX = AF_UNIX_or_skip()
        mock_unix_stream_socket.bind.side_effect = bind_error
        mock_unix_stream_socket.connect.return_value = None

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = _create_unix_stream_connection(
                remote_address,
                connect_timeout=connect_timeout,
                local_path=local_address,
            )

        # Assert
        mock_socket_cls.assert_called_once_with(AF_UNIX, SOCK_STREAM, 0)
        assert mock_unix_stream_socket.mock_calls == [
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
    @pytest.mark.parametrize("connect_timeout", [None, 10.4], ids=lambda p: f"connect_timeout=={p}")
    @pytest.mark.parametrize(
        "connect_error",
        [
            OSError(errno.ECONNREFUSED, os.strerror(errno.ECONNREFUSED)),
            OSError(errno.EPERM, os.strerror(errno.EPERM)),
        ],
        ids=lambda exc: f"connect_error=={exc!r}",
    )
    def test____create_unix_stream_connection____connect_error(
        self,
        remote_address: str | bytes,
        connect_timeout: float | None,
        connect_error: OSError,
        mock_socket_cls: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        AF_UNIX = AF_UNIX_or_skip()
        mock_unix_stream_socket.connect.side_effect = connect_error

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = _create_unix_stream_connection(
                remote_address,
                connect_timeout=connect_timeout,
            )

        # Assert
        mock_socket_cls.assert_called_once_with(AF_UNIX, SOCK_STREAM, 0)
        assert mock_unix_stream_socket.mock_calls == [
            mocker.call.settimeout(connect_timeout),
            mocker.call.connect(remote_address),
            mocker.call.close(),
        ]
        assert exc_info.value.errno == connect_error.errno
