from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import ClientClosedError
from easynetwork.lowlevel._utils import Flag
from easynetwork.lowlevel.socket import SocketProxy, UnixSocketAddress, UNIXSocketAttribute
from easynetwork.servers.async_unix_datagram import AsyncUnixDatagramServer, _ClientAPI
from easynetwork.servers.handlers import UNIXClientAttribute

import pytest

from .....fixtures.socket import AF_UNIX_or_skip
from .....tools import PlatformMarkers
from ....base import BaseTestSocket
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
@PlatformMarkers.skipif_platform_win32
class TestAsyncUnixDatagramServer:
    @pytest.fixture
    @staticmethod
    def server(
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> AsyncUnixDatagramServer[Any, Any]:
        return AsyncUnixDatagramServer("/path/to/sock", mock_datagram_protocol, mock_datagram_request_handler, mock_backend)

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
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        _ = AsyncUnixDatagramServer(valid_path, mock_datagram_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____path____invalid_value____unknown_type(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_path = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^expected str, bytes or os.PathLike object"):
            _ = AsyncUnixDatagramServer(invalid_path, mock_datagram_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____path____invalid_value____null_bytes_in_path(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        invalid_path = "/path/with/\0/bytes"

        # Act & Assert
        with pytest.raises(ValueError, match=r"^paths must not contain interior null bytes$"):
            _ = AsyncUnixDatagramServer(invalid_path, mock_datagram_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____protocol____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncUnixDatagramServer("/path/to/sock", mock_stream_protocol, mock_datagram_request_handler, mock_backend)

    async def test____dunder_init____request_handler____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncDatagramRequestHandler object, got .*$"):
            _ = AsyncUnixDatagramServer("/path/to/sock", mock_datagram_protocol, mock_stream_request_handler, mock_backend)

    async def test____dunder_init____unnamed_address_behavior____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Invalid unnamed_addresses_behavior value, got 'unknown'$"):
            _ = AsyncUnixDatagramServer(
                "/path/to/sock",
                mock_datagram_protocol,
                mock_datagram_request_handler,
                mock_backend,
                unnamed_addresses_behavior="unknown",  # type: ignore[arg-type]
            )

    async def test____dunder_init____backend____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = AsyncUnixDatagramServer("/path/to/sock", mock_datagram_protocol, mock_datagram_request_handler, invalid_backend)

    async def test____get_backend____returns_linked_instance(
        self,
        server: AsyncUnixDatagramServer[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_backend


@pytest.mark.asyncio
@PlatformMarkers.skipif_platform_win32
class TestClientAPI(BaseTestSocket):
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
    @staticmethod
    def service_available() -> Flag:
        return Flag()

    @pytest.fixture
    @classmethod
    def mock_datagram_server(
        cls,
        local_address: str,
        mock_unix_datagram_socket: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        from easynetwork.lowlevel.api_async.servers.datagram import AsyncDatagramServer
        from easynetwork.lowlevel.socket import _get_socket_extra

        cls.set_local_address_to_socket_mock(mock_unix_datagram_socket, AF_UNIX_or_skip(), local_address)
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_unix_datagram_socket)
        mock_datagram_server = make_transport_mock(mocker=mocker, spec=AsyncDatagramServer, backend=mock_backend)
        mock_datagram_server.extra_attributes = {
            **_get_socket_extra(mock_unix_datagram_socket, wrap_in_proxy=False),
            # Used to ensure that AsyncDatagramServer specific attributes are *NOT* merged.
            mocker.sentinel.custom_attribute: lambda: mocker.sentinel.custom_value,
        }
        return mock_datagram_server

    @pytest.fixture
    @staticmethod
    def client(
        remote_address: str | bytes,
        service_available: Flag,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_server: MagicMock,
    ) -> _ClientAPI[Any]:
        from easynetwork.lowlevel.api_async.servers.datagram import DatagramClientContext

        service_available.set()
        client: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=UnixSocketAddress.from_raw(remote_address),
                server=mock_datagram_server,
            ),
            service_available,
        )
        mock_unix_datagram_socket.reset_mock()
        return client

    async def test____dunder_init____initialize_inner_client(
        self,
        local_address: str,
        remote_address: str | bytes,
        service_available: Flag,
        mock_unix_datagram_socket: MagicMock,
        mock_datagram_server: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.servers.datagram import DatagramClientContext

        service_available.set()

        # Act
        client: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=UnixSocketAddress.from_raw(remote_address),
                server=mock_datagram_server,
            ),
            service_available,
        )

        # Assert
        assert mock_unix_datagram_socket.setsockopt.mock_calls == []
        assert client.backend() is mock_backend
        assert isinstance(client.extra(UNIXClientAttribute.socket), SocketProxy)
        assert client.extra(UNIXClientAttribute.local_name).as_raw() == local_address
        assert client.extra(UNIXClientAttribute.peer_name).as_raw() == remote_address
        assert client.extra(UNIXSocketAttribute.family) == AF_UNIX_or_skip()
        assert client.extra(mocker.sentinel.custom_attribute, mocker.sentinel.lookup_failed) is mocker.sentinel.lookup_failed

    async def test____uniqueness____using_hash_and_eq(
        self,
        remote_address: str | bytes,
        service_available: Flag,
        mock_datagram_server: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.servers.datagram import DatagramClientContext

        service_available.set()
        client_1: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=UnixSocketAddress.from_raw(remote_address),
                server=mock_datagram_server,
            ),
            service_available,
        )
        client_2: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=UnixSocketAddress.from_raw(remote_address),
                server=mock_datagram_server,
            ),
            service_available,
        )
        client_3: _ClientAPI[Any] = _ClientAPI(
            DatagramClientContext(
                address=UnixSocketAddress.from_raw("/path/to/other.sock"),
                server=mock_datagram_server,
            ),
            service_available,
        )

        # Act & Assert
        assert hash(client_1) == hash(client_2)
        assert hash(client_1) != hash(client_3)
        assert hash(client_2) != hash(client_3)
        assert client_1 == client_2
        assert client_1 != client_3
        assert client_2 != client_3
        assert client_1 != object()
        assert client_2 != object()
        assert client_3 != object()

    async def test____send_packet____send_bytes_to_socket(
        self,
        remote_address: str | bytes,
        client: _ClientAPI[Any],
        mock_datagram_server: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_server.send_packet_to.assert_awaited_once_with(
            mocker.sentinel.packet,
            UnixSocketAddress.from_raw(remote_address),
        )

    @pytest.mark.parametrize("method", ["server_close", "service_shutdown"])
    async def test____send_packet____closed_client(
        self,
        method: Literal["server_close", "service_shutdown"],
        client: _ClientAPI[Any],
        mock_datagram_server: MagicMock,
        service_available: Flag,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match method:
            case "server_close":
                await mock_datagram_server.aclose()
            case "service_shutdown":
                service_available.clear()
        assert client.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_server.send_packet_to.assert_not_awaited()
