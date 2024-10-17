from __future__ import annotations

import contextlib
import errno
import os
import pathlib
from collections.abc import AsyncIterator
from socket import SO_ERROR, SOL_SOCKET
from typing import TYPE_CHECKING, Any

from easynetwork.clients.async_unix_datagram import AsyncUnixDatagramClient
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel.api_async.endpoints.datagram import AsyncDatagramEndpoint
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS
from easynetwork.lowlevel.socket import SocketProxy, UnixSocketAddress, _get_socket_extra

import pytest
import pytest_asyncio

from .....fixtures.socket import AF_UNIX_or_skip
from .....tools import PlatformMarkers
from ...._utils import AsyncDummyLock, unsupported_families
from ....base import UNIX_FAMILIES
from ...mock_tools import make_transport_mock
from .base import BaseTestClient

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

    from .....pytest_plugins.async_finalizer import AsyncFinalizer


@pytest.mark.asyncio
@PlatformMarkers.skipif_platform_win32
class TestAsyncUnixDatagramClient(BaseTestClient):
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
            cls.set_local_address_to_socket_mock(mock_unix_datagram_socket, socket_family, global_local_address)
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
            cls.set_remote_address_to_socket_mock(mock_unix_datagram_socket, socket_family, global_remote_address)
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
    def mock_datagram_endpoint(mocker: MockerFixture, mock_backend: MagicMock) -> MagicMock:
        mock_datagram_endpoint = make_transport_mock(mocker=mocker, spec=AsyncDatagramEndpoint, backend=mock_backend)
        mock_datagram_endpoint.recv_packet.return_value = mocker.sentinel.packet
        mock_datagram_endpoint.send_packet.return_value = None
        return mock_datagram_endpoint

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_datagram_endpoint_cls(mocker: MockerFixture, mock_datagram_endpoint: MagicMock) -> MagicMock:
        from easynetwork.lowlevel._utils import Flag

        was_called = Flag()

        def mock_endpoint_side_effect(transport: MagicMock, *args: Any, **kwargs: Any) -> MagicMock:
            if was_called.is_set():
                raise RuntimeError("Must be called once.")
            was_called.set()
            mock_datagram_endpoint.extra_attributes = transport.extra_attributes
            return mock_datagram_endpoint

        return mocker.patch(
            f"{AsyncUnixDatagramClient.__module__}.AsyncDatagramEndpoint",
            side_effect=mock_endpoint_side_effect,
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_unix_datagram_socket: MagicMock,
        socket_family: int,
        mock_backend: MagicMock,
        mock_datagram_transport: MagicMock,
    ) -> None:
        mock_unix_datagram_socket.family = socket_family
        mock_unix_datagram_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()

        mock_backend.create_unix_datagram_endpoint.return_value = mock_datagram_transport
        mock_backend.wrap_connected_datagram_socket.return_value = mock_datagram_transport

        mock_datagram_transport.backend.return_value = mock_backend
        mock_datagram_transport.extra_attributes = _get_socket_extra(mock_unix_datagram_socket, wrap_in_proxy=False)

    @pytest_asyncio.fixture
    @staticmethod
    async def client_not_connected(
        mock_unix_datagram_socket: MagicMock,
        mock_backend: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncIterator[AsyncUnixDatagramClient[Any, Any]]:
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            mock_unix_datagram_socket,
            mock_datagram_protocol,
            mock_backend,
        )
        assert not client.is_connected()
        async with contextlib.aclosing(client):
            yield client

    @pytest_asyncio.fixture
    @staticmethod
    async def client_connected(
        mock_unix_datagram_socket: MagicMock,
        mock_backend: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncIterator[AsyncUnixDatagramClient[Any, Any]]:
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            mock_unix_datagram_socket,
            mock_datagram_protocol,
            mock_backend,
        )
        async with contextlib.aclosing(client):
            await client.wait_connected()
            assert client.is_connected()
            yield client

    @pytest_asyncio.fixture(params=[False, True], ids=lambda boolean: f"client_connected=={boolean}")
    @staticmethod
    async def client_connected_or_not(
        request: pytest.FixtureRequest,
        mock_unix_datagram_socket: MagicMock,
        mock_backend: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncIterator[AsyncUnixDatagramClient[Any, Any]]:
        assert request.param in (True, False)
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            mock_unix_datagram_socket,
            mock_datagram_protocol,
            mock_backend,
        )
        async with contextlib.aclosing(client):
            if request.param:
                await client.wait_connected()
                assert client.is_connected()
            else:
                assert not client.is_connected()
            yield client

    async def test____dunder_init____with_remote_address(
        self,
        async_finalizer: AsyncFinalizer,
        local_address: str | bytes,
        remote_address: str | bytes,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_datagram_endpoint_cls: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
            local_path=local_address,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_unix_datagram_endpoint.assert_awaited_once_with(
            remote_address,
            local_path=local_address,
        )
        mock_datagram_endpoint_cls.assert_called_once_with(mock_datagram_transport, mock_datagram_protocol)
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getsockname(),
        ]
        assert isinstance(client.socket, SocketProxy)

    @pytest.mark.parametrize("global_remote_address", ["/path/to/sock"], indirect=True)
    @pytest.mark.parametrize("global_local_address", ["/path/to/local_sock"], indirect=True)
    async def test____dunder_init____with_remote_address____with_path_like_object(
        self,
        async_finalizer: AsyncFinalizer,
        local_address: str,
        remote_address: str,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            pathlib.Path(remote_address),
            mock_datagram_protocol,
            mock_backend,
            local_path=pathlib.Path(local_address),
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_unix_datagram_endpoint.assert_awaited_once_with(
            remote_address,
            local_path=local_address,
        )

    async def test____dunder_init____with_remote_address____with_UnixSocketAddress_object(
        self,
        async_finalizer: AsyncFinalizer,
        local_address: str | bytes,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            UnixSocketAddress.from_raw(remote_address),
            mock_datagram_protocol,
            mock_backend,
            local_path=UnixSocketAddress.from_raw(local_address),
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_unix_datagram_endpoint.assert_awaited_once_with(
            remote_address,
            local_path=local_address,
        )

    async def test____dunder_init____with_remote_address____no_local_address____autobind_supported(
        self,
        async_finalizer: AsyncFinalizer,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = True

        # Act
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_unix_datagram_endpoint.assert_awaited_once_with(
            remote_address,
            local_path="",
        )

    async def test____dunder_init____with_remote_address____no_local_address____autobind_not_supported(
        self,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = False

        # Act & Assert
        with pytest.raises(
            ValueError,
            match=r"^local_path parameter is required on this platform and cannot be an empty string\.",
        ) as exc_info:
            _ = AsyncUnixDatagramClient(
                remote_address,
                mock_datagram_protocol,
                mock_backend,
            )
        assert exc_info.value.__notes__ == ["Automatic socket bind is not supported."]
        mock_backend.create_unix_datagram_endpoint.assert_not_awaited()

    async def test____dunder_init____with_remote_address____explicit_autobind_local_address____autobind_supported(
        self,
        async_finalizer: AsyncFinalizer,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = True

        # Act
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
            local_path="",
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_unix_datagram_endpoint.assert_awaited_once_with(
            remote_address,
            local_path="",
        )

    async def test____dunder_init____with_remote_address____explicit_autobind_local_address____autobind_not_supported(
        self,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_platform_supports_automatic_socket_bind: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_platform_supports_automatic_socket_bind.side_effect = None
        mock_platform_supports_automatic_socket_bind.return_value = False

        # Act & Assert
        with pytest.raises(
            ValueError,
            match=r"^local_path parameter is required on this platform and cannot be an empty string\.",
        ) as exc_info:
            _ = AsyncUnixDatagramClient(
                remote_address,
                mock_datagram_protocol,
                mock_backend,
                local_path="",
            )
        assert exc_info.value.__notes__ == ["Automatic socket bind is not supported."]
        mock_backend.create_unix_datagram_endpoint.assert_not_awaited()

    async def test____dunder_init____use_given_socket(
        self,
        async_finalizer: AsyncFinalizer,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_datagram_endpoint_cls: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            mock_unix_datagram_socket,
            mock_datagram_protocol,
            mock_backend,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_unix_datagram_socket.bind.assert_not_called()
        mock_backend.wrap_connected_datagram_socket.assert_awaited_once_with(mock_unix_datagram_socket)
        mock_datagram_endpoint_cls.assert_called_once_with(mock_datagram_transport, mock_datagram_protocol)
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.getsockname(),
        ]
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        self.configure_socket_mock_to_raise_ENOTCONN(mock_unix_datagram_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = AsyncUnixDatagramClient(mock_unix_datagram_socket, mock_datagram_protocol, mock_backend)

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.close(),
        ]

    @pytest.mark.parametrize("global_local_address", [""], indirect=True)
    async def test____dunder_init____use_given_socket____error_no_local_address(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^AsyncUnixDatagramClient requires the socket to be named.$"):
            _ = AsyncUnixDatagramClient(mock_unix_datagram_socket, mock_datagram_protocol, mock_backend)

        # Assert
        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.close(),
        ]

    @pytest.mark.parametrize("socket_family", list(unsupported_families(UNIX_FAMILIES)), indirect=True)
    async def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = AsyncUnixDatagramClient(
                mock_unix_datagram_socket,
                mock_datagram_protocol,
                mock_backend,
            )

        assert mock_unix_datagram_socket.mock_calls == [
            mocker.call.close(),
        ]

    async def test____dunder_init____invalid_first_argument____invalid_object(
        self,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_object = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^expected str, bytes or os.PathLike object, not .+$"):
            _ = AsyncUnixDatagramClient(
                invalid_object,
                protocol=mock_datagram_protocol,
                backend=mock_backend,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____protocol____invalid_value(
        self,
        use_socket: bool,
        remote_address: str | bytes,
        mock_unix_datagram_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            if use_socket:
                _ = AsyncUnixDatagramClient(
                    mock_unix_datagram_socket,
                    protocol=mock_stream_protocol,
                    backend=mock_backend,
                )
            else:
                _ = AsyncUnixDatagramClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    backend=mock_backend,
                )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____backend____invalid_value(
        self,
        request: pytest.FixtureRequest,
        use_socket: bool,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            if use_socket:
                _ = AsyncUnixDatagramClient(
                    request.getfixturevalue("mock_unix_datagram_socket"),
                    mock_datagram_protocol,
                    invalid_backend,
                )
            else:
                _ = AsyncUnixDatagramClient(
                    request.getfixturevalue("remote_address"),
                    mock_datagram_protocol,
                    invalid_backend,
                )

    async def test____dunder_init____local_path____invalid_object(
        self,
        remote_address: str | bytes,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_object = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^expected str, bytes or os.PathLike object, not .+$"):
            _ = AsyncUnixDatagramClient(
                remote_address,
                protocol=mock_datagram_protocol,
                backend=mock_backend,
                local_path=invalid_object,
            )

    async def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_endpoint: MagicMock,
        mock_datagram_protocol: MagicMock,
        local_address: str | bytes,
        remote_address: str | bytes,
        mock_backend: MagicMock,
    ) -> None:
        client: AsyncUnixDatagramClient[Any, Any] = AsyncUnixDatagramClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
            local_path=local_address,
        )
        await client.wait_connected()

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed client .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del client

        mock_datagram_endpoint.aclose.assert_not_called()

    async def test____is_closing____connection_not_performed_yet(
        self,
        client_not_connected: AsyncUnixDatagramClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert not client_not_connected.is_closing()
        await client_not_connected.wait_connected()
        assert not client_not_connected.is_closing()

    async def test____aclose____await_socket_close(
        self,
        client_connected: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert client_connected.is_closing()
        mock_datagram_endpoint.aclose.assert_awaited_once_with()

    async def test____aclose____connection_not_performed_yet(
        self,
        client_not_connected: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        assert not client_not_connected.is_closing()

        # Act
        await client_not_connected.aclose()

        # Assert
        assert client_not_connected.is_closing()
        mock_datagram_endpoint.aclose.assert_not_awaited()

    async def test____aclose____already_closed(
        self,
        client_connected: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        await client_connected.aclose()
        assert client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert mock_datagram_endpoint.aclose.await_count == 2

    async def test____aclose____cancelled(
        self,
        client_connected: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
        fake_cancellation_cls: type[BaseException],
    ) -> None:
        # Arrange
        old_side_effect = mock_datagram_endpoint.aclose.side_effect
        mock_datagram_endpoint.aclose.side_effect = fake_cancellation_cls

        # Act
        try:
            with pytest.raises(fake_cancellation_cls):
                await client_connected.aclose()
        finally:
            mock_datagram_endpoint.aclose.side_effect = old_side_effect

        # Assert
        mock_datagram_endpoint.aclose.assert_awaited_once_with()

    async def test____get_local_name____return_saved_address(
        self,
        local_address: str | bytes,
        client_connected: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getsockname.reset_mock()

        # Act
        address = client_connected.get_local_name()

        # Assert
        assert isinstance(address, UnixSocketAddress)
        mock_unix_datagram_socket.getsockname.assert_called_once()
        assert address.as_raw() == local_address

    async def test____get_local_name____error_connection_not_performed(
        self,
        client_not_connected: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getsockname.reset_mock()

        # Act
        with pytest.raises(OSError) as exc_info:
            client_not_connected.get_local_name()

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN
        mock_unix_datagram_socket.getsockname.assert_not_called()

    async def test____get_local_name____client_closed(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()
        mock_unix_datagram_socket.getsockname.reset_mock()

        # Act
        with pytest.raises(ClientClosedError):
            client_connected_or_not.get_local_name()

        # Assert
        mock_unix_datagram_socket.getsockname.assert_not_called()

    async def test____get_peer_name_____return_saved_address(
        self,
        remote_address: str | bytes,
        client_connected: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getpeername.reset_mock()

        # Act
        address = client_connected.get_peer_name()

        # Assert
        assert isinstance(address, UnixSocketAddress)
        mock_unix_datagram_socket.getpeername.assert_called_once()
        assert address.as_raw() == remote_address

    async def test____get_peer_name____error_connection_not_performed(
        self,
        client_not_connected: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getpeername.reset_mock()

        # Act
        with pytest.raises(OSError) as exc_info:
            client_not_connected.get_peer_name()

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN
        mock_unix_datagram_socket.getpeername.assert_not_called()

    async def test____get_peer_name____client_closed(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()
        mock_unix_datagram_socket.getpeername.reset_mock()

        # Act
        with pytest.raises(ClientClosedError):
            client_connected_or_not.get_peer_name()

        # Assert
        mock_unix_datagram_socket.getpeername.assert_not_called()

    async def test____get_backend____returns_linked_instance(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_connected_or_not.backend() is mock_backend

    async def test____socket_property____cached_attribute(
        self,
        client_connected: AsyncUnixDatagramClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_connected.socket is client_connected.socket

    async def test____socket_property____AttributeError(
        self,
        client_not_connected: AsyncUnixDatagramClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(AttributeError):
            _ = client_not_connected.socket

    async def test____send_packet____send_bytes_to_socket(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_unix_datagram_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    async def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_unix_datagram_socket.getsockopt.return_value = errno.ECONNREFUSED

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == errno.ECONNREFUSED
        mock_datagram_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_unix_datagram_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    async def test____send_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_endpoint.send_packet.assert_not_awaited()
        mock_unix_datagram_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____send_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_endpoint.send_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client_connected_or_not.is_closing()
        mock_datagram_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)
        mock_datagram_endpoint.aclose.assert_not_awaited()
        mock_unix_datagram_socket.getsockopt.assert_not_called()

    async def test____recv_packet____receive_bytes_from_socket(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_endpoint.recv_packet.side_effect = [mocker.sentinel.packet]

        # Act
        packet = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_endpoint.recv_packet.assert_awaited_once_with()
        assert packet is mocker.sentinel.packet

    async def test____recv_packet____protocol_parse_error(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        expected_error = DatagramProtocolParseError(DeserializeError("Sorry"))
        mock_datagram_endpoint.recv_packet.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = await client_connected_or_not.recv_packet()

        # Assert
        assert exc_info.value is expected_error
        mock_datagram_endpoint.recv_packet.assert_awaited_once_with()

    async def test____recv_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_endpoint.recv_packet.assert_not_awaited()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____recv_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_endpoint.recv_packet.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = await client_connected_or_not.recv_packet()

        # Assert
        assert exc_info.value.errno == closed_socket_errno
        assert exc_info.value.__notes__ == ["The socket file descriptor was closed unexpectedly."]
        assert not client_connected_or_not.is_closing()
        mock_datagram_endpoint.recv_packet.assert_awaited_once()
        mock_datagram_endpoint.aclose.assert_not_awaited()

    async def test____special_case____separate_send_and_receive_locks(
        self,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        async def recv_side_effect() -> bytes:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)
            raise ConnectionAbortedError

        mock_datagram_endpoint.recv_packet.side_effect = recv_side_effect

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_endpoint.send_packet.assert_awaited_once_with(mocker.sentinel.packet)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____special_case____close_during_recv_call(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
    ) -> None:
        # Arrange
        async def recv_side_effect() -> bytes:
            await client_connected_or_not.aclose()
            raise OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        mock_datagram_endpoint.recv_packet.side_effect = recv_side_effect

        # Act & Assert
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

    async def test____special_case____close_cancelled_during_lock_acquisition(
        self,
        client_connected: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client_connected.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client_connected.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_datagram_endpoint.aclose.assert_awaited_once_with()

    async def test____special_case____close_cancelled_during_lock_acquisition____endpoint_is_already_closing(
        self,
        client_connected: AsyncUnixDatagramClient[Any, Any],
        mock_datagram_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await mock_datagram_endpoint.aclose()
        assert mock_datagram_endpoint.is_closing()
        mock_datagram_endpoint.reset_mock()
        ## We simulate another task which takes the lock and aclose() has been cancelled.
        CancelledError = client_connected.backend().get_cancelled_exc_class()
        mock_lock_acquire = mocker.patch.object(AsyncDummyLock, "acquire", side_effect=CancelledError)

        # Act
        with pytest.raises(CancelledError):
            await client_connected.aclose()
        mocker.stop(mock_lock_acquire)

        # Assert
        mock_datagram_endpoint.aclose.assert_not_awaited()
