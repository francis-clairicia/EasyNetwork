from __future__ import annotations

import copy
import pathlib
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import ClientClosedError, TypedAttributeLookupError
from easynetwork.lowlevel.socket import SocketProxy, UnixCredentials, UnixSocketAddress, UNIXSocketAttribute
from easynetwork.servers.async_unix_stream import AsyncUnixStreamServer, _ConnectedClientAPI
from easynetwork.servers.handlers import UNIXClientAttribute

import pytest

from .....fixtures.socket import AF_UNIX_or_skip
from .....tools import PlatformMarkers
from ...._utils import AsyncDummyLock
from ....base import BaseTestSocket
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
@PlatformMarkers.skipif_platform_win32
class TestAsyncUnixStreamServer:
    @pytest.fixture
    @staticmethod
    def server(
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> AsyncUnixStreamServer[Any, Any]:
        return AsyncUnixStreamServer("/path/to/sock", mock_stream_protocol, mock_stream_request_handler, mock_backend)

    @pytest.mark.parametrize(
        "valid_path",
        [
            "/path/to/sock",
            b"/path/to/sock",
            pathlib.Path("/path/to/sock"),
            b"\0abstract",
            "\0abstract",
            b"",  # <- Indicates the kernel to give an arbitrary abstract Unix address.
            "",  # <- Indicates the kernel to give an arbitrary abstract Unix address.
            UnixSocketAddress.from_pathname("/path/to/sock"),
            UnixSocketAddress.from_abstract_name(b"abstract"),
            UnixSocketAddress(),  # <- Indicates the kernel to give an arbitrary abstract Unix address.
        ],
        ids=repr,
    )
    async def test____dunder_init____path____valid_value(
        self,
        valid_path: str | bytes | pathlib.Path | UnixSocketAddress,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        _ = AsyncUnixStreamServer(valid_path, mock_stream_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____path____invalid_value____unknown_type(
        self,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_path = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^expected str, bytes or os.PathLike object"):
            _ = AsyncUnixStreamServer(invalid_path, mock_stream_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____path____invalid_value____null_bytes_in_path(
        self,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        invalid_path = "/path/with/\0/bytes"

        # Act & Assert
        with pytest.raises(ValueError, match=r"^paths must not contain interior null bytes$"):
            _ = AsyncUnixStreamServer(invalid_path, mock_stream_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = AsyncUnixStreamServer("/path/to/sock", mock_datagram_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncStreamRequestHandler object, got .*$"):
            _ = AsyncUnixStreamServer("/path/to/sock", mock_stream_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____backend____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = AsyncUnixStreamServer("/path/to/sock", mock_stream_protocol, mock_stream_request_handler, invalid_backend)

    async def test____get_backend____returns_linked_instance(
        self,
        server: AsyncUnixStreamServer[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_backend


@pytest.mark.asyncio
@PlatformMarkers.skipif_platform_win32
class TestConnectedClientAPI(BaseTestSocket):
    @pytest.fixture
    @staticmethod
    def local_address() -> str:
        return "/path/to/server.sock"

    @pytest.fixture(params=["NAMED", "ABSTRACT", "UNNAMED"])
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
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        from easynetwork.lowlevel.api_async.servers.stream import ConnectedStreamClient
        from easynetwork.lowlevel.socket import _get_socket_extra

        cls.set_local_address_to_socket_mock(mock_unix_stream_socket, AF_UNIX_or_skip(), local_address)
        cls.set_remote_address_to_socket_mock(mock_unix_stream_socket, AF_UNIX_or_skip(), remote_address)
        mock_get_peer_credentials.side_effect = lambda sock: copy.copy(fake_ucred)

        mock_connected_stream_client = make_transport_mock(mocker=mocker, spec=ConnectedStreamClient, backend=mock_backend)
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

    async def test____dunder_init____initialize_inner_client(
        self,
        local_address: str,
        remote_address: str | bytes,
        fake_ucred: UnixCredentials,
        mock_unix_stream_socket: MagicMock,
        mock_backend: MagicMock,
        mock_connected_stream_client: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: _ConnectedClientAPI[Any] = _ConnectedClientAPI(
            UnixSocketAddress.from_raw(remote_address),
            mock_connected_stream_client,
        )

        # Assert
        assert mock_unix_stream_socket.setsockopt.mock_calls == []
        assert client.backend() is mock_backend
        assert isinstance(client.extra(UNIXClientAttribute.socket), SocketProxy)
        assert client.extra(UNIXClientAttribute.local_name).as_raw() == local_address
        assert client.extra(UNIXClientAttribute.peer_name).as_raw() == remote_address
        assert client.extra(UNIXClientAttribute.peer_credentials) == fake_ucred
        assert client.extra(UNIXSocketAttribute.family) == AF_UNIX_or_skip()
        assert client.extra(mocker.sentinel.custom_attribute) is mocker.sentinel.custom_value

    @pytest.mark.parametrize("remote_address", ["NAMED", "ABSTRACT"], indirect=True)
    async def test____dunder_init____initialize_inner_client____cache_peer_name_if_named(
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

    async def test____dunder_init____initialize_inner_client____cache_peer_name_if_named____eager_close_error(
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
    async def test____dunder_init____initialize_inner_client____cache_peer_name_if_named____retry_until_named(
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
        self.set_remote_address_to_socket_mock(mock_unix_stream_socket, AF_UNIX_or_skip(), b"\0new_address")
        mock_unix_stream_socket.reset_mock()
        assert client.extra(UNIXClientAttribute.peer_name).as_abstract_name() == b"new_address"
        for _ in range(3):
            assert client.extra(UNIXClientAttribute.peer_name) is client.extra(UNIXClientAttribute.peer_name)
        mock_unix_stream_socket.getpeername.assert_called_once_with()

    async def test____dunder_init____initialize_inner_client____lazy_peer_creds(
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

    async def test____extra_attributes____credentials_lookup_raises_OSError(
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

    async def test____extra_attributes____get_peer_credentials_not_implemented(
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

    async def test____send_packet____send_bytes_to_socket(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_connected_stream_client.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        ## This client object should not check SO_ERROR
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("method", ["close", "force_disconnect"])
    async def test____send_packet____closed_client(
        self,
        method: Literal["close", "force_disconnect"],
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match method:
            case "close":
                await client.aclose()
            case "force_disconnect":
                await client._on_disconnect()
        assert client.is_closing()
        mock_connected_stream_client.reset_mock()

        # Act
        with pytest.raises(ClientClosedError):
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_connected_stream_client.send_packet.assert_not_awaited()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    async def test____special_case____close_cancelled_during_lock_acquisition(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_connected_stream_client.aclose.assert_awaited_once_with()

    async def test____special_case____close_cancelled_during_lock_acquisition____endpoint_is_already_closing(
        self,
        client: _ConnectedClientAPI[Any],
        mock_connected_stream_client: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client._on_disconnect()
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_connected_stream_client.aclose.assert_not_awaited()
