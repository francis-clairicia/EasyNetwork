# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import AF_INET6, IPPROTO_TCP, TCP_NODELAY
from typing import TYPE_CHECKING, Any

from easynetwork.api_async.client.tcp import AsyncTCPNetworkClient
from easynetwork.exceptions import ClientClosedError
from easynetwork.tools.socket import MAX_STREAM_BUFSIZE, IPv4SocketAddress, IPv6SocketAddress, SocketProxy

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from .base import BaseTestClient


@pytest.mark.asyncio
class TestAsyncTCPNetworkClient(BaseTestClient):
    @pytest.fixture
    @staticmethod
    def mock_stream_data_producer() -> MagicMock:
        pytest.fail("StreamDataProducer is not used")

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
    def mock_stream_data_consumer_cls(mocker: MockerFixture, mock_stream_data_consumer: MagicMock) -> MagicMock:
        return mocker.patch(f"{AsyncTCPNetworkClient.__module__}.StreamDataConsumer", return_value=mock_stream_data_consumer)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_new_backend(mocker: MockerFixture, mock_backend: MagicMock) -> MagicMock:
        from easynetwork.api_async.backend.factory import AsyncBackendFactory

        return mocker.patch.object(AsyncBackendFactory, "new", return_value=mock_backend)

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        mock_stream_socket_adapter: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_local_address_to_socket_mock(
            mock_stream_socket_adapter,
            socket_family,
            global_local_address,
            "get_local_address",
        )
        return global_local_address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_stream_socket_adapter: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_remote_address_to_socket_mock(
            mock_stream_socket_adapter,
            socket_family,
            global_remote_address,
            "get_remote_address",
        )
        return global_remote_address

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        socket_family: int,
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        mock_tcp_socket.family = socket_family
        mock_tcp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()
        del mock_tcp_socket.getsockname
        del mock_tcp_socket.getpeername
        del mock_tcp_socket.sendall
        del mock_tcp_socket.recv

        mock_backend.create_tcp_connection.return_value = mock_stream_socket_adapter
        mock_backend.wrap_tcp_client_socket.return_value = mock_stream_socket_adapter

        mock_stream_socket_adapter.socket.return_value = mock_tcp_socket

    @pytest.fixture  # DO NOT set autouse=True
    @staticmethod
    def setup_producer_mock(mock_stream_protocol: MagicMock) -> None:
        mock_stream_protocol.generate_chunks.side_effect = lambda packet: iter(
            [str(packet).encode("ascii").removeprefix(b"sentinel.") + b"\n"]
        )

    @pytest.fixture  # DO NOT set autouse=True
    @staticmethod
    def setup_consumer_mock(mock_stream_data_consumer: MagicMock, mocker: MockerFixture) -> None:
        bytes_buffer: bytes = b""

        sentinel = mocker.sentinel

        def feed_side_effect(chunk: bytes) -> None:
            nonlocal bytes_buffer
            bytes_buffer += chunk

        def next_side_effect() -> Any:
            nonlocal bytes_buffer
            data, separator, bytes_buffer = bytes_buffer.partition(b"\n")
            if not separator:
                assert not bytes_buffer
                bytes_buffer = data
                raise StopIteration
            return getattr(sentinel, data.decode("ascii"))

        mock_stream_data_consumer.feed.side_effect = feed_side_effect
        mock_stream_data_consumer.__iter__.side_effect = lambda: mock_stream_data_consumer
        mock_stream_data_consumer.__next__.side_effect = next_side_effect

    @pytest.fixture
    @staticmethod
    def client(
        mock_backend: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> AsyncTCPNetworkClient[Any, Any]:
        return AsyncTCPNetworkClient(mock_backend, mock_stream_socket_adapter, mock_stream_protocol, None)

    async def test____connect____connect_to_remote(
        self,
        remote_address: tuple[str, int],
        socket_family: int,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = await AsyncTCPNetworkClient.connect(
            remote_address,
            family=socket_family,
            protocol=mock_stream_protocol,
            local_address=mocker.sentinel.local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_backend.create_tcp_connection.assert_awaited_once_with(
            *remote_address,
            family=socket_family,
            local_address=mocker.sentinel.local_address,
            happy_eyeballs_delay=mocker.sentinel.happy_eyeballs_delay,
        )
        mock_stream_socket_adapter.socket.assert_called_once_with()
        mock_stream_socket_adapter.get_local_address.assert_called_once_with()
        mock_stream_socket_adapter.get_remote_address.assert_called_once_with()
        mock_tcp_socket.setsockopt.assert_called_once_with(IPPROTO_TCP, TCP_NODELAY, True)
        assert isinstance(client.socket, SocketProxy)

    async def test____connect____backend____from_string(
        self,
        remote_address: tuple[str, int],
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncTCPNetworkClient.connect(
            remote_address,
            protocol=mock_stream_protocol,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____connect____backend____explicit_argument(
        self,
        remote_address: tuple[str, int],
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncTCPNetworkClient.connect(
            remote_address,
            protocol=mock_stream_protocol,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    async def test____from_socket____use_given_socket(
        self,
        mock_tcp_socket: MagicMock,
        mock_backend: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client: AsyncTCPNetworkClient[Any, Any] = await AsyncTCPNetworkClient.from_socket(
            mock_tcp_socket, protocol=mock_stream_protocol
        )

        # Assert
        mock_new_backend.assert_called_once_with(None)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_backend.wrap_tcp_client_socket.assert_awaited_once_with(mock_tcp_socket)
        mock_stream_socket_adapter.socket.assert_called_once_with()
        mock_stream_socket_adapter.get_local_address.assert_called_once_with()
        mock_stream_socket_adapter.get_remote_address.assert_called_once_with()
        mock_tcp_socket.setsockopt.assert_called_once_with(IPPROTO_TCP, TCP_NODELAY, True)
        assert isinstance(client.socket, SocketProxy)

    async def test____from_socket____backend____from_string(
        self,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncTCPNetworkClient.from_socket(
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            backend="custom_backend",
            backend_kwargs={"arg1": 1, "arg2": "2"},
        )

        # Assert
        mock_new_backend.assert_called_once_with("custom_backend", arg1=1, arg2="2")

    async def test____from_socket____backend____explicit_argument(
        self,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_backend: MagicMock,
        mock_new_backend: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await AsyncTCPNetworkClient.from_socket(
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            backend=mock_backend,
        )

        # Assert
        mock_new_backend.assert_not_called()

    @pytest.mark.parametrize("max_recv_size", [None, 1, 2**64], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____max_recv_size____valid_value(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: int | None,
        use_socket: bool,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        expected_size: int = max_recv_size if max_recv_size is not None else MAX_STREAM_BUFSIZE

        # Act
        client: AsyncTCPNetworkClient[Any, Any]
        if use_socket:
            client = await AsyncTCPNetworkClient.from_socket(
                request.getfixturevalue("mock_tcp_socket"),
                mock_stream_protocol,
                max_recv_size=max_recv_size,
            )
        else:
            client = await AsyncTCPNetworkClient.connect(
                request.getfixturevalue("remote_address"),
                family=request.getfixturevalue("socket_family"),
                protocol=mock_stream_protocol,
                max_recv_size=max_recv_size,
            )

        # Assert
        assert client.max_recv_size == expected_size

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    async def test____dunder_init____max_recv_size____invalid_value(
        self,
        request: pytest.FixtureRequest,
        max_recv_size: Any,
        use_socket: bool,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            if use_socket:
                _ = await AsyncTCPNetworkClient.from_socket(
                    request.getfixturevalue("mock_tcp_socket"),
                    mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )
            else:
                _ = await AsyncTCPNetworkClient.connect(
                    request.getfixturevalue("remote_address"),
                    family=request.getfixturevalue("socket_family"),
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )

    async def test____close____await_socket_close(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        assert not client.is_closing()

        # Act
        await client.close()

        # Assert
        assert client.is_closing()
        mock_stream_socket_adapter.close.assert_awaited_once_with()

    async def test____close____await_socket_close____error_occurred(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        error = OSError("Bad file descriptor")
        mock_stream_socket_adapter.close.side_effect = error
        assert not client.is_closing()

        # Act
        with pytest.raises(OSError) as exc_info:
            await client.close()

        # Assert
        assert client.is_closing()
        assert exc_info.value is error
        mock_stream_socket_adapter.close.assert_awaited_once_with()

    async def test____close____await_socket_close____hide_connection_error(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        error = ConnectionAbortedError()
        mock_stream_socket_adapter.close.side_effect = error
        assert not client.is_closing()

        # Act
        await client.close()

        # Assert
        assert client.is_closing()
        mock_stream_socket_adapter.close.assert_awaited_once_with()

    async def test____close____already_closed(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        await client.close()
        assert client.is_closing()

        # Act
        await client.close()

        # Assert
        mock_stream_socket_adapter.close.assert_awaited_once_with()

    async def test____abort____brute_force_shutdown(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await client.abort()

        # Assert
        mock_stream_socket_adapter.abort.assert_awaited_once_with()
        mock_stream_socket_adapter.close.assert_not_awaited()
        assert client.is_closing()

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    async def test____get_local_address____return_saved_address(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        client_closed: bool,
        socket_family: int,
        local_address: tuple[str, int],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.get_local_address.reset_mock()
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
        mock_stream_socket_adapter.get_local_address.assert_not_called()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    async def test____get_remote_address____return_saved_address(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        client_closed: bool,
        remote_address: tuple[str, int],
        socket_family: int,
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        mock_stream_socket_adapter.get_remote_address.assert_called_once()
        if client_closed:
            await client.close()
            assert client.is_closing()

        # Act
        address = client.get_remote_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_stream_socket_adapter.get_remote_address.assert_called_once()
        assert address.host == remote_address[0]
        assert address.port == remote_address[1]

    async def test____fileno____default(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.fileno.return_value = mocker.sentinel.fileno

        # Act
        fd = client.fileno()

        # Assert
        mock_tcp_socket.fileno.assert_called_once_with()
        assert fd is mocker.sentinel.fileno

    async def test____fileno____closed_client(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        await client.close()
        assert client.is_closing()

        # Act
        fd = client.fileno()

        # Assert
        mock_tcp_socket.fileno.assert_not_called()
        assert fd == -1

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____send_bytes_to_socket(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        # Act
        await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.sendall.assert_awaited_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from errno import ECONNRESET
        from socket import SO_ERROR, SOL_SOCKET

        mock_tcp_socket.getsockopt.return_value = ECONNRESET

        # Act
        with pytest.raises(OSError) as exc_info:
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == ECONNRESET
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_socket_adapter.sendall.assert_awaited_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____closed_client_error(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        await client.close()
        assert client.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_socket_adapter.sendall.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    async def test____send_packet____unexpected_socket_close(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ConnectionAbortedError):
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_socket_adapter.sendall.assert_not_awaited()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____receive_bytes_from_socket(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b"packet\n"]

        # Act
        packet: Any = await client.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert packet is mocker.sentinel.packet

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____partial_data(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = await client.recv_packet()

        # Assert
        mock_backend.coro_yield.assert_awaited_once()
        assert mock_stream_socket_adapter.recv.mock_calls == [mocker.call(MAX_STREAM_BUFSIZE) for _ in range(2)]
        assert mock_stream_data_consumer.feed.mock_calls == [mocker.call(b"pac"), mocker.call(b"ket\n")]
        assert packet is mocker.sentinel.packet

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____extra_data(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = await client.recv_packet()
        packet_2: Any = await client.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_called_once()
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        mock_backend.coro_yield.assert_not_awaited()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____eof_error____default(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mock_backend: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b""]

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____protocol_parse_error(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import StreamProtocolParseError

        mock_stream_socket_adapter.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", "deserialization", "Sorry")
        mock_stream_data_consumer.__next__.side_effect = [StopIteration, expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await client.recv_packet()
        exception = exc_info.value

        # Assert
        mock_stream_socket_adapter.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        mock_backend.coro_yield.assert_not_awaited()
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____closed_client_error(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        await client.close()
        assert client.is_closing()

        # Act
        with pytest.raises(ClientClosedError):
            _ = await client.recv_packet()

        # Assert
        mock_stream_data_consumer.feed.assert_not_called()
        mock_stream_socket_adapter.recv.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____recv_packet____unexpected_socket_close(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_backend: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.is_closing.return_value = True

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet()

        # Assert
        mock_stream_data_consumer.feed.assert_not_called()
        mock_stream_socket_adapter.recv.assert_not_called()
        mock_backend.coro_yield.assert_not_awaited()

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    async def test____special_case____send_packet____eof_error____do_not_try_socket_send(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet()

        mock_stream_socket_adapter.recv.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError):
            await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_socket_adapter.sendall.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    async def test____special_case____recv_packet____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        client: AsyncTCPNetworkClient[Any, Any],
        mock_stream_socket_adapter: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet()

        mock_stream_socket_adapter.recv.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = await client.recv_packet()

        # Assert
        mock_stream_socket_adapter.recv.assert_not_called()

    async def test____get_backend____default(self, client: AsyncTCPNetworkClient[Any, Any], mock_backend: MagicMock) -> None:
        # Arrange

        # Act & Assert
        assert client.get_backend() is mock_backend
