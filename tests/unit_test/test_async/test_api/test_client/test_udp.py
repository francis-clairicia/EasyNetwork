from __future__ import annotations

import contextlib
import errno
import os
from collections.abc import AsyncIterator
from socket import AF_INET6, AF_UNSPEC, SO_ERROR, SOL_SOCKET
from typing import TYPE_CHECKING, Any

from easynetwork.clients.async_udp import AsyncUDPNetworkClient
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError, DeserializeError
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS
from easynetwork.lowlevel.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy, _get_socket_extra
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

    from .....pytest_plugins.async_finalizer import AsyncFinalizer

from ....base import UNSUPPORTED_FAMILIES, BaseTestWithDatagramProtocol
from .base import BaseTestClient


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning:easynetwork.lowlevel.api_async.endpoints.datagram")
class TestAsyncUDPNetworkClient(BaseTestClient, BaseTestWithDatagramProtocol):
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
    @classmethod
    def local_address(
        cls,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_local_address_to_socket_mock(mock_udp_socket, socket_family, global_local_address)
        return global_local_address

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
        mock_backend: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        mock_udp_socket.family = socket_family
        mock_udp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()
        del mock_udp_socket.send
        del mock_udp_socket.sendto
        del mock_udp_socket.recvfrom

        mock_backend.create_udp_endpoint.return_value = mock_datagram_socket_adapter
        mock_backend.wrap_connected_datagram_socket.return_value = mock_datagram_socket_adapter

        mock_datagram_socket_adapter.extra_attributes = _get_socket_extra(mock_udp_socket, wrap_in_proxy=False)
        mock_datagram_socket_adapter.extra.side_effect = TypedAttributeProvider.extra.__get__(mock_datagram_socket_adapter)

    @pytest_asyncio.fixture
    @staticmethod
    async def client_not_connected(
        mock_udp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncIterator[AsyncUDPNetworkClient[Any, Any]]:
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(mock_udp_socket, mock_datagram_protocol, mock_backend)
        assert not client.is_connected()
        async with contextlib.aclosing(client):
            yield client

    @pytest_asyncio.fixture
    @staticmethod
    async def client_connected(client_not_connected: AsyncUDPNetworkClient[Any, Any]) -> AsyncUDPNetworkClient[Any, Any]:
        await client_not_connected.wait_connected()
        assert client_not_connected.is_connected()
        return client_not_connected

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"client_connected=={boolean}")
    @staticmethod
    def client_connected_or_not(request: pytest.FixtureRequest) -> AsyncUDPNetworkClient[Any, Any]:
        client_to_use: str = {False: "client_not_connected", True: "client_connected"}[getattr(request, "param")]
        return request.getfixturevalue(client_to_use)

    async def test____dunder_init____with_remote_address(
        self,
        async_finalizer: AsyncFinalizer,
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
            local_address=mocker.sentinel.local_address,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            *remote_address,
            local_address=mocker.sentinel.local_address,
        )
        assert mock_udp_socket.mock_calls == [
            mocker.call.fileno(),
            mocker.call.getsockname(),
        ]
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____with_remote_address____socket_family(
        self,
        async_finalizer: AsyncFinalizer,
        remote_address: tuple[str, int],
        socket_family: int,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
            family=socket_family,
            local_address=mocker.sentinel.local_address,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            *remote_address,
            family=socket_family,
            local_address=mocker.sentinel.local_address,
        )

    async def test____dunder_init____with_remote_address____explicit_AF_UNSPEC(
        self,
        async_finalizer: AsyncFinalizer,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
            family=AF_UNSPEC,
            local_address=mocker.sentinel.local_address,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            *remote_address,
            family=AF_UNSPEC,
            local_address=mocker.sentinel.local_address,
        )

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
    async def test____dunder_init____with_remote_address____invalid_socket_family(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        mock_backend: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = AsyncUDPNetworkClient(
                remote_address,
                mock_datagram_protocol,
                mock_backend,
                family=socket_family,
                local_address=mocker.sentinel.local_address,
            )

    async def test____dunder_init____with_remote_address____force_local_address(
        self,
        async_finalizer: AsyncFinalizer,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
            local_address=None,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            *remote_address,
            local_address=("localhost", 0),
        )

    async def test____dunder_init____use_given_socket(
        self,
        async_finalizer: AsyncFinalizer,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            mock_udp_socket,
            mock_datagram_protocol,
            mock_backend,
        )
        async_finalizer.add_finalizer(client.aclose)
        await client.wait_connected()

        # Assert
        mock_udp_socket.bind.assert_not_called()
        mock_backend.wrap_connected_datagram_socket.assert_awaited_once_with(mock_udp_socket)
        assert mock_udp_socket.mock_calls == [
            mocker.call.getpeername(),
            mocker.call.getsockname(),
            mocker.call.fileno(),
            mocker.call.getsockname(),
        ]
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____use_given_socket____error_no_remote_address(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        self.configure_socket_mock_to_raise_ENOTCONN(mock_udp_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = AsyncUDPNetworkClient(mock_udp_socket, mock_datagram_protocol, mock_backend)

        # Assert
        assert exc_info.value.errno == errno.ENOTCONN

    async def test____dunder_init____use_given_socket____force_local_address(
        self,
        async_finalizer: AsyncFinalizer,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.return_value = ("0.0.0.0", 0)

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            mock_udp_socket,
            mock_datagram_protocol,
            mock_backend,
        )
        async_finalizer.add_finalizer(client.aclose)

        # Assert
        mock_udp_socket.bind.assert_called_once_with(("localhost", 0))

    @pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
    async def test____dunder_init____use_given_socket____invalid_socket_family(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
            _ = AsyncUDPNetworkClient(
                mock_udp_socket,
                mock_datagram_protocol,
                mock_backend,
            )

    async def test____dunder_init____invalid_first_argument____invalid_object(
        self,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_object = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = AsyncUDPNetworkClient(
                invalid_object,
                protocol=mock_datagram_protocol,
                backend=mock_backend,
            )

    async def test____dunder_init____invalid_first_argument____invalid_host_port_pair(
        self,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_host = mocker.NonCallableMagicMock(spec=object)
        invalid_port = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid arguments$"):
            _ = AsyncUDPNetworkClient(
                (invalid_host, invalid_port),
                protocol=mock_datagram_protocol,
                backend=mock_backend,
            )

    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____protocol____invalid_value(
        self,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            if use_socket:
                _ = AsyncUDPNetworkClient(
                    mock_udp_socket,
                    protocol=mock_stream_protocol,
                    backend=mock_backend,
                )
            else:
                _ = AsyncUDPNetworkClient(
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
                _ = AsyncUDPNetworkClient(
                    request.getfixturevalue("mock_tcp_socket"),
                    mock_datagram_protocol,
                    invalid_backend,
                )
            else:
                _ = AsyncUDPNetworkClient(
                    request.getfixturevalue("remote_address"),
                    mock_datagram_protocol,
                    invalid_backend,
                )

    async def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        remote_address: tuple[str, int],
        mock_backend: MagicMock,
    ) -> None:
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            mock_backend,
        )
        await client.wait_connected()

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed client .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del client

        mock_datagram_socket_adapter.aclose.assert_not_called()

    async def test____is_closing____connection_not_performed_yet(
        self,
        client_not_connected: AsyncUDPNetworkClient[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert not client_not_connected.is_closing()
        await client_not_connected.wait_connected()
        assert not client_not_connected.is_closing()

    async def test____aclose____await_socket_close(
        self,
        client_connected: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        assert not client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert client_connected.is_closing()
        mock_datagram_socket_adapter.aclose.assert_awaited_once_with()

    async def test____aclose____connection_not_performed_yet(
        self,
        client_not_connected: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        assert not client_not_connected.is_closing()

        # Act
        await client_not_connected.aclose()

        # Assert
        assert client_not_connected.is_closing()
        mock_datagram_socket_adapter.aclose.assert_not_awaited()

    async def test____aclose____already_closed(
        self,
        client_connected: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        await client_connected.aclose()
        assert client_connected.is_closing()

        # Act
        await client_connected.aclose()

        # Assert
        assert mock_datagram_socket_adapter.aclose.await_count == 2

    async def test____aclose____cancellation(
        self,
        client_connected: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        fake_cancellation_cls: type[BaseException],
    ) -> None:
        # Arrange
        old_side_effect = mock_datagram_socket_adapter.aclose.side_effect
        mock_datagram_socket_adapter.aclose.side_effect = fake_cancellation_cls

        # Act
        with pytest.raises(fake_cancellation_cls):
            await client_connected.aclose()
        mock_datagram_socket_adapter.aclose.side_effect = old_side_effect

        # Assert
        mock_datagram_socket_adapter.aclose.assert_awaited_once_with()

    async def test____get_local_address____return_saved_address(
        self,
        socket_family: int,
        local_address: tuple[str, int],
        client_connected: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.reset_mock()

        # Act
        address = client_connected.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_udp_socket.getsockname.assert_called_once()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    async def test____get_local_address____error_connection_not_performed(
        self,
        client_not_connected: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.reset_mock()

        # Act
        with pytest.raises(OSError):
            client_not_connected.get_local_address()

        # Assert
        mock_udp_socket.getsockname.assert_not_called()

    async def test____get_local_address____client_closed(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.reset_mock()
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            client_connected_or_not.get_local_address()

        # Assert
        mock_udp_socket.getsockname.assert_not_called()

    async def test____get_remote_address____return_saved_address(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        client_connected: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getpeername.reset_mock()

        # Act
        address = client_connected.get_remote_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        assert address.host == remote_address[0]
        assert address.port == remote_address[1]
        mock_udp_socket.getpeername.assert_called_once()

    async def test____get_remote_address____error_connection_not_performed(
        self,
        client_not_connected: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getpeername.reset_mock()

        # Act
        with pytest.raises(OSError):
            client_not_connected.get_remote_address()

        # Assert
        mock_udp_socket.getpeername.assert_not_called()

    async def test____get_remote_address____client_closed(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getpeername.reset_mock()
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            client_connected_or_not.get_remote_address()

        # Assert
        mock_udp_socket.getpeername.assert_not_called()

    async def test____get_backend____returns_linked_instance(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_connected_or_not.backend() is mock_backend

    async def test____send_packet____send_bytes_to_socket(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_socket_adapter.send.assert_awaited_once_with(b"packet")
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    async def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockopt.return_value = errno.ECONNREFUSED

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == errno.ECONNREFUSED
        mock_datagram_socket_adapter.send.assert_awaited_once()
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    async def test____send_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_socket_adapter.send.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    async def test____send_packet____unexpected_socket_close(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_socket_adapter.send.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____send_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.send.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            await client_connected_or_not.send_packet(mocker.sentinel.packet)

        # Assert
        mock_datagram_socket_adapter.send.assert_awaited_once()
        mock_datagram_protocol.make_datagram.assert_called_once()
        mock_udp_socket.getsockopt.assert_not_called()

    async def test____recv_packet____receive_bytes_from_socket(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recv.side_effect = [b"packet"]

        # Act
        packet = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_socket_adapter.recv.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet

    async def test____recv_packet____protocol_parse_error(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recv.side_effect = [b"packet"]
        expected_error = DatagramProtocolParseError(DeserializeError("Sorry"))
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_socket_adapter.recv.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")

    async def test____recv_packet____closed_client_error(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        await client_connected_or_not.aclose()
        assert client_connected_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_socket_adapter.recv.assert_not_awaited()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    async def test____recv_packet____unexpected_socket_close(
        self,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_socket_adapter.recv.assert_not_awaited()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____recv_packet____convert_closed_socket_error(
        self,
        closed_socket_errno: int,
        client_connected_or_not: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recv.side_effect = OSError(closed_socket_errno, os.strerror(closed_socket_errno))

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_connected_or_not.recv_packet()

        # Assert
        mock_datagram_socket_adapter.recv.assert_awaited_once()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()
