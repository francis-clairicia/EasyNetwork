from __future__ import annotations

import copy
import errno
import pathlib
import sys
from typing import TYPE_CHECKING, Any, Literal

import pytest

from .....tools import PlatformMarkers
from ....base import BaseTestUnixSocketTransport
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


if sys.platform != "win32":
    from easynetwork.exceptions import ClientClosedError, TypedAttributeLookupError
    from easynetwork.lowlevel.socket import SocketAncillary, SocketProxy, UnixCredentials, UnixSocketAddress, UNIXSocketAttribute
    from easynetwork.servers.handlers import UNIXClientAttribute
    from easynetwork.servers.threaded_unix_stream import ThreadedUnixStreamServer, _ConnectedClientAPI

    class TestThreadedUnixStreamServer:

        @pytest.mark.parametrize(
            "valid_path",
            [
                "/path/to/sock",
                b"/path/to/sock",
                pathlib.Path("/path/to/sock"),
                UnixSocketAddress.from_pathname("/path/to/sock"),
            ],
            ids=repr,
        )
        def test____dunder_init____path____valid_value(
            self,
            valid_path: str | bytes | pathlib.Path | UnixSocketAddress,
            mock_stream_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
        ) -> None:
            # Arrange

            # Act & Assert
            _ = ThreadedUnixStreamServer(valid_path, mock_stream_protocol, mock_stream_request_handler)

        if sys.platform == "linux":

            @pytest.mark.parametrize(
                "valid_path",
                [
                    b"\0abstract",
                    "\0abstract",
                    UnixSocketAddress.from_abstract_name(b"abstract"),
                ],
                ids=repr,
            )
            def test____dunder_init____path____valid_value____abstract_sockets(
                self,
                valid_path: str | bytes,
                mock_stream_protocol: MagicMock,
                mock_stream_request_handler: MagicMock,
            ) -> None:
                # Arrange

                # Act & Assert
                _ = ThreadedUnixStreamServer(valid_path, mock_stream_protocol, mock_stream_request_handler)

        @pytest.mark.parametrize(
            "valid_path",
            # Indicates the kernel to give an arbitrary abstract Unix address.
            [b"", "", UnixSocketAddress()],
            ids=repr,
        )
        def test____dunder_init____path____automatic_socket_bind(
            self,
            valid_path: str | bytes | UnixSocketAddress,
            mock_stream_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
        ) -> None:
            # Arrange
            from easynetwork.lowlevel._unix_utils import platform_supports_automatic_socket_bind

            # Act & Assert
            if platform_supports_automatic_socket_bind():
                _ = ThreadedUnixStreamServer(valid_path, mock_stream_protocol, mock_stream_request_handler)
            else:
                with pytest.raises(
                    ValueError,
                    match=r"^path parameter is required on this platform and cannot be an empty string",
                ):
                    _ = ThreadedUnixStreamServer(valid_path, mock_stream_protocol, mock_stream_request_handler)

        def test____dunder_init____path____invalid_value____unknown_type(
            self,
            mock_stream_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange
            invalid_path = mocker.NonCallableMagicMock(spec=object)

            # Act & Assert
            with pytest.raises(TypeError, match=r"^expected str, bytes or os.PathLike object"):
                _ = ThreadedUnixStreamServer(invalid_path, mock_stream_protocol, mock_stream_request_handler)

        @pytest.mark.parametrize(
            "invalid_path",
            [
                pytest.param("/path/with/\0/bytes", id="byte in middle"),
                pytest.param(
                    "\0/path/with/nul/bytes", id="byte at beginning", marks=[PlatformMarkers.abstract_sockets_unsupported]
                ),
            ],
        )
        def test____dunder_init____path____invalid_value____null_bytes_in_path(
            self,
            invalid_path: str,
            mock_stream_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
        ) -> None:
            # Arrange

            # Act & Assert
            with pytest.raises(ValueError, match=r"^paths must not contain interior null bytes$"):
                _ = ThreadedUnixStreamServer(invalid_path, mock_stream_protocol, mock_stream_request_handler)

        def test____dunder_init____protocol____invalid_value(
            self,
            mock_datagram_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
        ) -> None:
            # Arrange

            # Act & Assert
            with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
                _ = ThreadedUnixStreamServer("/path/to/sock", mock_datagram_protocol, mock_stream_request_handler)

        def test____dunder_init____request_handler____invalid_value(
            self,
            mock_stream_protocol: MagicMock,
            mock_datagram_request_handler: MagicMock,
        ) -> None:
            # Arrange

            # Act & Assert
            with pytest.raises(TypeError, match=r"^Expected a BlockingStreamRequestHandler object, got .*$"):
                _ = ThreadedUnixStreamServer("/path/to/sock", mock_stream_protocol, mock_datagram_request_handler)

        @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size__{p}")
        def test____dunder_init____max_recv_size____invalid_value(
            self,
            max_recv_size: Any,
            mock_stream_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
        ) -> None:
            with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
                _ = ThreadedUnixStreamServer(
                    "/path/to/sock",
                    mock_stream_protocol,
                    mock_stream_request_handler,
                    max_recv_size=max_recv_size,
                )

        @pytest.mark.parametrize("invalid_bufsize", [0, -42, 3.14])
        def test____dunder_init____ancillary_bufsize____invalid_value(
            self,
            invalid_bufsize: Any,
            mock_stream_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
        ) -> None:
            # Arrange

            # Act & Assert
            with pytest.raises(
                ValueError,
                match=r"^ancillary_bufsize must be a strictly positive integer$",
            ):
                _ = ThreadedUnixStreamServer(
                    "/path/to/sock",
                    mock_stream_protocol,
                    mock_stream_request_handler,
                    ancillary_bufsize=invalid_bufsize,
                )

        @pytest.mark.parametrize("valid_bufsize", [1, 8192, 2**16])
        def test____dunder_init____ancillary_bufsize____valid_value(
            self,
            valid_bufsize: Any,
            mock_stream_protocol: MagicMock,
            mock_stream_request_handler: MagicMock,
        ) -> None:
            # Arrange

            # Act & Assert
            _ = ThreadedUnixStreamServer(
                "/path/to/sock",
                mock_stream_protocol,
                mock_stream_request_handler,
                ancillary_bufsize=valid_bufsize,
            )

    class TestConnectedClientAPI(BaseTestUnixSocketTransport):
        @pytest.fixture
        @staticmethod
        def local_address() -> str:
            return "/path/to/server.sock"

        @pytest.fixture(
            params=[
                pytest.param("NAMED"),
                pytest.param("ABSTRACT", marks=PlatformMarkers.supports_abstract_sockets),
                pytest.param("UNNAMED"),
            ]
        )
        @staticmethod
        def remote_address(request: pytest.FixtureRequest) -> str | bytes:
            match request.param:
                case "NAMED":
                    return "/path/to/client.sock"
                case "ABSTRACT":
                    return b"\0remote_address"
                case "UNNAMED":
                    return ""
                case _:
                    pytest.fail(f"Invalid remote_address parameter: {request.param}")

        @pytest.fixture
        @classmethod
        def mock_connected_stream_client(
            cls,
            local_address: str,
            remote_address: str | bytes,
            fake_ucred: UnixCredentials,
            mock_unix_stream_socket: MagicMock,
            mock_get_peer_credentials: MagicMock,
            mocker: MockerFixture,
        ) -> MagicMock:
            from easynetwork.lowlevel.api_sync.servers.selector_stream import ConnectedStreamClient
            from easynetwork.lowlevel.socket import _get_socket_extra

            cls.set_local_address_to_socket_mock(mock_unix_stream_socket, mock_unix_stream_socket.family, local_address)
            cls.set_remote_address_to_socket_mock(mock_unix_stream_socket, mock_unix_stream_socket.family, remote_address)
            mock_get_peer_credentials.side_effect = lambda sock: copy.copy(fake_ucred)

            mock_connected_stream_client = make_transport_mock(mocker=mocker, spec=ConnectedStreamClient)
            mock_connected_stream_client.extra_attributes = {
                **_get_socket_extra(mock_unix_stream_socket, wrap_in_proxy=False),
                # Used to ensure that ConnectedStreamClient specific attributes are merged.
                mocker.sentinel.custom_attribute: lambda: mocker.sentinel.custom_value,
            }
            return mock_connected_stream_client

        @pytest.fixture
        @staticmethod
        def client(
            mock_unix_stream_socket: MagicMock,
            mock_connected_stream_client: MagicMock,
        ) -> _ConnectedClientAPI[Any]:
            peer_name = UnixSocketAddress.from_raw(mock_connected_stream_client.extra(UNIXSocketAttribute.peername))
            client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(peer_name, mock_connected_stream_client)
            mock_unix_stream_socket.reset_mock()
            return client

        def test____dunder_init____initialize_inner_client(
            self,
            local_address: str,
            remote_address: str | bytes,
            fake_ucred: UnixCredentials,
            mock_unix_stream_socket: MagicMock,
            mock_connected_stream_client: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange
            from socket import AF_UNIX

            # Act
            client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(
                UnixSocketAddress.from_raw(remote_address),
                mock_connected_stream_client,
            )

            # Assert
            assert mock_unix_stream_socket.setsockopt.mock_calls == []
            assert isinstance(client.extra(UNIXClientAttribute.socket), SocketProxy)
            assert client.extra(UNIXClientAttribute.local_name).as_raw() == local_address
            assert client.extra(UNIXClientAttribute.peer_name).as_raw() == remote_address
            assert client.extra(UNIXClientAttribute.peer_credentials) == fake_ucred
            assert client.extra(UNIXSocketAttribute.family) == AF_UNIX
            assert client.extra(mocker.sentinel.custom_attribute) is mocker.sentinel.custom_value

        @pytest.mark.parametrize(
            "remote_address",
            [
                pytest.param("NAMED"),
                pytest.param("ABSTRACT", marks=PlatformMarkers.supports_abstract_sockets),
            ],
            indirect=True,
        )
        def test____dunder_init____initialize_inner_client____cache_peer_name_if_named(
            self,
            remote_address: str | bytes,
            mock_unix_stream_socket: MagicMock,
            mock_connected_stream_client: MagicMock,
        ) -> None:
            # Arrange

            # Act
            client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(UnixSocketAddress(), mock_connected_stream_client)

            # Assert
            mock_unix_stream_socket.getpeername.assert_not_called()
            assert client.extra(UNIXClientAttribute.peer_name).as_raw() == remote_address
            mock_unix_stream_socket.getpeername.assert_called_once()
            ## Should have cached the result
            mock_unix_stream_socket.reset_mock()
            for _ in range(3):
                assert client.extra(UNIXClientAttribute.peer_name) is client.extra(UNIXClientAttribute.peer_name)
            mock_unix_stream_socket.getpeername.assert_not_called()

        def test____dunder_init____initialize_inner_client____cache_peer_name_if_named____eager_close_error(
            self,
            mock_unix_stream_socket: MagicMock,
            mock_connected_stream_client: MagicMock,
        ) -> None:
            # Arrange
            self.configure_socket_mock_to_raise_ENOTCONN(mock_unix_stream_socket)

            # Act
            _ = _ConnectedClientAPI(UnixSocketAddress(), mock_connected_stream_client)

            # Assert
            mock_unix_stream_socket.getpeername.assert_not_called()

        @pytest.mark.parametrize("remote_address", ["UNNAMED"], indirect=True)
        def test____dunder_init____initialize_inner_client____cache_peer_name_if_named____retry_until_named(
            self,
            mock_unix_stream_socket: MagicMock,
            mock_connected_stream_client: MagicMock,
        ) -> None:
            # Arrange

            # Act
            client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(UnixSocketAddress(), mock_connected_stream_client)

            # Assert
            mock_unix_stream_socket.getpeername.assert_not_called()
            assert client.extra(UNIXClientAttribute.peer_name).is_unnamed()

            ## It is possible to bind a Unix socket AFTER a call to connect(2), therefore retry to call getpeername() each time
            ## the peer name is requested.
            mock_unix_stream_socket.reset_mock()
            for _ in range(3):
                assert client.extra(UNIXClientAttribute.peer_name).is_unnamed()
            assert mock_unix_stream_socket.getpeername.call_count == 3

            ## The call to bind(2) or the autobind feature happened.
            ## Should have cached the result
            self.set_remote_address_to_socket_mock(
                mock_unix_stream_socket,
                mock_unix_stream_socket.family,
                b"/path/to/new_address",
            )
            mock_unix_stream_socket.reset_mock()
            assert client.extra(UNIXClientAttribute.peer_name).as_pathname() == pathlib.Path("/path/to/new_address")
            for _ in range(3):
                assert client.extra(UNIXClientAttribute.peer_name) is client.extra(UNIXClientAttribute.peer_name)
            mock_unix_stream_socket.getpeername.assert_called_once_with()

        def test____dunder_init____initialize_inner_client____lazy_peer_creds(
            self,
            mock_get_peer_credentials: MagicMock,
            fake_ucred: UnixCredentials,
            mock_connected_stream_client: MagicMock,
        ) -> None:
            # Arrange

            # Act
            client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(UnixSocketAddress(), mock_connected_stream_client)

            # Assert
            mock_get_peer_credentials.assert_not_called()
            ## Once requested, cache the result
            assert client.extra(UNIXClientAttribute.peer_credentials) == fake_ucred
            for _ in range(3):
                assert client.extra(UNIXClientAttribute.peer_credentials) is client.extra(UNIXClientAttribute.peer_credentials)
            mock_get_peer_credentials.assert_called_once()

        def test____extra_attributes____credentials_lookup_raises_OSError(
            self,
            client: _ConnectedClientAPI[Any],
            mock_get_peer_credentials: MagicMock,
        ) -> None:
            # Arrange
            from errno import EACCES
            from os import strerror

            os_error = EACCES
            mock_get_peer_credentials.side_effect = OSError(os_error, strerror(os_error))

            # Act & Assert
            with pytest.raises(TypedAttributeLookupError):
                client.extra(UNIXClientAttribute.peer_credentials)
            mock_get_peer_credentials.assert_called_once()

        def test____extra_attributes____get_peer_credentials_not_implemented(
            self,
            client: _ConnectedClientAPI[Any],
            mock_get_peer_credentials: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange
            get_peer_credentials_impl_from_platform = mocker.patch(
                "easynetwork.lowlevel._unix_utils._get_peer_credentials_impl_from_platform",
                side_effect=NotImplementedError,
            )

            # Act & Assert
            with pytest.raises(TypedAttributeLookupError):
                client.extra(UNIXClientAttribute.peer_credentials)
            get_peer_credentials_impl_from_platform.assert_called_once_with()
            mock_get_peer_credentials.assert_not_called()

        def test____send_packet____send_bytes_to_socket(
            self,
            client: _ConnectedClientAPI[Any],
            mock_connected_stream_client: MagicMock,
            mock_unix_stream_socket: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange

            # Act
            client.send_packet(mocker.sentinel.packet)

            # Assert
            mock_connected_stream_client.send_packet.assert_called_once_with(mocker.sentinel.packet, timeout=None)
            mock_connected_stream_client.send_packet_with_ancillary.assert_not_called()
            ## This client object should not check SO_ERROR
            mock_unix_stream_socket.getsockopt.assert_not_called()

        def test____send_packet____send_bytes_to_socket____with_timeout(
            self,
            client: _ConnectedClientAPI[Any],
            mock_connected_stream_client: MagicMock,
            mock_unix_stream_socket: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange

            # Act
            client.send_packet(mocker.sentinel.packet, timeout=mocker.sentinel.timeout)

            # Assert
            mock_connected_stream_client.send_packet.assert_called_once_with(
                mocker.sentinel.packet,
                timeout=mocker.sentinel.timeout,
            )
            mock_connected_stream_client.send_packet_with_ancillary.assert_not_called()
            ## This client object should not check SO_ERROR
            mock_unix_stream_socket.getsockopt.assert_not_called()

        def test____send_packet_with_ancillary____send_bytes_to_socket(
            self,
            client: _ConnectedClientAPI[Any],
            mock_connected_stream_client: MagicMock,
            mock_unix_stream_socket: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange

            # Act
            client.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata)

            # Assert
            mock_connected_stream_client.send_packet_with_ancillary.assert_called_once_with(
                mocker.sentinel.packet,
                mocker.sentinel.ancdata,
                timeout=None,
            )
            mock_connected_stream_client.send_packet.assert_not_called()
            ## This client object should not check SO_ERROR
            mock_unix_stream_socket.getsockopt.assert_not_called()

        def test____send_packet_with_ancillary____send_bytes_to_socket____with_timeout(
            self,
            client: _ConnectedClientAPI[Any],
            mock_connected_stream_client: MagicMock,
            mock_unix_stream_socket: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange

            # Act
            client.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata, timeout=mocker.sentinel.timeout)

            # Assert
            mock_connected_stream_client.send_packet_with_ancillary.assert_called_once_with(
                mocker.sentinel.packet,
                mocker.sentinel.ancdata,
                timeout=mocker.sentinel.timeout,
            )
            mock_connected_stream_client.send_packet.assert_not_called()
            ## This client object should not check SO_ERROR
            mock_unix_stream_socket.getsockopt.assert_not_called()

        def test____send_packet_with_ancillary____socket_ancillary(
            self,
            client: _ConnectedClientAPI[Any],
            mock_connected_stream_client: MagicMock,
            mock_unix_stream_socket: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange
            mock_socket_ancillary = mocker.NonCallableMagicMock(spec=SocketAncillary)
            mock_socket_ancillary.as_raw.return_value = mocker.sentinel.ancdata

            # Act
            client.send_packet_with_ancillary(mocker.sentinel.packet, mock_socket_ancillary)

            # Assert
            mock_connected_stream_client.send_packet_with_ancillary.assert_called_once_with(
                mocker.sentinel.packet,
                mocker.sentinel.ancdata,
                timeout=mocker.ANY,
            )
            mock_connected_stream_client.send_packet.assert_not_called()
            assert mock_socket_ancillary.mock_calls == [mocker.call.as_raw()]
            ## This client object should not check SO_ERROR
            mock_unix_stream_socket.getsockopt.assert_not_called()

        @pytest.mark.parametrize("method", ["close", "abort", "force_disconnect"])
        @pytest.mark.parametrize("with_ancillary_data", [False, True], ids=lambda p: f"with_ancillary_data__{p}")
        def test____send_packet____closed_client(
            self,
            method: Literal["close", "abort", "force_disconnect"],
            with_ancillary_data: bool,
            client: _ConnectedClientAPI[Any],
            mock_connected_stream_client: MagicMock,
            mock_unix_stream_socket: MagicMock,
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
                if with_ancillary_data:
                    client.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata)
                else:
                    client.send_packet(mocker.sentinel.packet)

            # Assert
            mock_connected_stream_client.send_packet.assert_not_called()
            mock_connected_stream_client.send_packet_with_ancillary.assert_not_called()
            mock_unix_stream_socket.getsockopt.assert_not_called()

        def test____socket_proxy____setsockopt(
            self,
            client: _ConnectedClientAPI[Any],
            mock_unix_stream_socket: MagicMock,
            mocker: MockerFixture,
        ) -> None:
            # Arrange
            from socket import SO_KEEPALIVE, SOL_SOCKET

            assert mock_unix_stream_socket.setsockopt.mock_calls == []

            socket = client.extra(UNIXClientAttribute.socket)

            # Act
            socket.setsockopt(SOL_SOCKET, SO_KEEPALIVE, True)

            # Assert
            assert mock_unix_stream_socket.setsockopt.mock_calls == [mocker.call(SOL_SOCKET, SO_KEEPALIVE, True)]

        @pytest.mark.parametrize("method", ["close", "abort", "force_disconnect"])
        def test____socket_proxy____closed_client(
            self,
            method: Literal["close", "abort", "force_disconnect"],
            client: _ConnectedClientAPI[Any],
            mock_connected_stream_client: MagicMock,
            mock_unix_stream_socket: MagicMock,
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
            mock_unix_stream_socket.reset_mock()
            mock_unix_stream_socket.fileno.__name__ = "fileno"

            # Act & Assert
            socket = client.extra(UNIXClientAttribute.socket)
            assert socket.fileno() == -1
            with pytest.raises(OSError, check=lambda exc: exc.errno == errno.EBADF):
                socket.setsockopt(SOL_SOCKET, SO_KEEPALIVE, False)
            mock_unix_stream_socket.fileno.assert_not_called()
            mock_unix_stream_socket.setsockopt.assert_not_called()
