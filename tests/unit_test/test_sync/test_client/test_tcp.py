# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import AF_INET6, IPPROTO_TCP, TCP_NODELAY
from typing import TYPE_CHECKING, Any

from easynetwork.api_sync.client.tcp import TCPNetworkClient
from easynetwork.exceptions import ClientClosedError
from easynetwork.tools.socket import MAX_STREAM_BUFSIZE, IPv4SocketAddress, IPv6SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from .base import BaseTestClient


@pytest.fixture(scope="module", autouse=True)
def setup_dummy_lock(module_mocker: MockerFixture, dummy_lock_cls: Any) -> None:
    module_mocker.patch(f"{TCPNetworkClient.__module__}._Lock", new=dummy_lock_cls)


class TestTCPNetworkClient(BaseTestClient):
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
    def mock_socket_create_connection(mocker: MockerFixture, mock_tcp_socket: MagicMock) -> MagicMock:
        return mocker.patch("socket.create_connection", return_value=mock_tcp_socket)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_socket_proxy_cls(mocker: MockerFixture, mock_tcp_socket: MagicMock) -> MagicMock:
        return mocker.patch(f"{TCPNetworkClient.__module__}.SocketProxy", return_value=mock_tcp_socket)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_data_consumer_cls(mocker: MockerFixture, mock_stream_data_consumer: MagicMock) -> MagicMock:
        return mocker.patch(f"{TCPNetworkClient.__module__}.StreamDataConsumer", return_value=mock_stream_data_consumer)

    @pytest.fixture(autouse=True)
    @classmethod
    def local_address(
        cls,
        mock_tcp_socket: MagicMock,
        socket_family: int,
        global_local_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_local_address_to_socket_mock(mock_tcp_socket, socket_family, global_local_address)
        return global_local_address

    @pytest.fixture(autouse=True)
    @classmethod
    def remote_address(
        cls,
        mock_tcp_socket: MagicMock,
        socket_family: int,
        global_remote_address: tuple[str, int],
    ) -> tuple[str, int]:
        cls.set_remote_address_to_socket_mock(mock_tcp_socket, socket_family, global_remote_address)
        return global_remote_address

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_tcp_socket: MagicMock,
        socket_family: int,
        mocker: MockerFixture,
    ) -> None:
        mock_tcp_socket.family = socket_family
        mock_tcp_socket.gettimeout.return_value = mocker.sentinel.default_timeout
        mock_tcp_socket.getsockopt.return_value = 0  # Needed for tests dealing with send_packet()

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
    def max_recv_size(request: Any) -> int | None:
        return getattr(request, "param", None)

    @pytest.fixture(params=["REMOTE_ADDRESS", "SOCKET_WITH_EXPLICIT_GIVE"])
    @staticmethod
    def client_with_socket_ownership(
        request: Any,
        max_recv_size: int | None,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> TCPNetworkClient[Any, Any]:
        match request.param:
            case "REMOTE_ADDRESS":
                return TCPNetworkClient(remote_address, mock_stream_protocol, max_recv_size=max_recv_size)
            case "SOCKET_WITH_EXPLICIT_GIVE":
                return TCPNetworkClient(mock_tcp_socket, mock_stream_protocol, give=True, max_recv_size=max_recv_size)
            case invalid:
                pytest.fail(f"Invalid fixture param: Got {invalid!r}")

    @pytest.fixture
    @staticmethod
    def client_without_socket_ownership(
        max_recv_size: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> TCPNetworkClient[Any, Any]:
        return TCPNetworkClient(mock_tcp_socket, mock_stream_protocol, give=False, max_recv_size=max_recv_size)

    @pytest.fixture
    @staticmethod
    def client(client_without_socket_ownership: TCPNetworkClient[Any, Any]) -> TCPNetworkClient[Any, Any]:
        return client_without_socket_ownership

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: Any) -> Any:
        return request.param

    def test____dunder_init____connect_to_remote(
        self,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_socket_proxy_cls.return_value = mocker.sentinel.proxy

        # Act
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            timeout=mocker.sentinel.timeout,
            source_address=mocker.sentinel.source_address,
        )

        # Assert
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_socket_create_connection.assert_called_once_with(
            remote_address,
            timeout=mocker.sentinel.timeout,
            source_address=mocker.sentinel.source_address,
        )
        mock_socket_proxy_cls.assert_called_once_with(mock_tcp_socket, lock=mocker.ANY)
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        mock_tcp_socket.setsockopt.assert_called_once_with(IPPROTO_TCP, TCP_NODELAY, True)
        assert client.socket is mocker.sentinel.proxy

    @pytest.mark.parametrize("give_ownership", [False, True], ids=lambda p: f"give=={p}")
    def test____dunder_init____use_given_socket(
        self,
        give_ownership: bool,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_socket_proxy_cls.return_value = mocker.sentinel.proxy

        # Act
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(mock_tcp_socket, protocol=mock_stream_protocol, give=give_ownership)

        # Assert
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_socket_create_connection.assert_not_called()
        mock_socket_proxy_cls.assert_called_once_with(mock_tcp_socket, lock=mocker.ANY)
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        mock_tcp_socket.setsockopt.assert_called_once_with(IPPROTO_TCP, TCP_NODELAY, True)
        assert client.socket is mocker.sentinel.proxy

    @pytest.mark.parametrize("give_ownership", [False, True], ids=lambda p: f"give=={p}")
    def test____dunder_init____invalid_socket_type_error(
        self,
        give_ownership: bool,
        mock_udp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^Invalid socket type$"):
            _ = TCPNetworkClient(mock_udp_socket, protocol=mock_stream_protocol, give=give_ownership)

        # Assert
        mock_stream_data_consumer_cls.assert_not_called()
        mock_socket_create_connection.assert_not_called()
        mock_socket_proxy_cls.assert_not_called()
        mock_udp_socket.getsockname.assert_not_called()
        mock_udp_socket.getpeername.assert_not_called()
        ## If ownership was given, the socket must be closed
        if give_ownership:
            mock_udp_socket.close.assert_called_once_with()
        else:
            mock_udp_socket.close.assert_not_called()

    @pytest.mark.parametrize("give_ownership", [False, True], ids=lambda p: f"give=={p}")
    def test____dunder_init____socket_given_is_not_connected_error(
        self,
        give_ownership: bool,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        enotconn_exception = self.configure_socket_mock_to_raise_ENOTCONN(mock_tcp_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = TCPNetworkClient(mock_tcp_socket, protocol=mock_stream_protocol, give=give_ownership)

        # Assert
        assert exc_info.value is enotconn_exception
        mock_stream_data_consumer_cls.assert_not_called()
        mock_socket_create_connection.assert_not_called()
        mock_socket_proxy_cls.assert_not_called()
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        ## If ownership was given, the socket must be closed
        if give_ownership:
            mock_tcp_socket.close.assert_called_once_with()
        else:
            mock_tcp_socket.close.assert_not_called()

    def test____dunder_init____ownership_parameter_missing(
        self,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(TypeError, match=r"^Missing keyword argument 'give'$"):
            _ = TCPNetworkClient(mock_tcp_socket, protocol=mock_stream_protocol)

        # Assert
        mock_stream_data_consumer_cls.assert_not_called()
        mock_socket_create_connection.assert_not_called()
        mock_socket_proxy_cls.assert_not_called()
        mock_tcp_socket.close.assert_not_called()

    @pytest.mark.parametrize("max_recv_size", [None, 1, 2**64], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____with_ownership____max_size____valid_value(
        self,
        max_recv_size: int | None,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        expected_size: int = max_recv_size if max_recv_size is not None else MAX_STREAM_BUFSIZE

        # Act
        client: TCPNetworkClient[Any, Any]
        if use_socket:
            client = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                give=True,
                max_recv_size=max_recv_size,
            )
        else:
            client = TCPNetworkClient(
                remote_address,
                protocol=mock_stream_protocol,
                max_recv_size=max_recv_size,
            )

        # Assert
        assert client.max_recv_bufsize == expected_size

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    @pytest.mark.parametrize("use_socket", [False, True], ids=lambda p: f"use_socket=={p}")
    def test____dunder_init____with_ownership____max_size____invalid_value(
        self,
        max_recv_size: Any,
        use_socket: bool,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_socket_proxy_cls: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^max_size must be a strict positive integer$"):
            if use_socket:
                _ = TCPNetworkClient(
                    mock_tcp_socket,
                    protocol=mock_stream_protocol,
                    give=True,
                    max_recv_size=max_recv_size,
                )
            else:
                _ = TCPNetworkClient(
                    remote_address,
                    protocol=mock_stream_protocol,
                    max_recv_size=max_recv_size,
                )

        # Assert
        mock_stream_data_consumer_cls.assert_not_called()
        mock_socket_proxy_cls.assert_not_called()
        mock_tcp_socket.getsockname.assert_not_called()
        mock_tcp_socket.getpeername.assert_not_called()
        mock_tcp_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("max_recv_size", [None, 1, 2**64], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____without_ownership____max_size____valid_value(
        self,
        max_recv_size: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        expected_size: int = max_recv_size if max_recv_size is not None else MAX_STREAM_BUFSIZE

        # Act
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            give=False,
            max_recv_size=max_recv_size,
        )

        # Assert
        assert client.max_recv_bufsize == expected_size

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____without_ownership____max_size____invalid_value(
        self,
        max_recv_size: Any,
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_socket_proxy_cls: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^max_size must be a strict positive integer$"):
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                give=False,
                max_recv_size=max_recv_size,
            )

        # Assert
        mock_stream_data_consumer_cls.assert_not_called()
        mock_socket_proxy_cls.assert_not_called()
        mock_tcp_socket.getsockname.assert_not_called()
        mock_tcp_socket.getpeername.assert_not_called()
        mock_tcp_socket.close.assert_not_called()

    def test____close____with_ownership(
        self,
        client_with_socket_ownership: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client_with_socket_ownership.is_closed()

        # Act
        client_with_socket_ownership.close()

        # Assert
        assert client_with_socket_ownership.is_closed()
        mock_tcp_socket.shutdown.assert_not_called()
        mock_tcp_socket.close.assert_called_once_with()

    def test____close____without_ownership(
        self,
        client_without_socket_ownership: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client_without_socket_ownership.is_closed()

        # Act
        client_without_socket_ownership.close()

        # Assert
        assert client_without_socket_ownership.is_closed()
        mock_tcp_socket.shutdown.assert_not_called()
        mock_tcp_socket.close.assert_not_called()

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    def test____get_local_address____return_saved_address(
        self,
        client: TCPNetworkClient[Any, Any],
        client_closed: bool,
        socket_family: int,
        local_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.getsockname.reset_mock()
        if client_closed:
            client.close()
            assert client.is_closed()

        # Act
        address = client.get_local_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_tcp_socket.getsockname.assert_not_called()
        assert address.host == local_address[0]
        assert address.port == local_address[1]

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    def test____get_remote_address____return_saved_address(
        self,
        client: TCPNetworkClient[Any, Any],
        client_closed: bool,
        remote_address: tuple[str, int],
        socket_family: int,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        ## NOTE: The client should have the remote address saved. Therefore this test check if there is no new call.
        mock_tcp_socket.getpeername.assert_called_once()
        if client_closed:
            client.close()
            assert client.is_closed()

        # Act
        address = client.get_remote_address()

        # Assert
        if socket_family == AF_INET6:
            assert isinstance(address, IPv6SocketAddress)
        else:
            assert isinstance(address, IPv4SocketAddress)
        mock_tcp_socket.getpeername.assert_called_once()
        assert address.host == remote_address[0]
        assert address.port == remote_address[1]

    def test____fileno____default(
        self,
        client: TCPNetworkClient[Any, Any],
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

    def test____fileno____closed_client(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        fd = client.fileno()

        # Assert
        mock_tcp_socket.fileno.assert_not_called()
        assert fd == -1

    @pytest.mark.parametrize("shutdown_flag_name", ["SHUT_RD", "SHUT_WR", "SHUT_RDWR"])
    def test____shutdown____default(
        self,
        client: TCPNetworkClient[Any, Any],
        shutdown_flag_name: str,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        import socket

        shutdown_flag = int(getattr(socket, shutdown_flag_name))

        # Act
        client.shutdown(shutdown_flag)

        # Assert
        mock_tcp_socket.shutdown.assert_called_once_with(shutdown_flag)

    @pytest.mark.parametrize("shutdown_flag_name", ["SHUT_RD", "SHUT_WR", "SHUT_RDWR"])
    def test____shutdown____closed_client(
        self,
        client: TCPNetworkClient[Any, Any],
        shutdown_flag_name: str,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        import socket

        shutdown_flag = int(getattr(socket, shutdown_flag_name))
        client.close()

        # Act
        with pytest.raises(ClientClosedError):
            client.shutdown(shutdown_flag)

        # Assert
        mock_tcp_socket.shutdown.assert_not_called()

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____send_bytes_to_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import SO_ERROR, SOL_SOCKET

        # Act
        client.send_packet(mocker.sentinel.packet)

        # Assert
        assert mock_tcp_socket.settimeout.mock_calls == [mocker.call(None), mocker.call(mocker.sentinel.default_timeout)]
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_tcp_socket.sendall.assert_called_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____raise_error_saved_in_SO_ERROR_option(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from errno import ECONNRESET
        from socket import SO_ERROR, SOL_SOCKET

        mock_tcp_socket.getsockopt.return_value = ECONNRESET

        # Act
        with pytest.raises(OSError) as exc_info:
            client.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.errno == ECONNRESET
        assert mock_tcp_socket.settimeout.mock_calls == [mocker.call(None), mocker.call(mocker.sentinel.default_timeout)]
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_tcp_socket.sendall.assert_called_once_with(b"packet\n")
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_tcp_socket.settimeout.assert_not_called()
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_tcp_socket.sendall.assert_not_called()
        mock_tcp_socket.getsockopt.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____receive_bytes_from_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet\n"]

        # Act
        packet: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert mock_tcp_socket.settimeout.mock_calls == [mocker.call(recv_timeout), mocker.call(mocker.sentinel.default_timeout)]
        mock_tcp_socket.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [None, 123456789], indirect=True)  # Do not test with timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking____partial_data(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        if recv_timeout is None:
            assert mock_tcp_socket.settimeout.mock_calls == [
                mocker.call(recv_timeout),
                mocker.call(mocker.sentinel.default_timeout),
            ]
        else:
            assert mock_tcp_socket.settimeout.mock_calls == [
                mocker.call(recv_timeout),
                mocker.call(mocker.ANY),
                mocker.call(mocker.sentinel.default_timeout),
            ]
        assert mock_tcp_socket.recv.mock_calls == [mocker.call(MAX_STREAM_BUFSIZE) for _ in range(2)]
        assert mock_stream_data_consumer.feed.mock_calls == [mocker.call(b"pac"), mocker.call(b"ket\n")]
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [0], indirect=True)  # Only test with timeout==0
    @pytest.mark.parametrize(
        "max_recv_size",
        [
            pytest.param(3, id="chunk_matching_bufsize"),
            pytest.param(1024, id="chunk_not_matching_bufsize"),
        ],
        indirect=True,
    )
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_____non_blocking____partial_data(
        self,
        client: TCPNetworkClient[Any, Any],
        max_recv_size: int,
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket", b"\n"]

        # Act & Assert
        if max_recv_size == 3:
            packet: Any = client.recv_packet(timeout=recv_timeout)

            assert mock_tcp_socket.recv.mock_calls == [mocker.call(max_recv_size) for _ in range(3)]
            assert mock_stream_data_consumer.feed.mock_calls == [mocker.call(b"pac"), mocker.call(b"ket"), mocker.call(b"\n")]
            assert packet is mocker.sentinel.packet
        else:
            with pytest.raises(TimeoutError, match=r"^recv_packet\(\) timed out$"):
                client.recv_packet(timeout=recv_timeout)

            mock_tcp_socket.recv.assert_called_once_with(max_recv_size)
            mock_stream_data_consumer.feed.assert_called_once_with(b"pac")

        assert mock_tcp_socket.settimeout.mock_calls == [
            mocker.call(recv_timeout),
            mocker.call(mocker.sentinel.default_timeout),
        ]

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____extra_data(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = client.recv_packet(timeout=recv_timeout)
        mock_tcp_socket.settimeout.reset_mock()
        packet_2: Any = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_tcp_socket.recv.assert_called_once()
        mock_tcp_socket.settimeout.assert_not_called()
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____eof_error____default(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b""]

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        assert mock_tcp_socket.settimeout.mock_calls == [mocker.call(recv_timeout), mocker.call(mocker.sentinel.default_timeout)]
        mock_tcp_socket.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____protocol_parse_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import StreamProtocolParseError

        mock_tcp_socket.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", "deserialization", "Sorry")
        mock_stream_data_consumer.__next__.side_effect = [StopIteration, expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = client.recv_packet(timeout=recv_timeout)
        exception = exc_info.value

        # Assert
        assert mock_tcp_socket.settimeout.mock_calls == [mocker.call(recv_timeout), mocker.call(mocker.sentinel.default_timeout)]
        mock_tcp_socket.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____blocking_or_not____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(ClientClosedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_tcp_socket.settimeout.assert_not_called()
        mock_stream_data_consumer.feed.assert_not_called()
        mock_tcp_socket.recv.assert_not_called()

    @pytest.mark.parametrize(
        ["recv_timeout", "recv_exception"],
        [
            pytest.param(0, BlockingIOError, id="null timeout"),
            pytest.param(123456789, TimeoutError, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet____timeout(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int,
        recv_exception: type[BaseException],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = recv_exception

        # Act & Assert
        with pytest.raises(TimeoutError, match=r"^recv_packet\(\) timed out$"):
            _ = client.recv_packet(timeout=recv_timeout)

        mock_tcp_socket.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.parametrize(
        ["recv_timeout", "recv_exception"],
        [
            pytest.param(0, BlockingIOError, id="null timeout"),
            pytest.param(123456789, TimeoutError, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.parametrize("max_recv_size", [3], indirect=True)  # Needed for timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_with_given_timeout(
        self,
        client: TCPNetworkClient[Any, Any],
        max_recv_size: int,
        recv_timeout: int,
        recv_exception: type[BaseException],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket", b"_1\np", b"ack", b"et_", b"2\n", recv_exception]

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [mocker.call(max_recv_size) for _ in range(7)]
        assert mock_stream_data_consumer.feed.mock_calls == [
            mocker.call(b"pac"),
            mocker.call(b"ket"),
            mocker.call(b"_1\np"),
            mocker.call(b"ack"),
            mocker.call(b"et_"),
            mocker.call(b"2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.parametrize("max_recv_size", [3], indirect=True)  # Needed for timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_until_eof(
        self,
        client: TCPNetworkClient[Any, Any],
        max_recv_size: int,
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket", b"_1\np", b"ack", b"et_", b"2\n", b""]

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [mocker.call(max_recv_size) for _ in range(7)]
        assert mock_stream_data_consumer.feed.mock_calls == [
            mocker.call(b"pac"),
            mocker.call(b"ket"),
            mocker.call(b"_1\np"),
            mocker.call(b"ack"),
            mocker.call(b"et_"),
            mocker.call(b"2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.parametrize("max_recv_size", [3], indirect=True)  # Needed for timeout==0
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_until_error(
        self,
        client: TCPNetworkClient[Any, Any],
        max_recv_size: int,
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket", b"_1\np", b"ack", b"et_", b"2\n", OSError]

        # Act
        packets = list(client.iter_received_packets(timeout=recv_timeout))

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [mocker.call(max_recv_size) for _ in range(7)]
        assert mock_stream_data_consumer.feed.mock_calls == [
            mocker.call(b"pac"),
            mocker.call(b"ket"),
            mocker.call(b"_1\np"),
            mocker.call(b"ack"),
            mocker.call(b"et_"),
            mocker.call(b"2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____protocol_parse_error(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.exceptions import StreamProtocolParseError

        mock_stream_data_consumer.__next__.side_effect = StreamProtocolParseError(b"", "deserialization", "Sorry")

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = next(client.iter_received_packets(timeout=recv_timeout))
        exception = exc_info.value

        # Assert
        assert exception is mock_stream_data_consumer.__next__.side_effect

    @pytest.mark.parametrize("several_generators", [False, True], ids=lambda t: f"several_generators=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____avoid_unnecessary_socket_recv_call(
        self,
        client: TCPNetworkClient[Any, Any],
        several_generators: bool,
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        if several_generators:
            packet_1 = next(client.iter_received_packets(timeout=recv_timeout))
            packet_2 = next(client.iter_received_packets(timeout=recv_timeout))
        else:
            iterator = client.iter_received_packets(timeout=recv_timeout)
            packet_1 = next(iterator)
            packet_2 = next(iterator)

        # Assert
        mock_tcp_socket.recv.assert_called_once_with(MAX_STREAM_BUFSIZE)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____release_internal_lock_before_yield(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from threading import Lock

        mock_acquire = mocker.patch.object(Lock, "acquire", return_value=True)
        mock_release = mocker.patch.object(Lock, "release", return_value=None)
        mock_tcp_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act & Assert
        iterator = client.iter_received_packets(timeout=recv_timeout)
        mock_acquire.assert_not_called()
        mock_release.assert_not_called()
        packet_1 = next(iterator)
        mock_acquire.assert_called_once_with()
        mock_release.assert_called_once_with()
        mock_acquire.reset_mock()
        mock_release.reset_mock()
        packet_2 = next(iterator)
        mock_acquire.assert_called_once_with()
        mock_release.assert_called_once_with()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____closed_client_during_iteration(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet_1\n"]

        # Act & Assert
        iterator = client.iter_received_packets(timeout=recv_timeout)
        packet_1 = next(iterator)
        assert packet_1 is mocker.sentinel.packet_1
        client.close()
        assert client.is_closed()
        with pytest.raises(StopIteration):
            _ = next(iterator)

    @pytest.mark.usefixtures("setup_producer_mock", "setup_consumer_mock")
    def test____special_case____send_packet____eof_error____do_not_try_socket_send(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet()

        mock_tcp_socket.recv.reset_mock()
        mock_tcp_socket.settimeout.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_tcp_socket.settimeout.assert_not_called()
        mock_tcp_socket.sendall.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____special_case____recv_packet____blocking_or_not____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        client: TCPNetworkClient[Any, Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        mock_tcp_socket.recv.reset_mock()
        mock_tcp_socket.settimeout.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError):
            _ = client.recv_packet(timeout=recv_timeout)

        # Assert
        mock_tcp_socket.recv.assert_not_called()
        mock_tcp_socket.settimeout.assert_not_called()
