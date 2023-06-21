# -*- coding: utf-8 -*-

from __future__ import annotations

from socket import AF_INET6
from typing import TYPE_CHECKING, Any, cast

from easynetwork.api_async.client.udp import AsyncUDPNetworkClient, AsyncUDPNetworkEndpoint
from easynetwork.exceptions import ClientClosedError
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress, SocketProxy

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import MagicMock, AsyncMock

    from pytest_mock import MockerFixture

from .base import BaseTestClient


@pytest.fixture(autouse=True)
def mock_new_backend(mocker: MockerFixture, mock_backend: MagicMock) -> MagicMock:
    from easynetwork.api_async.backend.factory import AsyncBackendFactory

    return mocker.patch.object(AsyncBackendFactory, "new", return_value=mock_backend)


@pytest.mark.asyncio
class TestAsyncUDPNetworkEndpoint(BaseTestClient):
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
        mock_datagram_socket_adapter: MagicMock,
        mock_udp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_local_address_to_socket_mock(mock_udp_socket, socket_family, global_local_address)
        cls.set_local_address_to_async_socket_adapter_mock(
            mock_datagram_socket_adapter,
            socket_family,
            global_local_address,
        )
        return global_local_address

    @pytest.fixture(autouse=True, params=[False, True], ids=lambda p: f"remote_address=={p}")
    @classmethod
    def remote_address(
        cls,
        request: Any,
        mock_datagram_socket_adapter: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int] | None:
        match request.param:
            case True:
                cls.set_remote_address_to_async_socket_adapter_mock(
                    mock_datagram_socket_adapter,
                    socket_family,
                    global_remote_address,
                )
                return global_remote_address
            case False:
                mock_datagram_socket_adapter.get_remote_address.return_value = None
                return None
            case invalid:
                pytest.fail(f"Invalid fixture param: Got {invalid!r}")

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_udp_socket: MagicMock,
        socket_family: int,
        mock_backend: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        mock_udp_socket.family = socket_family
        mock_udp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet_to()
        del mock_udp_socket.getpeername
        del mock_udp_socket.send
        del mock_udp_socket.sendto
        del mock_udp_socket.recvfrom

        mock_backend.create_udp_endpoint.return_value = mock_datagram_socket_adapter
        mock_backend.wrap_udp_socket.return_value = mock_datagram_socket_adapter

        mock_datagram_socket_adapter.socket.return_value = mock_udp_socket

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

    @pytest.fixture
    @staticmethod
    def client_not_bound(
        mock_backend: MagicMock,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncUDPNetworkEndpoint[Any, Any]:
        client: AsyncUDPNetworkEndpoint[Any, Any] = AsyncUDPNetworkEndpoint(
            mock_datagram_protocol,
            socket=mock_udp_socket,
            backend=mock_backend,
        )
        assert not client.is_bound()
        return client

    @pytest_asyncio.fixture
    @staticmethod
    async def client_bound(client_not_bound: AsyncUDPNetworkEndpoint[Any, Any]) -> AsyncUDPNetworkEndpoint[Any, Any]:
        await client_not_bound.wait_bound()
        assert client_not_bound.is_bound()
        return client_not_bound

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"client_bound=={boolean}")
    @staticmethod
    def client_bound_or_not(request: pytest.FixtureRequest) -> AsyncUDPNetworkEndpoint[Any, Any]:
        client_to_use: str = {False: "client_not_bound", True: "client_bound"}[getattr(request, "param")]
        return request.getfixturevalue(client_to_use)

    @pytest.fixture
    @staticmethod
    def sender_address(request: Any, global_remote_address: tuple[str, int]) -> tuple[str, int]:
        param: Any = getattr(request, "param", "REMOTE")
        if param == "REMOTE":
            return global_remote_address
        host, port = param
        return host, port

    async def test____dunder_init____with_remote_address(
        self,
        remote_address: tuple[str, int] | None,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkEndpoint[Any, Any] = AsyncUDPNetworkEndpoint(
            mock_datagram_protocol,
            remote_address=remote_address,
            local_address=mocker.sentinel.local_address,
            reuse_port=mocker.sentinel.reuse_port,
        )
        await client.wait_bound()

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            remote_address=remote_address,
            local_address=mocker.sentinel.local_address,
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_datagram_socket_adapter.socket.assert_called_once_with()
        mock_datagram_socket_adapter.get_local_address.assert_called_once_with()
        mock_datagram_socket_adapter.get_remote_address.assert_called_once_with()
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____with_remote_address____force_local_address(
        self,
        remote_address: tuple[str, int] | None,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkEndpoint[Any, Any] = AsyncUDPNetworkEndpoint(
            mock_datagram_protocol,
            remote_address=remote_address,
            local_address=None,
        )
        await client.wait_bound()

        # Assert
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            remote_address=remote_address,
            local_address=(None, 0),
        )

    async def test____dunder_init____backend____from_string(
        self,
        remote_address: tuple[str, int] | None,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        _ = AsyncUDPNetworkEndpoint(
            mock_datagram_protocol,
            remote_address=remote_address,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____dunder_init____backend____explicit_argument(
        self,
        remote_address: tuple[str, int] | None,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        _ = AsyncUDPNetworkEndpoint(
            mock_datagram_protocol,
            remote_address=remote_address,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    async def test____dunder_init____use_given_socket(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkEndpoint[Any, Any] = AsyncUDPNetworkEndpoint(
            mock_datagram_protocol,
            socket=mock_udp_socket,
        )
        await client.wait_bound()

        # Assert
        mock_udp_socket.bind.assert_not_called()
        mock_new_backend.assert_called_once_with(None)
        mock_backend.wrap_udp_socket.assert_awaited_once_with(mock_udp_socket)
        mock_datagram_socket_adapter.socket.assert_called_once_with()
        mock_datagram_socket_adapter.get_local_address.assert_called_once_with()
        mock_datagram_socket_adapter.get_remote_address.assert_called_once_with()
        assert isinstance(client.socket, SocketProxy)

    async def test____dunder_init____use_given_socket____force_local_address(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.return_value = ("0.0.0.0", 0)

        # Act
        _ = AsyncUDPNetworkEndpoint(
            mock_datagram_protocol,
            socket=mock_udp_socket,
        )

        # Assert
        mock_udp_socket.bind.assert_called_once_with(("", 0))

    async def test____context____close_endpoint_at_end(
        self,
        client_not_bound: AsyncUDPNetworkEndpoint[Any, Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wait_bound = cast("AsyncMock", mocker.patch.object(AsyncUDPNetworkEndpoint, "wait_bound"))
        mock_close = cast("AsyncMock", mocker.patch.object(AsyncUDPNetworkEndpoint, "aclose"))

        # Act
        async with client_not_bound:
            mock_wait_bound.assert_awaited_once_with()
            mock_close.assert_not_awaited()

        # Assert
        mock_wait_bound.assert_awaited_once_with()
        mock_close.assert_awaited_once_with()

    async def test___is_closing___connection_not_performed_yet(
        self,
        client_not_bound: AsyncUDPNetworkEndpoint[Any, Any],
    ) -> None:
        # Arrange

        # Act & Assert
        assert not client_not_bound.is_closing()
        await client_not_bound.wait_bound()
        assert not client_not_bound.is_closing()

    async def test____aclose____await_socket_close(
        self,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        assert not client_bound.is_closing()

        # Act
        await client_bound.aclose()

        # Assert
        assert client_bound.is_closing()
        mock_datagram_socket_adapter.aclose.assert_awaited_once_with()

    async def test____aclose____connection_not_performed_yet(
        self,
        client_not_bound: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        assert not client_not_bound.is_closing()

        # Act
        await client_not_bound.aclose()

        # Assert
        assert client_not_bound.is_closing()
        mock_datagram_socket_adapter.aclose.assert_not_awaited()

    async def test____aclose____await_socket_close____error_occurred(
        self,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        error = OSError("Bad file descriptor")
        mock_datagram_socket_adapter.aclose.side_effect = error
        assert not client_bound.is_closing()

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_bound.aclose()

        # Assert
        assert client_bound.is_closing()
        assert exc_info.value is error
        mock_datagram_socket_adapter.aclose.assert_awaited_once_with()

    async def test____aclose____await_socket_close____hide_connection_error(
        self,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        error = ConnectionAbortedError()
        mock_datagram_socket_adapter.aclose.side_effect = error
        assert not client_bound.is_closing()

        # Act
        await client_bound.aclose()

        # Assert
        assert client_bound.is_closing()
        mock_datagram_socket_adapter.aclose.assert_awaited_once_with()

    async def test____aclose____already_closed(
        self,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        await client_bound.aclose()
        assert client_bound.is_closing()

        # Act
        await client_bound.aclose()

        # Assert
        mock_datagram_socket_adapter.aclose.assert_awaited_once_with()

    async def test____aclose____cancellation(
        self,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        fake_cancellation_cls: type[BaseException],
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.aclose.side_effect = fake_cancellation_cls

        # Act
        with pytest.raises(fake_cancellation_cls):
            await client_bound.aclose()

        # Assert
        mock_datagram_socket_adapter.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    async def test____get_local_address____return_saved_address(
        self,
        client_closed: bool,
        socket_family: int,
        local_address: tuple[str, int],
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.get_local_address.reset_mock()
        if client_closed:
            await client_bound.aclose()
            assert client_bound.is_closing()

        # Act
        address = client_bound.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_datagram_socket_adapter.get_local_address.assert_not_called()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    async def test____get_local_address____error_connection_not_performed(
        self,
        client_not_bound: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(OSError):
            client_not_bound.get_local_address()

        # Assert
        mock_datagram_socket_adapter.get_local_address.assert_not_called()

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    async def test____get_remote_address____return_saved_address(
        self,
        client_closed: bool,
        remote_address: tuple[str, int] | None,
        socket_family: int,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        mock_datagram_socket_adapter.get_remote_address.assert_called_once()
        if client_closed:
            await client_bound.aclose()
            assert client_bound.is_closing()

        # Act
        address = client_bound.get_remote_address()

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
        mock_datagram_socket_adapter.get_remote_address.assert_called_once()

    async def test____get_remote_address____error_connection_not_performed(
        self,
        client_not_bound: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(OSError):
            client_not_bound.get_remote_address()

        # Assert
        mock_datagram_socket_adapter.get_remote_address.assert_not_called()

    async def test____fileno____default(
        self,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_socket.fileno.return_value = mocker.sentinel.fileno

        # Act
        fd = client_bound.fileno()

        # Assert
        mock_udp_socket.fileno.assert_called_once_with()
        assert fd is mocker.sentinel.fileno

    async def test____fileno____connection_not_performed(
        self,
        client_not_bound: AsyncUDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        fd = client_not_bound.fileno()

        # Assert
        mock_udp_socket.fileno.assert_not_called()
        assert fd == -1

    async def test____fileno____closed_client(
        self,
        client_bound: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        await client_bound.aclose()
        assert client_bound.is_closing()

        # Act
        fd = client_bound.fileno()

        # Assert
        mock_udp_socket.fileno.assert_not_called()
        assert fd == -1

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____without_remote____default(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        target_address: tuple[str, int] = ("remote_address", 5000)

        # Act
        await client_bound_or_not.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_awaited_once_with(b"packet", target_address)
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____without_remote____None_address_error(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^Invalid address: must not be None$"):
            await client_bound_or_not.send_packet_to(mocker.sentinel.packet, None)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("target_address", [None, ("remote_address", 5000)], ids=lambda p: f"target_address=={p}")
    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____with_remote____default(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        target_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        # Act
        await client_bound_or_not.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_awaited_once_with(b"packet", None)
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____with_remote____invalid_target_address(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        target_address: tuple[str, int] = ("address_other_than_remote", 9999)

        # Act
        with pytest.raises(ValueError, match=r"^Invalid address: must be None or .+$"):
            await client_bound_or_not.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____raise_error_saved_in_SO_ERROR_option(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        global_remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from errno import ECONNREFUSED
        from socket import SO_ERROR, SOL_SOCKET

        mock_udp_socket.getsockopt.return_value = ECONNREFUSED

        # Act
        with pytest.raises(OSError) as exc_info:
            await client_bound_or_not.send_packet_to(mocker.sentinel.packet, global_remote_address)

        # Assert
        assert exc_info.value.errno == ECONNREFUSED
        mock_datagram_socket_adapter.sendto.assert_awaited_once()
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____closed_client_error(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        remote_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client_bound_or_not.aclose()
        assert client_bound_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client_bound_or_not.send_packet_to(mocker.sentinel.packet, remote_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____unexpected_socket_close(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        remote_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ConnectionAbortedError):
            await client_bound_or_not.send_packet_to(mocker.sentinel.packet, remote_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____receive_bytes_from_socket(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recvfrom.side_effect = [(b"packet", sender_address)]

        # Act
        packet, sender = await client_bound_or_not.recv_packet_from()

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet
        assert (sender.host, sender.port) == sender_address

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____protocol_parse_error(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import DatagramProtocolParseError

        mock_datagram_socket_adapter.recvfrom.side_effect = [(b"packet", sender_address)]
        expected_error = DatagramProtocolParseError("deserialization", "Sorry")
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = await client_bound_or_not.recv_packet_from()
        exception = exc_info.value

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____closed_client_error(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        await client_bound_or_not.aclose()
        assert client_bound_or_not.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client_bound_or_not.recv_packet_from()

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_not_awaited()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____unexpected_socket_close(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client_bound_or_not.recv_packet_from()

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_not_awaited()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____iter_received_packets_from____yields_available_packets_until_error(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recvfrom.side_effect = [
            (b"packet_1", sender_address),
            (b"packet_2", sender_address),
            OSError,
        ]

        # Act
        packets = [(p, (s.host, s.port)) async for p, s in client_bound_or_not.iter_received_packets_from()]

        # Assert
        assert mock_datagram_socket_adapter.recvfrom.await_args_list == [mocker.call() for _ in range(3)]
        assert mock_datagram_protocol.build_packet_from_datagram.mock_calls == [
            mocker.call(b"packet_1"),
            mocker.call(b"packet_2"),
        ]
        assert packets == [
            (mocker.sentinel.packet_1, sender_address),
            (mocker.sentinel.packet_2, sender_address),
        ]

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____iter_received_packets_from____protocol_parse_error(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import DatagramProtocolParseError

        mock_datagram_socket_adapter.recvfrom.side_effect = [(b"packet", sender_address)]
        expected_error = DatagramProtocolParseError("deserialization", "Sorry")
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            _ = await anext(client_bound_or_not.iter_received_packets_from())
        exception = exc_info.value

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____iter_received_packets_from____closed_client_during_iteration(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        mock_datagram_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recvfrom.side_effect = [(b"packet_1", sender_address)]

        # Act & Assert
        iterator = client_bound_or_not.iter_received_packets_from()
        packet_1 = await anext(iterator)
        assert packet_1[0] is mocker.sentinel.packet_1
        await client_bound_or_not.aclose()
        assert client_bound_or_not.is_closing()
        with pytest.raises(StopAsyncIteration):
            _ = await anext(iterator)

    async def test____get_backend____default(
        self,
        client_bound_or_not: AsyncUDPNetworkEndpoint[Any, Any],
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_bound_or_not.get_backend() is mock_backend


@pytest.mark.asyncio
class TestAsyncUDPNetworkClient(BaseTestClient):
    @pytest.fixture(scope="class", params=["AF_INET", "AF_INET6"])
    @staticmethod
    def socket_family(request: Any) -> Any:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture
    @staticmethod
    def remote_address() -> tuple[str, int]:
        return ("remote_address", 5000)

    @pytest.fixture
    @staticmethod
    def mock_udp_endpoint(mock_udp_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AsyncUDPNetworkEndpoint)
        mock.get_local_address.return_value = ("local_address", 12345)
        mock.get_remote_address.return_value = ("remote_address", 5000)
        mock.socket = mock_udp_socket
        return mock

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_udp_endpoint_cls(mocker: MockerFixture, mock_udp_endpoint: MagicMock) -> MagicMock:
        return mocker.patch(f"{AsyncUDPNetworkEndpoint.__module__}.AsyncUDPNetworkEndpoint", return_value=mock_udp_endpoint)

    @pytest.fixture
    @staticmethod
    def client(
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncUDPNetworkClient[Any, Any]:
        return AsyncUDPNetworkClient(mock_udp_socket, mock_datagram_protocol)

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_udp_socket: MagicMock,
    ) -> None:
        mock_udp_socket.getsockname.return_value = ("local_address", 12345)
        mock_udp_socket.getpeername.return_value = ("remote_address", 5000)

    async def test____dunder_init____with_remote_address(
        self,
        remote_address: tuple[str, int],
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint_cls: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            remote_address,
            mock_datagram_protocol,
            local_address=mocker.sentinel.local_address,
            reuse_port=mocker.sentinel.reuse_port,
            backend=mock_backend,
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_udp_endpoint_cls.assert_called_once_with(
            protocol=mock_datagram_protocol,
            remote_address=remote_address,
            local_address=mocker.sentinel.local_address,
            reuse_port=mocker.sentinel.reuse_port,
            backend=mock_backend,
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )
        assert client.socket is mock_udp_socket

    async def test____dunder_init____use_given_socket(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint_cls: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = AsyncUDPNetworkClient(
            mock_udp_socket,
            mock_datagram_protocol,
            backend=mock_backend,
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_udp_endpoint_cls.assert_called_once_with(
            protocol=mock_datagram_protocol,
            socket=mock_udp_socket,
            backend=mock_backend,
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )
        assert client.socket is mock_udp_socket

    async def test____dunder_init____error_no_remote_address(
        self,
        mock_backend: MagicMock,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        self.configure_socket_mock_to_raise_ENOTCONN(mock_udp_socket)

        # Act & Assert
        with pytest.raises(OSError, match=r"^No remote address configured$"):
            _ = AsyncUDPNetworkClient(mock_udp_socket, mock_datagram_protocol, backend=mock_backend)

    async def test____is_closing____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.is_closing.return_value = mocker.sentinel.status

        # Act
        status = client.is_closing()

        # Assert
        mock_udp_endpoint.is_closing.assert_called_once_with()
        assert status is mocker.sentinel.status

    async def test____is_connected____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_endpoint.is_bound.return_value = True

        # Act
        status = client.is_connected()

        # Assert
        mock_udp_endpoint.is_bound.assert_called_once_with()
        assert status is True

    async def test____wait_connected____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_endpoint.wait_bound.return_value = None

        # Act
        await client.wait_connected()

        # Assert
        mock_udp_endpoint.wait_bound.assert_awaited_once_with()

    async def test____aclose____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_endpoint.aclose.return_value = None

        # Act
        await client.aclose()

        # Assert
        mock_udp_endpoint.aclose.assert_awaited_once_with()

    async def test____get_local_address____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        address = client.get_local_address()

        # Assert
        mock_udp_endpoint.get_local_address.assert_called_once_with()
        assert address == ("local_address", 12345)

    async def test____get_remote_address____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        address = client.get_remote_address()

        # Assert
        mock_udp_endpoint.get_remote_address.assert_called_once()
        assert address == ("remote_address", 5000)

    async def test____send_packet____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.send_packet_to.return_value = None

        # Act
        await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_udp_endpoint.send_packet_to.assert_awaited_once_with(mocker.sentinel.packet, None)

    async def test____recv_packet____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.recv_packet_from.return_value = (mocker.sentinel.packet, ("remote_address", 5000))

        # Act
        packet = await client.recv_packet()

        # Assert
        mock_udp_endpoint.recv_packet_from.assert_awaited_once_with()
        assert packet is mocker.sentinel.packet

    async def test____iter_received_packets____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        async def side_effect() -> Any:
            yield (mocker.sentinel.packet_1, ("remote_address", 5000))
            yield (mocker.sentinel.packet_2, ("remote_address", 5000))
            yield (mocker.sentinel.packet_3, ("remote_address", 5000))

        mock_udp_endpoint.iter_received_packets_from.side_effect = side_effect

        # Act
        packets = [p async for p in client.iter_received_packets()]

        # Assert
        mock_udp_endpoint.iter_received_packets_from.assert_called_once_with()
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2, mocker.sentinel.packet_3]

    async def test____fileno____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
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

    async def test____get_backend____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_udp_endpoint.get_backend.return_value = mocker.sentinel.backend

        # Act
        backend = client.get_backend()

        # Assert
        mock_udp_endpoint.get_backend.assert_called_once_with()
        assert backend is mocker.sentinel.backend
