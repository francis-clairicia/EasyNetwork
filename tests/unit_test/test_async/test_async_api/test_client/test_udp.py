# -*- coding: Utf-8 -*-

from __future__ import annotations

from concurrent.futures import Future
from socket import AF_INET6
from typing import TYPE_CHECKING, Any, cast

from easynetwork.api_async.client.udp import AsyncUDPNetworkClient, AsyncUDPNetworkEndpoint
from easynetwork.exceptions import ClientClosedError
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock, AsyncMock

    from pytest_mock import MockerFixture

from .base import BaseTestClient


def _get_all_socket_families() -> list[str]:
    import socket

    return [v for v in dir(socket) if v.startswith("AF_")]


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

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_close_future(mocker: MockerFixture) -> Future[None]:
        fut: Future[None] = Future()
        mocker.patch("concurrent.futures.Future", return_value=fut)
        return fut

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
        cls.set_local_address_to_socket_mock(mock_datagram_socket_adapter, socket_family, global_local_address)
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
                cls.set_remote_address_to_socket_mock(mock_datagram_socket_adapter, socket_family, global_remote_address)
                return global_remote_address
            case False:
                mock_datagram_socket_adapter.getpeername.return_value = None
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

        mock_datagram_socket_adapter.proxy.return_value = mock_udp_socket

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
    def client(mock_datagram_socket_adapter: MagicMock, mock_datagram_protocol: MagicMock) -> AsyncUDPNetworkEndpoint[Any, Any]:
        return AsyncUDPNetworkEndpoint(mock_datagram_socket_adapter, mock_datagram_protocol)

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

    async def test____create____with_remote_address(
        self,
        remote_address: tuple[str, int] | None,
        socket_family: int,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkEndpoint[Any, Any] = await AsyncUDPNetworkEndpoint.create(
            mock_datagram_protocol,
            family=socket_family,
            remote_address=remote_address,
            local_address=mocker.sentinel.source_address,
        )

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            family=socket_family,
            remote_address=remote_address,
            local_address=mocker.sentinel.source_address,
            reuse_port=False,
        )
        mock_datagram_socket_adapter.proxy.assert_called_once_with()
        mock_datagram_socket_adapter.getsockname.assert_called_once_with()
        mock_datagram_socket_adapter.getpeername.assert_called_once_with()
        assert client.socket is mock_udp_socket

    async def test____create____force_local_address(
        self,
        remote_address: tuple[str, int] | None,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkEndpoint.create(
            mock_datagram_protocol,
            remote_address=remote_address,
            local_address=None,
        )

        # Assert
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            remote_address=remote_address,
            local_address=("", 0),
            family=mocker.ANY,  # Not tested here
            reuse_port=mocker.ANY,  # Not tested here
        )

    async def test____create____backend____from_string(
        self,
        remote_address: tuple[str, int] | None,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkEndpoint.create(
            mock_datagram_protocol,
            remote_address=remote_address,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____create____backend____explicit_argument(
        self,
        remote_address: tuple[str, int] | None,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkEndpoint.create(
            mock_datagram_protocol,
            remote_address=remote_address,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    async def test____from_socket____use_given_socket(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkEndpoint[Any, Any] = await AsyncUDPNetworkEndpoint.from_socket(
            mock_udp_socket,
            mock_datagram_protocol,
        )

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_backend.wrap_udp_socket.assert_awaited_once_with(mock_udp_socket)
        mock_datagram_socket_adapter.proxy.assert_called_once_with()
        mock_datagram_socket_adapter.getsockname.assert_called_once_with()
        mock_datagram_socket_adapter.getpeername.assert_called_once_with()
        assert client.socket is mock_udp_socket

    async def test____from_socket____force_local_address(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.return_value = ("0.0.0.0", 0)

        # Act
        await AsyncUDPNetworkEndpoint.from_socket(
            mock_udp_socket,
            mock_datagram_protocol,
        )

        # Assert
        mock_udp_socket.bind.assert_called_once_with(("", 0))

    async def test____from_socket____backend____from_string(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkEndpoint.from_socket(
            mock_udp_socket,
            protocol=mock_datagram_protocol,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____from_socket____backend____explicit_argument(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkEndpoint.from_socket(
            mock_udp_socket,
            protocol=mock_datagram_protocol,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    async def test____dunder_init____error_no_local_address(
        self,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.getsockname.return_value = ("0.0.0.0", 0)

        # Act & Assert
        with pytest.raises(OSError, match=r"^.+ is not bound to a local address$"):
            _ = AsyncUDPNetworkEndpoint(
                mock_datagram_socket_adapter,
                mock_datagram_protocol,
            )

    async def test____context____close_endpoint_at_end(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_close = cast("AsyncMock", mocker.patch.object(AsyncUDPNetworkEndpoint, "close"))

        # Act
        async with client:
            mock_close.assert_not_awaited()

        # Assert
        mock_close.assert_awaited_once_with()

    async def test____close____await_socket_close(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_close_future: Future[None],
    ) -> None:
        # Arrange
        assert not client.is_closing()
        assert not mock_close_future.done()
        assert not mock_close_future.running()

        # Act
        await client.close()

        # Assert
        assert client.is_closing()
        mock_datagram_socket_adapter.close.assert_awaited_once_with()
        assert mock_close_future.done() and mock_close_future.result() is None

    async def test____close____await_socket_close____error_occurred(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_close_future: Future[None],
    ) -> None:
        # Arrange
        error = OSError("Bad file descriptor")
        mock_datagram_socket_adapter.close.side_effect = error
        assert not client.is_closing()
        assert not mock_close_future.done()
        assert not mock_close_future.running()

        # Act
        with pytest.raises(OSError) as exc_info:
            await client.close()

        # Assert
        assert client.is_closing()
        assert exc_info.value is error
        mock_datagram_socket_adapter.close.assert_awaited_once_with()
        assert mock_close_future.done() and mock_close_future.exception() is error

    async def test____close____await_socket_close____hide_connection_error(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_close_future: Future[None],
    ) -> None:
        # Arrange
        error = ConnectionAbortedError()
        mock_datagram_socket_adapter.close.side_effect = error
        assert not client.is_closing()
        assert not mock_close_future.done()
        assert not mock_close_future.running()

        # Act
        await client.close()

        # Assert
        assert client.is_closing()
        mock_datagram_socket_adapter.close.assert_awaited_once_with()
        assert mock_close_future.done() and mock_close_future.exception() is None

    async def test____close____action_in_progress(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_close_future: Future[None],
    ) -> None:
        # Arrange
        mock_close_future.set_running_or_notify_cancel()
        mock_backend.wait_future.return_value = None

        # Act
        await client.close()

        # Assert
        mock_backend.wait_future.assert_awaited_once_with(mock_close_future)
        mock_datagram_socket_adapter.close.assert_not_awaited()

    async def test____close____already_closed(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_close_future: Future[None],
    ) -> None:
        # Arrange
        mock_close_future.set_result(None)

        # Act
        await client.close()

        # Assert
        mock_backend.wait_future.assert_not_awaited()
        mock_datagram_socket_adapter.close.assert_not_awaited()

    async def test____abort____brute_force_shutdown(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await client.abort()

        # Assert
        mock_datagram_socket_adapter.abort.assert_awaited_once_with()
        mock_datagram_socket_adapter.close.assert_not_awaited()
        assert client.is_closing()

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    async def test____get_local_address____return_saved_address(
        self,
        client_closed: bool,
        socket_family: int,
        local_address: tuple[str, int],
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.getsockname.reset_mock()
        if client_closed:
            await client.close()
            assert client.is_closing()

        # Act
        address = client.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_datagram_socket_adapter.getsockname.assert_not_called()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    async def test____get_remote_address____return_saved_address(
        self,
        client_closed: bool,
        remote_address: tuple[str, int] | None,
        socket_family: int,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        mock_datagram_socket_adapter.getpeername.assert_called_once()
        if client_closed:
            await client.close()
            assert client.is_closing()

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
        mock_datagram_socket_adapter.getpeername.assert_called_once()

    async def test____fileno____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
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

    async def test____fileno____closed_client(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        await client.close()
        assert client.is_closing()

        # Act
        fd = client.fileno()

        # Assert
        mock_udp_socket.fileno.assert_not_called()
        assert fd == -1

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____without_remote____default(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        target_address: tuple[str, int] = ("remote_address", 5000)

        # Act
        await client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_awaited_once_with(b"packet", target_address)
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [False], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____without_remote____None_address_error(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^Invalid address: must not be None$"):
            await client.send_packet_to(mocker.sentinel.packet, None)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("target_address", [None, ("remote_address", 5000)], ids=lambda p: f"target_address=={p}")
    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____with_remote____default(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        target_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        # Act
        await client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_awaited_once_with(b"packet", None)
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.parametrize("remote_address", [True], indirect=True)
    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____send_bytes_to_socket____with_remote____invalid_target_address(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        target_address: tuple[str, int] = ("address_other_than_remote", 9999)

        # Act
        with pytest.raises(ValueError, match=r"^Invalid address: must be None or .+$"):
            await client.send_packet_to(mocker.sentinel.packet, target_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____raise_error_saved_in_SO_ERROR_option(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
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
            await client.send_packet_to(mocker.sentinel.packet, global_remote_address)

        # Assert
        assert exc_info.value.errno == ECONNREFUSED
        mock_datagram_socket_adapter.sendto.assert_awaited_once()
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_udp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____closed_client_error(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        remote_address: tuple[str, int] | None,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client.close()
        assert client.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client.send_packet_to(mocker.sentinel.packet, remote_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____send_packet_to____unexpected_socket_close(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
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
            await client.send_packet_to(mocker.sentinel.packet, remote_address)

        # Assert
        mock_datagram_socket_adapter.sendto.assert_not_awaited()
        mock_datagram_protocol.make_datagram.assert_not_called()
        mock_udp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____receive_bytes_from_socket(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recvfrom.side_effect = [(b"packet", sender_address)]

        # Act
        packet, sender = await client.recv_packet_from()

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert packet is mocker.sentinel.packet
        assert (sender.host, sender.port) == sender_address

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____protocol_parse_error(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
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
            _ = await client.recv_packet_from()
        exception = exc_info.value

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____closed_client_error(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        await client.close()
        assert client.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client.recv_packet_from()

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_not_awaited()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____recv_packet_from____unexpected_socket_close(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet_from()

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_not_awaited()
        mock_datagram_protocol.build_packet_from_datagram.assert_not_called()

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____iter_received_packets_from____yields_available_packets_until_error(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
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
        packets = [(p, (s.host, s.port)) async for p, s in client.iter_received_packets_from()]

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
        client: AsyncUDPNetworkEndpoint[Any, Any],
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
            _ = await anext(client.iter_received_packets_from())
        exception = exc_info.value

        # Assert
        mock_datagram_socket_adapter.recvfrom.assert_awaited_once_with()
        mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_protocol_mock")
    async def test____iter_received_packets_from____closed_client_during_iteration(
        self,
        client: AsyncUDPNetworkEndpoint[Any, Any],
        sender_address: tuple[str, int],
        mock_datagram_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket_adapter.recvfrom.side_effect = [(b"packet_1", sender_address)]

        # Act & Assert
        iterator = client.iter_received_packets_from()
        packet_1 = await anext(iterator)
        assert packet_1[0] is mocker.sentinel.packet_1
        await client.close()
        assert client.is_closing()
        with pytest.raises(StopAsyncIteration):
            _ = await anext(iterator)


@pytest.mark.asyncio
class TestAsyncUDPNetworkClient:
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
    def client(mock_datagram_socket_adapter: MagicMock, mock_datagram_protocol: MagicMock) -> AsyncUDPNetworkClient[Any, Any]:
        return AsyncUDPNetworkClient(mock_datagram_socket_adapter, mock_datagram_protocol)

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_udp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
    ) -> None:
        mock_udp_socket.getsockname.return_value = ("local_address", 12345)
        del mock_udp_socket.getpeername

        mock_backend.create_udp_endpoint.return_value = mock_datagram_socket_adapter
        mock_backend.wrap_udp_socket.return_value = mock_datagram_socket_adapter

        mock_datagram_socket_adapter.proxy.return_value = mock_udp_socket

    async def test____create____with_remote_address(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint_cls: MagicMock,
        mock_udp_endpoint: MagicMock,
        mock_new_backend: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = await AsyncUDPNetworkClient.create(
            remote_address,
            mock_datagram_protocol,
            family=socket_family,
            local_address=mocker.sentinel.source_address,
        )

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_udp_endpoint_cls.assert_called_once_with(mock_datagram_socket_adapter, mock_datagram_protocol)
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            family=socket_family,
            remote_address=remote_address,
            local_address=mocker.sentinel.source_address,
            reuse_port=False,
        )
        mock_udp_endpoint.get_remote_address.assert_called_once_with()
        assert client.socket is mock_udp_socket

    async def test____create____force_local_address(
        self,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkClient.create(
            remote_address,
            mock_datagram_protocol,
            local_address=None,
        )

        # Assert
        mock_backend.create_udp_endpoint.assert_awaited_once_with(
            remote_address=remote_address,
            local_address=("", 0),
            family=mocker.ANY,  # Not tested here
            reuse_port=mocker.ANY,  # Not tested here
        )

    async def test____create____backend____from_string(
        self,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkClient.create(
            remote_address,
            protocol=mock_datagram_protocol,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____create____backend____explicit_argument(
        self,
        remote_address: tuple[str, int],
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkClient.create(
            remote_address,
            protocol=mock_datagram_protocol,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    async def test____from_socket____use_given_socket(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint_cls: MagicMock,
        mock_udp_endpoint: MagicMock,
        mock_new_backend: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncUDPNetworkClient[Any, Any] = await AsyncUDPNetworkClient.from_socket(
            mock_udp_socket,
            mock_datagram_protocol,
        )

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_udp_endpoint_cls.assert_called_once_with(mock_datagram_socket_adapter, mock_datagram_protocol)
        mock_backend.wrap_udp_socket.assert_awaited_once_with(mock_udp_socket)
        mock_udp_endpoint.get_remote_address.assert_called_once_with()
        assert client.socket is mock_udp_socket

    async def test____from_socket____force_local_address(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_socket.getsockname.return_value = ("0.0.0.0", 0)

        # Act
        await AsyncUDPNetworkClient.from_socket(
            mock_udp_socket,
            mock_datagram_protocol,
        )

        # Assert
        mock_udp_socket.bind.assert_called_once_with(("", 0))

    async def test____from_socket____backend____from_string(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkClient.from_socket(
            mock_udp_socket,
            protocol=mock_datagram_protocol,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____from_socket____backend____explicit_argument(
        self,
        mock_udp_socket: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncUDPNetworkClient.from_socket(
            mock_udp_socket,
            protocol=mock_datagram_protocol,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    async def test____dunder_init____error_no_remote_address(
        self,
        mock_datagram_socket_adapter: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_endpoint.get_remote_address.return_value = None

        # Act & Assert
        with pytest.raises(OSError, match=r"^No remote address configured$"):
            _ = AsyncUDPNetworkClient(
                mock_datagram_socket_adapter,
                mock_datagram_protocol,
            )

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

    async def test____close____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_endpoint.close.return_value = None

        # Act
        await client.close()

        # Assert
        mock_udp_endpoint.close.assert_awaited_once_with()

    async def test___abort____default(
        self,
        client: AsyncUDPNetworkClient[Any, Any],
        mock_udp_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_udp_endpoint.abort.return_value = None

        # Act
        await client.abort()

        # Assert
        mock_udp_endpoint.abort.assert_awaited_once_with()

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
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        mock_udp_endpoint.get_remote_address.assert_called_once()

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
