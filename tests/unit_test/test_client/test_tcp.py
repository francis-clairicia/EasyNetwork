# -*- coding: Utf-8 -*-

from __future__ import annotations

from collections import deque
from socket import AF_INET6
from typing import TYPE_CHECKING, Any, Callable, Iterator

from easynetwork.client.tcp import TCPNetworkClient
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture(scope="module", autouse=True)
def setup_dummy_lock(module_mocker: MockerFixture, dummy_lock_cls: Any) -> None:
    module_mocker.patch(f"{TCPNetworkClient.__module__}.RLock", new=dummy_lock_cls)


class TestTCPNetworkClient:
    @pytest.fixture(scope="class", params=["AF_INET", "AF_INET6"])
    @staticmethod
    def socket_family(request: Any) -> Any:
        import socket

        return getattr(socket, request.param)

    @pytest.fixture(scope="class")
    @staticmethod
    def remote_address() -> tuple[str, int]:
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
    def mock_stream_data_producer_cls(mocker: MockerFixture, mock_stream_data_producer: MagicMock) -> MagicMock:
        return mocker.patch(f"{TCPNetworkClient.__module__}.StreamDataProducer", return_value=mock_stream_data_producer)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_stream_data_consumer_cls(mocker: MockerFixture, mock_stream_data_consumer: MagicMock) -> MagicMock:
        return mocker.patch(f"{TCPNetworkClient.__module__}.StreamDataConsumer", return_value=mock_stream_data_consumer)

    @pytest.fixture(autouse=True)
    @staticmethod
    def set_default_socket_mock_configuration(
        mock_tcp_socket: MagicMock,
        socket_family: int,
        remote_address: tuple[str, int],
        mocker: MockerFixture,
    ) -> None:
        additional_address_components: tuple[Any, ...] = (0, 0) if socket_family == AF_INET6 else ()

        mock_tcp_socket.family = socket_family
        mock_tcp_socket.getsockname.return_value = ("local_address", 12345) + additional_address_components
        mock_tcp_socket.getpeername.return_value = remote_address + additional_address_components
        mock_tcp_socket.gettimeout.return_value = mocker.sentinel.default_timeout

    @pytest.fixture(scope="class", autouse=True)
    @staticmethod
    def auto_client_close(class_mocker: MockerFixture) -> Iterator[None]:
        from contextlib import ExitStack, closing

        client_stack = ExitStack()
        default_new = TCPNetworkClient.__new__

        def patch_new(cls: type[Any], *args: Any, **kwargs: Any) -> Any:
            obj = default_new(cls)
            client_stack.enter_context(closing(obj))
            return obj

        class_mocker.patch.object(TCPNetworkClient, "__new__", staticmethod(patch_new))
        # Default __del__ implementation try to close client
        class_mocker.patch.object(TCPNetworkClient, "__del__", lambda self: None)
        with client_stack:
            yield

    @pytest.fixture(params=["REMOTE_ADDRESS", "SOCKET_WITH_EXPLICIT_GIVE"])
    @staticmethod
    def client_with_socket_ownership(
        request: Any,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> TCPNetworkClient[Any, Any]:
        match request.param:
            case "REMOTE_ADDRESS":
                return TCPNetworkClient(
                    remote_address,
                    mock_stream_protocol,
                    send_flags=mocker.sentinel.send_flags,
                    recv_flags=mocker.sentinel.recv_flags,
                )
            case "SOCKET_WITH_EXPLICIT_GIVE":
                return TCPNetworkClient(
                    mock_tcp_socket,
                    mock_stream_protocol,
                    give=True,
                    send_flags=mocker.sentinel.send_flags,
                    recv_flags=mocker.sentinel.recv_flags,
                )
            case invalid:
                pytest.fail(f"Invalid fixture param: Got {invalid!r}")

    @pytest.fixture  # DO NOT set autouse=True
    @staticmethod
    def setup_producer_mock(mock_stream_data_producer: MagicMock) -> None:
        bytes_queue: deque[bytes] = deque()

        def queue_side_effect(*packets: Any) -> None:
            nonlocal bytes_queue
            bytes_queue.extend(str(p).encode("ascii").removeprefix(b"sentinel.") + b"\n" for p in packets)

        def next_side_effect() -> bytes:
            nonlocal bytes_queue
            try:
                return bytes_queue.popleft()
            except IndexError:
                raise StopIteration from None

        mock_stream_data_producer.queue.side_effect = queue_side_effect
        mock_stream_data_producer.__iter__.side_effect = lambda: mock_stream_data_producer
        mock_stream_data_producer.__next__.side_effect = next_side_effect

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
    def client_without_socket_ownership(
        mock_tcp_socket: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> TCPNetworkClient[Any, Any]:
        return TCPNetworkClient(
            mock_tcp_socket,
            mock_stream_protocol,
            give=False,
            send_flags=mocker.sentinel.send_flags,
            recv_flags=mocker.sentinel.recv_flags,
        )

    @pytest.fixture
    @staticmethod
    def client(client_without_socket_ownership: TCPNetworkClient[Any, Any]) -> TCPNetworkClient[Any, Any]:
        return client_without_socket_ownership

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking"),
            pytest.param(123456789, id="non_blocking"),
        ]
    )
    @staticmethod
    def recv_timeout(request: Any) -> Any:
        return request.param

    @pytest.fixture
    @staticmethod
    def client_recv_packet(client: TCPNetworkClient[Any, Any], recv_timeout: int | None) -> Any:
        from functools import partial

        if recv_timeout is None:
            return client.recv_packet
        return partial(client.recv_packet_no_block, timeout=recv_timeout)

    def test____dunder_init____connect_to_remote(
        self,
        remote_address: tuple[str, int],
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_producer_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(
            remote_address,
            protocol=mock_stream_protocol,
            timeout=mocker.sentinel.timeout,
            source_address=mocker.sentinel.source_address,
            send_flags=mocker.sentinel.send_flags,
            recv_flags=mocker.sentinel.recv_flags,
        )

        # Assert
        mock_stream_data_producer_cls.assert_called_once_with(mock_stream_protocol)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_socket_create_connection.assert_called_once_with(
            remote_address,
            timeout=mocker.sentinel.timeout,
            source_address=mocker.sentinel.source_address,
        )
        mock_socket_proxy_cls.assert_called_once_with(mock_tcp_socket)
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        assert client.default_send_flags is mocker.sentinel.send_flags
        assert client.default_recv_flags is mocker.sentinel.recv_flags
        assert client.socket is mock_tcp_socket

    @pytest.mark.parametrize("give_ownership", [False, True], ids=lambda p: f"give=={p}")
    def test____dunder_init____use_given_socket(
        self,
        give_ownership: bool,
        mock_tcp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_producer_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client: TCPNetworkClient[Any, Any] = TCPNetworkClient(
            mock_tcp_socket,
            protocol=mock_stream_protocol,
            give=give_ownership,
            send_flags=mocker.sentinel.send_flags,
            recv_flags=mocker.sentinel.recv_flags,
        )

        # Assert
        mock_stream_data_producer_cls.assert_called_once_with(mock_stream_protocol)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_socket_create_connection.assert_not_called()
        mock_socket_proxy_cls.assert_called_once_with(mock_tcp_socket)
        mock_tcp_socket.getsockname.assert_called_once_with()
        mock_tcp_socket.getpeername.assert_called_once_with()
        assert client.default_send_flags is mocker.sentinel.send_flags
        assert client.default_recv_flags is mocker.sentinel.recv_flags
        assert client.socket is mock_tcp_socket

    @pytest.mark.parametrize("give_ownership", [False, True], ids=lambda p: f"give=={p}")
    def test____dunder_init____invalid_socket_type_error(
        self,
        give_ownership: bool,
        mock_udp_socket: MagicMock,
        mock_socket_create_connection: MagicMock,
        mock_socket_proxy_cls: MagicMock,
        mock_stream_data_producer_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError, match=r"^Invalid socket type$"):
            _ = TCPNetworkClient(
                mock_udp_socket,
                protocol=mock_stream_protocol,
                give=give_ownership,
                send_flags=mocker.sentinel.send_flags,
                recv_flags=mocker.sentinel.recv_flags,
            )

        # Assert
        mock_stream_data_producer_cls.assert_called_once_with(mock_stream_protocol)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
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
        mock_stream_data_producer_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import errno
        import os

        ## Exception raised by socket.getpeername() if socket.connect() was not called before
        enotconn_exception = OSError(errno.ENOTCONN, os.strerror(errno.ENOTCONN))
        mock_tcp_socket.getpeername.side_effect = enotconn_exception

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                give=give_ownership,
                send_flags=mocker.sentinel.send_flags,
                recv_flags=mocker.sentinel.recv_flags,
            )

        # Assert
        assert exc_info.value is enotconn_exception
        mock_stream_data_producer_cls.assert_called_once_with(mock_stream_protocol)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
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
        mock_stream_data_producer_cls: MagicMock,
        mock_stream_data_consumer_cls: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(TypeError, match=r"^Missing keyword argument 'give'$"):
            _ = TCPNetworkClient(
                mock_tcp_socket,
                protocol=mock_stream_protocol,
                send_flags=mocker.sentinel.send_flags,
                recv_flags=mocker.sentinel.recv_flags,
            )

        # Assert
        mock_stream_data_producer_cls.assert_called_once_with(mock_stream_protocol)
        mock_stream_data_consumer_cls.assert_called_once_with(mock_stream_protocol)
        mock_socket_create_connection.assert_not_called()
        mock_socket_proxy_cls.assert_not_called()
        mock_tcp_socket.close.assert_not_called()

    @pytest.mark.parametrize(
        "give_shutdown_flag",
        [
            pytest.param(False, id="without parameters"),
            pytest.param(True, id="with default flag indicator"),
        ],
    )
    def test____close____with_ownership____default(
        self,
        client_with_socket_ownership: TCPNetworkClient[Any, Any],
        give_shutdown_flag: bool,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        from socket import SHUT_WR

        assert not client_with_socket_ownership.is_closed()

        # Act
        if give_shutdown_flag:
            client_with_socket_ownership.close(shutdown=-1)
        else:
            client_with_socket_ownership.close()

        # Assert
        assert client_with_socket_ownership.is_closed()
        mock_tcp_socket.shutdown.assert_called_once_with(SHUT_WR)
        mock_tcp_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("shutdown_flag", ["SHUT_RD", "SHUT_WR", "SHUT_RDWR"])
    def test____close____with_ownership____use_given_flag(
        self,
        client_with_socket_ownership: TCPNetworkClient[Any, Any],
        shutdown_flag: str,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        import socket

        shutdown_flag_value: int = getattr(socket, shutdown_flag)

        # Act
        client_with_socket_ownership.close(shutdown=shutdown_flag_value)

        # Assert
        assert client_with_socket_ownership.is_closed()
        mock_tcp_socket.shutdown.assert_called_once_with(shutdown_flag_value)
        mock_tcp_socket.close.assert_called_once_with()

    def test____close____with_ownership____disable_shutdown_using_None(
        self,
        client_with_socket_ownership: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not client_with_socket_ownership.is_closed()

        # Act
        client_with_socket_ownership.close(shutdown=None)

        # Assert
        assert client_with_socket_ownership.is_closed()
        mock_tcp_socket.shutdown.assert_not_called()
        mock_tcp_socket.close.assert_called_once_with()

    def test____close____with_ownership____ignore_shutdown_errors(
        self,
        client_with_socket_ownership: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        from socket import SHUT_WR

        assert not client_with_socket_ownership.is_closed()

        mock_tcp_socket.shutdown.side_effect = OSError("ERROR")

        # Act
        client_with_socket_ownership.close()

        # Assert
        assert client_with_socket_ownership.is_closed()
        mock_tcp_socket.shutdown.assert_called_once_with(SHUT_WR)
        mock_tcp_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("shutdown_flag", ["SHUT_RD", "SHUT_WR", "SHUT_RDWR", -1, None])
    def test____close____without_ownership(
        self,
        client_without_socket_ownership: TCPNetworkClient[Any, Any],
        shutdown_flag: int | str | None,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        if isinstance(shutdown_flag, str):
            import socket

            shutdown_flag = int(getattr(socket, shutdown_flag))

        assert not client_without_socket_ownership.is_closed()

        # Act
        client_without_socket_ownership.close(shutdown=shutdown_flag)

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
        assert address.host == "local_address"
        assert address.port == 12345

    @pytest.mark.parametrize("client_closed", [False, True], ids=lambda p: f"client_closed=={p}")
    def test____get_remote_address____return_saved_address(
        self,
        client: TCPNetworkClient[Any, Any],
        client_closed: bool,
        socket_family: int,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.getpeername.reset_mock()
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
        mock_tcp_socket.getpeername.assert_not_called()
        assert address.host == "remote_address"
        assert address.port == 5000

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

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____send_bytes_to_socket(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_producer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        client.send_packet(mocker.sentinel.packet)

        # Assert
        assert mock_tcp_socket.settimeout.mock_calls == [mocker.call(None), mocker.call(mocker.sentinel.default_timeout)]
        mock_stream_data_producer.queue.assert_called_once_with(mocker.sentinel.packet)
        mock_tcp_socket.sendall.assert_called_once_with(b"packet\n", mocker.sentinel.send_flags)

    @pytest.mark.usefixtures("setup_producer_mock")
    def test____send_packet____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_producer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(RuntimeError, match=r"^Closed client$"):
            client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_tcp_socket.settimeout.assert_not_called()
        mock_stream_data_producer.queue.assert_not_called()
        mock_tcp_socket.sendall.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_blocking_or_not____receive_bytes_from_socket(
        self,
        client_recv_packet: Callable[[], Any],
        recv_timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet\n"]

        # Act
        packet: Any = client_recv_packet()

        # Assert
        assert mock_tcp_socket.settimeout.mock_calls == [mocker.call(recv_timeout), mocker.call(mocker.sentinel.default_timeout)]
        mock_tcp_socket.recv.assert_called_once_with(TCPNetworkClient.max_size, mocker.sentinel.recv_flags)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert packet is mocker.sentinel.packet

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_blocking_or_not____partial_data(
        self,
        client_recv_packet: Callable[[], Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = client_recv_packet()

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [
            mocker.call(TCPNetworkClient.max_size, mocker.sentinel.recv_flags) for _ in range(2)
        ]
        assert mock_stream_data_consumer.feed.mock_calls == [mocker.call(b"pac"), mocker.call(b"ket\n")]
        assert packet is mocker.sentinel.packet

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_blocking_or_not____extra_data(
        self,
        client_recv_packet: Callable[[], Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket_1\npa", b"ck", b"et", b"_2\n"]

        # Act
        packet_1: Any = client_recv_packet()
        packet_2: Any = client_recv_packet()

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [
            mocker.call(TCPNetworkClient.max_size, mocker.sentinel.recv_flags) for _ in range(5)
        ]
        assert mock_stream_data_consumer.feed.mock_calls == [
            mocker.call(b"pac"),
            mocker.call(b"ket_1\npa"),
            mocker.call(b"ck"),
            mocker.call(b"et"),
            mocker.call(b"_2\n"),
        ]
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_blocking_or_not____avoid_unnecessary_socket_recv_call(
        self,
        client_recv_packet: Callable[[], Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = client_recv_packet()
        packet_2: Any = client_recv_packet()

        # Assert
        mock_tcp_socket.recv.assert_called_once_with(TCPNetworkClient.max_size, mocker.sentinel.recv_flags)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_blocking_or_not____eof_error(
        self,
        client_recv_packet: Callable[[], Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b""]

        # Act
        with pytest.raises(EOFError):
            _ = client_recv_packet()

        # Assert
        mock_tcp_socket.recv.assert_called_once_with(TCPNetworkClient.max_size, mocker.sentinel.recv_flags)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_blocking_or_not____protocol_parse_error(
        self,
        client_recv_packet: Callable[[], Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.protocol import StreamProtocolParseError

        mock_tcp_socket.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", "deserialization", "Sorry")
        mock_stream_data_consumer.__next__.side_effect = [StopIteration, expected_error]

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = client_recv_packet()
        exception = exc_info.value

        # Assert
        mock_tcp_socket.recv.assert_called_once_with(TCPNetworkClient.max_size, mocker.sentinel.recv_flags)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet\n")
        assert exception is expected_error

    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_blocking_or_not____closed_client_error(
        self,
        client: TCPNetworkClient[Any, Any],
        client_recv_packet: Callable[[], Any],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        client.close()
        assert client.is_closed()

        # Act
        with pytest.raises(RuntimeError, match=r"^Closed client$"):
            _ = client_recv_packet()

        # Assert
        mock_tcp_socket.settimeout.assert_not_called()
        mock_stream_data_consumer.feed.assert_not_called()
        mock_tcp_socket.recv.assert_not_called()

    @pytest.mark.parametrize(
        ["timeout", "recv_exception"],
        [
            pytest.param(0, BlockingIOError, id="null timeout"),
            pytest.param(123456789, TimeoutError, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.parametrize(
        "return_default",
        [
            pytest.param(False, id="raise TimeoutError"),
            pytest.param(True, id="return given default"),
        ],
    )
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____recv_packet_no_block____timeout(
        self,
        client: TCPNetworkClient[Any, Any],
        timeout: int,
        recv_exception: type[BaseException],
        return_default: bool,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = recv_exception

        # Act & Assert
        if return_default:
            packet = client.recv_packet_no_block(timeout=timeout, default=mocker.sentinel.default_value)
            assert packet is mocker.sentinel.default_value
        else:
            with pytest.raises(TimeoutError, match=r"^recv_packet\(\) timed out$"):
                _ = client.recv_packet_no_block(timeout=timeout)

        mock_tcp_socket.recv.assert_called_once_with(TCPNetworkClient.max_size, mocker.sentinel.recv_flags)
        mock_stream_data_consumer.feed.assert_not_called()

    @pytest.mark.parametrize(
        ["timeout", "recv_exception"],
        [
            pytest.param(0, BlockingIOError, id="null timeout"),
            pytest.param(123456789, TimeoutError, id="strictly positive timeout"),
        ],
    )
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_with_given_timeout(
        self,
        client: TCPNetworkClient[Any, Any],
        timeout: int,
        recv_exception: type[BaseException],
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket_1\npa", b"ck", b"et", b"_2\n", recv_exception]

        # Act
        packets = list(client.iter_received_packets(timeout=timeout))

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [
            mocker.call(TCPNetworkClient.max_size, mocker.sentinel.recv_flags) for _ in range(6)
        ]
        assert mock_stream_data_consumer.feed.mock_calls == [
            mocker.call(b"pac"),
            mocker.call(b"ket_1\npa"),
            mocker.call(b"ck"),
            mocker.call(b"et"),
            mocker.call(b"_2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.parametrize("timeout", [0, 123456789, None], ids=lambda t: f"timeout=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_until_eof(
        self,
        client: TCPNetworkClient[Any, Any],
        timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket_1\npa", b"ck", b"et", b"_2\n", b""]

        # Act
        packets = list(client.iter_received_packets(timeout=timeout))

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [
            mocker.call(TCPNetworkClient.max_size, mocker.sentinel.recv_flags) for _ in range(6)
        ]
        assert mock_stream_data_consumer.feed.mock_calls == [
            mocker.call(b"pac"),
            mocker.call(b"ket_1\npa"),
            mocker.call(b"ck"),
            mocker.call(b"et"),
            mocker.call(b"_2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.parametrize("timeout", [0, 123456789, None], ids=lambda t: f"timeout=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____yields_available_packets_until_error(
        self,
        client: TCPNetworkClient[Any, Any],
        timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"pac", b"ket_1\npa", b"ck", b"et", b"_2\n", OSError]

        # Act
        packets = list(client.iter_received_packets(timeout=timeout))

        # Assert
        assert mock_tcp_socket.recv.mock_calls == [
            mocker.call(TCPNetworkClient.max_size, mocker.sentinel.recv_flags) for _ in range(6)
        ]
        assert mock_stream_data_consumer.feed.mock_calls == [
            mocker.call(b"pac"),
            mocker.call(b"ket_1\npa"),
            mocker.call(b"ck"),
            mocker.call(b"et"),
            mocker.call(b"_2\n"),
        ]
        assert packets == [mocker.sentinel.packet_1, mocker.sentinel.packet_2]

    @pytest.mark.parametrize("timeout", [0, 123456789, None], ids=lambda t: f"timeout=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____protocol_parse_error(
        self,
        client: TCPNetworkClient[Any, Any],
        timeout: int | None,
        mock_stream_data_consumer: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.protocol import StreamProtocolParseError

        mock_stream_data_consumer.__next__.side_effect = StreamProtocolParseError(b"", "deserialization", "Sorry")

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = next(client.iter_received_packets(timeout=timeout))
        exception = exc_info.value

        # Assert
        assert exception is mock_stream_data_consumer.__next__.side_effect

    @pytest.mark.parametrize("timeout", [0, 123456789, None], ids=lambda t: f"timeout=={t}")
    @pytest.mark.parametrize("several_generators", [False, True], ids=lambda t: f"several_generators=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____avoid_unnecessary_socket_recv_call(
        self,
        client: TCPNetworkClient[Any, Any],
        several_generators: bool,
        timeout: int | None,
        mock_tcp_socket: MagicMock,
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        if several_generators:
            packet_1 = next(client.iter_received_packets(timeout=timeout))
            packet_2 = next(client.iter_received_packets(timeout=timeout))
        else:
            iterator = client.iter_received_packets(timeout=timeout)
            packet_1 = next(iterator)
            packet_2 = next(iterator)

        # Assert
        mock_tcp_socket.recv.assert_called_once_with(TCPNetworkClient.max_size, mocker.sentinel.recv_flags)
        mock_stream_data_consumer.feed.assert_called_once_with(b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.parametrize("timeout", [0, 123456789, None], ids=lambda t: f"timeout=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____release_internal_lock_before_yield(
        self,
        client: TCPNetworkClient[Any, Any],
        timeout: int | None,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from threading import RLock

        mock_acquire = mocker.patch.object(RLock, "acquire", return_value=True)
        mock_release = mocker.patch.object(RLock, "release", return_value=None)
        mock_tcp_socket.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act & Assert
        iterator = client.iter_received_packets(timeout=timeout)
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

    @pytest.mark.parametrize("timeout", [0, 123456789, None], ids=lambda t: f"timeout=={t}")
    @pytest.mark.usefixtures("setup_consumer_mock")
    def test____iter_received_packets____closed_client_during_iteration(
        self,
        client: TCPNetworkClient[Any, Any],
        timeout: int | None,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_tcp_socket.recv.side_effect = [b"packet_1\n"]

        # Act & Assert
        iterator = client.iter_received_packets(timeout=timeout)
        packet_1 = next(iterator)
        assert packet_1 is mocker.sentinel.packet_1
        client.close()
        assert client.is_closed()
        with pytest.raises(RuntimeError, match=r"^Closed client$"):
            _ = next(iterator)

    def test____get_buffer____return_unconsumed_data(
        self,
        client: TCPNetworkClient[Any, Any],
        mock_stream_data_consumer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_data_consumer.get_unconsumed_data.return_value = mocker.sentinel.data

        # Act
        data: bytes = client._get_buffer()

        # Assert
        mock_stream_data_consumer.get_unconsumed_data.assert_called_once_with()
        assert data is mocker.sentinel.data
