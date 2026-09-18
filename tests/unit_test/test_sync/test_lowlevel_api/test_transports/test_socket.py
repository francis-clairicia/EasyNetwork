# mypy: disable-error-code=func-returns-value

from __future__ import annotations

import contextlib
import dataclasses
import errno
import math
import os
import ssl
from collections.abc import Buffer, Callable, Generator, Iterable
from concurrent.futures import Executor, Future
from socket import AF_INET, SHUT_RDWR, SHUT_WR
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import TypedAttributeLookupError, UnsupportedOperation
from easynetwork.lowlevel.api_sync.transports.base_selector import SelectorBaseTransport, WouldBlockOnRead, WouldBlockOnWrite
from easynetwork.lowlevel.api_sync.transports.socket import (
    SocketDatagramListener,
    SocketDatagramTransport,
    SocketStreamListener,
    SocketStreamTransport,
    SSLStreamTransport,
)
from easynetwork.lowlevel.constants import (
    CLOSED_SOCKET_ERRNOS,
    IGNORABLE_ACCEPT_ERRNOS,
    MAX_DATAGRAM_BUFSIZE,
    NOT_CONNECTED_SOCKET_ERRNOS,
    SSL_HANDSHAKE_TIMEOUT,
)
from easynetwork.lowlevel.socket import SocketAttribute, SocketProxy, TLSAttribute

import pytest

from .....tools import PlatformMarkers
from ...._utils import executor_submit_default_side_effect, make_executor_submit_side_effect
from ....base import BaseTestSocketTransport, MixinTestSocketSendMSG

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


def _retry_side_effect(self: SelectorBaseTransport, callback: Callable[[], Any], timeout: float) -> tuple[Any, float]:
    while True:
        try:
            return callback(), timeout
        except WouldBlockOnRead:
            self.read_fileno()
        except WouldBlockOnWrite:
            self.write_fileno()


_SUPPORTS_ANCILLARY = ("AF_UNIX",)
_ANCILLARY_UNSUPPORTED = ("AF_INET",)


class TestSocketStreamTransport(BaseTestSocketTransport, MixinTestSocketSendMSG):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_transport_retry(mocker: MockerFixture) -> MagicMock:
        mock_transport_retry = mocker.patch.object(SocketStreamTransport, "_retry", autospec=True)
        mock_transport_retry.side_effect = _retry_side_effect
        return mock_transport_retry

    @pytest.fixture
    @staticmethod
    def mock_transport_send_all(mocker: MockerFixture) -> MagicMock:
        mock_transport_send_all = mocker.patch.object(SocketStreamTransport, "send_all", spec=lambda data, timeout: None)
        mock_transport_send_all.return_value = None
        return mock_transport_send_all

    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @classmethod
    def mock_stream_socket(
        cls,
        socket_family_name: str,
        socket_fileno: int,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_tcp_socket_factory: Callable[[int, int], MagicMock],
        mock_unix_stream_socket_factory: Callable[[int], MagicMock],
    ) -> MagicMock:
        mock_stream_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_stream_socket = mock_tcp_socket_factory(AF_INET, socket_fileno)
            case "AF_UNIX":
                mock_stream_socket = mock_unix_stream_socket_factory(socket_fileno)
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_stream_socket, mock_stream_socket.family, local_address)
        cls.set_remote_address_to_socket_mock(mock_stream_socket, mock_stream_socket.family, remote_address)

        if hasattr(mock_stream_socket, "sendmsg"):
            mock_stream_socket.sendmsg.side_effect = lambda buffers, *args: sum(memoryview(v).nbytes for v in buffers)
        return mock_stream_socket

    @pytest.fixture
    @staticmethod
    def transport(mock_stream_socket: MagicMock) -> Generator[SocketStreamTransport]:
        transport = SocketStreamTransport(mock_stream_socket, math.inf)
        mock_stream_socket.reset_mock()
        with transport:
            yield transport

    def test____dunder_init____default(
        self,
        request: pytest.FixtureRequest,
        mock_stream_socket: MagicMock,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SocketStreamTransport(mock_stream_socket, math.inf, selector_factory=mock_selector_factory)
        request.addfinalizer(transport.close)

        # Assert
        assert transport._retry_interval is math.inf
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_stream_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        assert transport.extra(SocketAttribute.peername) == remote_address

        mock_stream_socket.getsockname.assert_called_once_with()
        mock_stream_socket.getpeername.assert_called()
        mock_stream_socket.setblocking.assert_called_once_with(False)
        mock_stream_socket.settimeout.assert_not_called()

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SocketStreamTransport(mock_ssl_socket, math.inf)

    def test____dunder_init____forbid_non_stream_sockets(
        self,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = SocketStreamTransport(mock_udp_socket, math.inf)

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        transport = SocketStreamTransport(mock_stream_socket, math.inf)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_stream_socket.close.assert_called()

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SocketStreamTransport,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    @pytest.mark.parametrize("error", [None, OSError])
    def test____abort____default(
        self,
        error: type[OSError] | None,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if error is not None:
            mock_stream_socket.shutdown.side_effect = error

        # Act
        transport.abort()

        # Assert
        assert mock_stream_socket.mock_calls == [mocker.call.shutdown(SHUT_RDWR), mocker.call.close()]

    @pytest.mark.parametrize("error", [None, OSError])
    def test____close____default(
        self,
        error: type[OSError] | None,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if error is not None:
            mock_stream_socket.shutdown.side_effect = error

        # Act
        transport.close()

        # Assert
        assert mock_stream_socket.mock_calls == [mocker.call.shutdown(SHUT_RDWR), mocker.call.close()]

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____read_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SocketStreamTransport,
    ) -> None:
        # Arrange

        # Act
        fd = transport.read_fileno()

        # Assert
        assert fd == socket_fileno

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____write_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SocketStreamTransport,
    ) -> None:
        # Arrange

        # Act
        fd = transport.write_fileno()

        # Assert
        assert fd == socket_fileno

    def test____recv_noblock____default(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recv.return_value = mocker.sentinel.bytes

        # Act
        result = transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_stream_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_stream_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____recv_noblock____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recv.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_stream_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_stream_socket.fileno.assert_not_called()

    def test____recv_noblock_into____default(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recv_into.return_value = mocker.sentinel.nb_bytes_written

        # Act
        result = transport.recv_noblock_into(mocker.sentinel.buffer)

        # Assert
        mock_stream_socket.recv_into.assert_called_once_with(mocker.sentinel.buffer)
        mock_stream_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.nb_bytes_written

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____recv_noblock_into____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recv_into.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock_into(mocker.sentinel.buffer)

        # Assert
        mock_stream_socket.recv_into.assert_called_once_with(mocker.sentinel.buffer)
        mock_stream_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    def test____recv_noblock_with_ancillary____default(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recvmsg.return_value = (mocker.sentinel.bytes, mocker.sentinel.ancdata, 0, mocker.sentinel.addr)

        # Act
        result, ancdata = transport.recv_noblock_with_ancillary(mocker.sentinel.bufsize, mocker.sentinel.ancbufsize)

        # Assert
        mock_stream_socket.recvmsg.assert_called_once_with(mocker.sentinel.bufsize, mocker.sentinel.ancbufsize)
        mock_stream_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes
        assert ancdata is mocker.sentinel.ancdata

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _ANCILLARY_UNSUPPORTED, indirect=True)
    def test____recv_noblock_with_ancillary____socket_family_unsupported(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recvmsg.return_value = (mocker.sentinel.bytes, mocker.sentinel.ancdata, 0, mocker.sentinel.addr)

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.recv_noblock_with_ancillary(mocker.sentinel.bufsize, mocker.sentinel.ancbufsize)

        # Assert
        mock_stream_socket.recvmsg.assert_not_called()
        mock_stream_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____recv_noblock_with_ancillary____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recvmsg.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock_with_ancillary(mocker.sentinel.bufsize, mocker.sentinel.ancbufsize)

        # Assert
        mock_stream_socket.recvmsg.assert_called_once_with(mocker.sentinel.bufsize, mocker.sentinel.ancbufsize)
        mock_stream_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg_into
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    def test____recv_noblock_with_ancillary_into____default(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recvmsg_into.return_value = (
            mocker.sentinel.nb_bytes_written,
            mocker.sentinel.ancdata,
            0,
            mocker.sentinel.addr,
        )

        # Act
        result, ancdata = transport.recv_noblock_with_ancillary_into(mocker.sentinel.buffer, mocker.sentinel.ancbufsize)

        # Assert
        mock_stream_socket.recvmsg_into.assert_called_once_with([mocker.sentinel.buffer], mocker.sentinel.ancbufsize)
        mock_stream_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.nb_bytes_written
        assert ancdata is mocker.sentinel.ancdata

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _ANCILLARY_UNSUPPORTED, indirect=True)
    def test____recv_noblock_with_ancillary_into____socket_family_unsupported(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recvmsg_into.return_value = (
            mocker.sentinel.nb_bytes_written,
            mocker.sentinel.ancdata,
            0,
            mocker.sentinel.addr,
        )

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.recv_noblock_with_ancillary_into(mocker.sentinel.buffer, mocker.sentinel.ancbufsize)

        # Assert
        mock_stream_socket.recvmsg_into.assert_not_called()
        mock_stream_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg_into
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____recv_noblock_with_ancillary_into____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.recvmsg_into.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock_with_ancillary_into(mocker.sentinel.buffer, mocker.sentinel.ancbufsize)

        # Assert
        mock_stream_socket.recvmsg_into.assert_called_once_with([mocker.sentinel.buffer], mocker.sentinel.ancbufsize)
        mock_stream_socket.fileno.assert_not_called()

    def test____send_noblock____default(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.send.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_stream_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_stream_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.nb_bytes_sent

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_noblock____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.send.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite):
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_stream_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_stream_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    def test____send_all_noblock_with_ancillary____default(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer], *args: Any) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_noblock_with_ancillary(iter([b"data", b"to", b"send"]), mocker.sentinel.ancdata)

        # Assert
        mock_stream_socket.sendmsg.assert_called_once_with(mocker.ANY, mocker.sentinel.ancdata)
        mock_stream_socket.fileno.assert_not_called()
        assert chunks == [[b"data", b"to", b"send"]]

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _ANCILLARY_UNSUPPORTED, indirect=True)
    def test____send_all_noblock_with_ancillary____socket_family_unsupported(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer], *args: Any) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.send_all_noblock_with_ancillary(iter([b"data", b"to", b"send"]), mocker.sentinel.ancdata)

        # Assert
        mock_stream_socket.sendmsg.assert_not_called()
        mock_stream_socket.fileno.assert_not_called()
        assert chunks == []

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    def test____send_all_noblock_with_ancillary____message_too_long(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer], *args: Any) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return min(sum(memoryview(v).nbytes for v in buffers), 3)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        with pytest.raises(OSError, check=lambda exc: exc.errno == errno.EMSGSIZE):
            transport.send_all_noblock_with_ancillary(iter([b"data", b"to", b"send"]), mocker.sentinel.ancdata)

        # Assert
        mock_stream_socket.sendmsg.assert_called_once_with(mocker.ANY, mocker.sentinel.ancdata)
        mock_stream_socket.fileno.assert_not_called()
        assert chunks == [[b"data", b"to", b"send"]]

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.usefixtures("SC_IOV_MAX")
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("SC_IOV_MAX", [2], ids=lambda p: f"SC_IOV_MAX__{p}", indirect=True)
    def test____send_all_noblock_with_ancillary____message_too_long____nb_buffers_greather_than_SC_IOV_MAX(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer], *args: Any) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        with pytest.raises(OSError, check=lambda exc: exc.errno == errno.EMSGSIZE):
            transport.send_all_noblock_with_ancillary(iter([b"a", b"b", b"c", b"d"]), mocker.sentinel.ancdata)

        # Assert
        mock_stream_socket.sendmsg.assert_called_once_with(mocker.ANY, mocker.sentinel.ancdata)
        mock_stream_socket.fileno.assert_not_called()
        assert chunks == [[b"a", b"b"]]

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_all_noblock_with_ancillary____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket.sendmsg.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite):
            transport.send_all_noblock_with_ancillary(iter([b"data", b"to", b"send"]), mocker.sentinel.ancdata)

        # Assert
        mock_stream_socket.sendmsg.assert_called_once_with(mocker.ANY, mocker.sentinel.ancdata)
        mock_stream_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("data_is_iterator", [False, True], ids=lambda p: f"data_is_iterator__{p}")
    @pytest.mark.parametrize("ancillary_data_is_iterator", [False, True], ids=lambda p: f"ancillary_data_is_iterator__{p}")
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_all_with_ancillary____correctly_handle_iterables(
        self,
        error: type[OSError],
        data_is_iterator: bool,
        ancillary_data_is_iterator: bool,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        to_raise: list[type[OSError]] = [error]
        chunks: list[list[bytes]] = []
        ancillary_data_sent: list[list[Any]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer], ancdata: Iterable[Any]) -> int:
            buffers = list(buffers)
            ancdata = list(ancdata)
            if to_raise:
                raise to_raise.pop(0)
            chunks.append(list(map(bytes, buffers)))
            ancillary_data_sent.append(ancdata)
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        data: Iterable[bytes] = [b"data"]
        if data_is_iterator:
            data = iter(data)
        ancillary_data: Iterable[Any] = [mocker.sentinel.ancdata]
        if ancillary_data_is_iterator:
            ancillary_data = iter(ancillary_data)

        # Act
        transport.send_all_with_ancillary(data, ancillary_data, 123456)

        # Assert
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 123456)
        assert mock_stream_socket.sendmsg.call_count == 2
        assert chunks == [[b"data"]]
        assert ancillary_data_sent == [[mocker.sentinel.ancdata]]

    @PlatformMarkers.supports_socket_sendmsg
    def test____send_all_from_iterable____use_socket_sendmsg_when_available(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mock_transport_send_all: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_from_iterable(iter([b"data", b"to", b"send"]), 123456)

        # Assert
        mock_transport_send_all.assert_not_called()
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 123456)
        mock_stream_socket.sendmsg.assert_called_once()
        assert chunks == [[b"data", b"to", b"send"]]

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.usefixtures("SC_IOV_MAX")
    @pytest.mark.parametrize("SC_IOV_MAX", [2], ids=lambda p: f"SC_IOV_MAX__{p}", indirect=True)
    def test____send_all_from_iterable____use_socket_sendmsg____nb_buffers_greather_than_SC_IOV_MAX(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_from_iterable(iter([b"a", b"b", b"c", b"d", b"e"]), 123456)

        # Assert
        assert mock_stream_socket.sendmsg.call_count == 3
        assert chunks == [
            [b"a", b"b"],
            [b"c", b"d"],
            [b"e"],
        ]

    @PlatformMarkers.supports_socket_sendmsg
    def test____send_all_from_iterable____use_socket_sendmsg____adjust_leftover_buffer(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return min(sum(memoryview(v).nbytes for v in buffers), 3)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_from_iterable(iter([b"abcd", b"efg", b"hijkl", b"mnop"]), 123456)

        # Assert
        assert mock_stream_socket.sendmsg.call_count == 6
        assert chunks == [
            [b"abcd", b"efg", b"hijkl", b"mnop"],
            [b"d", b"efg", b"hijkl", b"mnop"],
            [b"g", b"hijkl", b"mnop"],
            [b"jkl", b"mnop"],
            [b"mnop"],
            [b"p"],
        ]

    @PlatformMarkers.supports_socket_sendmsg
    def test____send_all_from_iterable____use_socket_sendmsg____empty_buffer_list(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mock_transport_send_all: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_from_iterable(iter([]), 123456)

        # Assert
        mock_transport_send_all.assert_not_called()
        assert mock_stream_socket.sendmsg.call_count == 1
        assert chunks == [[]]

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_all_from_iterable____use_socket_sendmsg____blocking_error(
        self,
        error: type[OSError],
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mock_transport_send_all: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        to_raise: list[type[OSError]] = [error]
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer]) -> int:
            if to_raise:
                raise to_raise.pop(0)
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(memoryview(v).nbytes for v in buffers)

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_from_iterable(iter([b"data"]), 123456)

        # Assert
        mock_transport_send_all.assert_not_called()
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 123456)
        assert mock_stream_socket.sendmsg.call_count == 2
        assert chunks == [[b"data"]]

    @PlatformMarkers.socket_sendmsg_unsupported
    def test____send_all_from_iterable____fallback_to_send_all____sendmsg_unavailable(
        self,
        transport: SocketStreamTransport,
        mock_transport_retry: MagicMock,
        mock_transport_send_all: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.send_all_from_iterable(iter([b"data", b"to", b"send"]), 123456)

        # Assert
        mock_transport_retry.assert_not_called()
        assert mock_transport_send_all.call_args_list == [
            mocker.call(b"".join([b"data", b"to", b"send"]), mocker.ANY),
        ]

    @pytest.mark.parametrize(
        "os_error",
        [pytest.param(None)] + list(map(pytest.param, sorted(NOT_CONNECTED_SOCKET_ERRNOS | CLOSED_SOCKET_ERRNOS))),
        ids=lambda p: errno.errorcode.get(p, repr(p)),
    )
    def test____send_eof____default(
        self,
        os_error: int | None,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        if os_error is not None:
            mock_stream_socket.shutdown.side_effect = OSError(os_error, os.strerror(os_error))

        # Act
        transport.send_eof()

        # Assert
        mock_stream_socket.shutdown.assert_called_once_with(SHUT_WR)

    def test____send_eof____os_error(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_socket.shutdown.side_effect = OSError

        # Act & Assert
        with pytest.raises(OSError):
            transport.send_eof()

    def test____send_eof____transport_closed(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        transport.close()
        mock_stream_socket.reset_mock()

        # Act
        transport.send_eof()

        # Assert
        mock_stream_socket.shutdown.assert_not_called()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method", "os_error"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", errno.EINVAL, id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", errno.ENOTCONN, id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_raises_OSError(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        os_error: int,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_stream_socket, called_socket_method)
        mock_get_address.side_effect = OSError(os_error, os.strerror(os_error))

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_called_once()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_on_closed_socket(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_stream_socket, called_socket_method)
        transport.close()
        assert mock_stream_socket.fileno.return_value == -1

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_not_called()


class TestSSLStreamTransport:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_transport_retry(mocker: MockerFixture) -> MagicMock:
        mock_transport_retry = mocker.patch.object(SSLStreamTransport, "_retry", autospec=True)
        mock_transport_retry.side_effect = _retry_side_effect
        return mock_transport_retry

    @pytest.fixture
    @staticmethod
    def mock_transport_send_all(mocker: MockerFixture) -> MagicMock:
        mock_transport_send_all = mocker.patch.object(SSLStreamTransport, "send_all", spec=lambda data, timeout: None)
        mock_transport_send_all.return_value = None
        return mock_transport_send_all

    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @staticmethod
    def mock_ssl_socket(mock_ssl_socket: MagicMock, socket_fileno: int) -> MagicMock:
        mock_ssl_socket.fileno.return_value = socket_fileno
        mock_ssl_socket.do_handshake.side_effect = [ssl.SSLWantReadError, ssl.SSLWantWriteError, None]
        mock_ssl_socket.unwrap.side_effect = [ssl.SSLWantReadError, ssl.SSLWantWriteError, None]

        mock_ssl_socket.getsockname.return_value = ("local_address", 11111)
        mock_ssl_socket.getpeername.return_value = ("remote_address", 12345)

        return mock_ssl_socket

    @pytest.fixture
    @staticmethod
    def mock_ssl_context(mock_ssl_context: MagicMock, mock_ssl_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock_ssl_context.wrap_socket.return_value = mock_ssl_socket
        mock_ssl_socket.context = mock_ssl_context
        mock_ssl_socket.getpeercert.return_value = mocker.sentinel.peercert
        mock_ssl_socket.cipher.return_value = mocker.sentinel.cipher
        mock_ssl_socket.compression.return_value = mocker.sentinel.compression
        mock_ssl_socket.version.return_value = mocker.sentinel.tls_version
        return mock_ssl_context

    @pytest.fixture
    @staticmethod
    def standard_compatible(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param", True)

    @pytest.fixture
    @staticmethod
    def transport(
        standard_compatible: bool,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
        mock_transport_retry: MagicMock,
    ) -> Generator[SSLStreamTransport]:
        transport = SSLStreamTransport(
            mock_tcp_socket,
            mock_ssl_context,
            handshake_timeout=123456789,
            shutdown_timeout=987654321,
            retry_interval=math.inf,
            standard_compatible=standard_compatible,
        )
        mock_tcp_socket.reset_mock()
        mock_ssl_socket.reset_mock()
        mock_transport_retry.reset_mock()
        with transport:
            yield transport

    def test____dunder_init____default(
        self,
        request: pytest.FixtureRequest,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SSLStreamTransport(
            mock_tcp_socket,
            mock_ssl_context,
            retry_interval=math.inf,
            server_hostname=mocker.sentinel.server_hostname,
            selector_factory=mock_selector_factory,
        )
        request.addfinalizer(transport.close)

        # Assert
        assert transport._retry_interval is math.inf
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_tcp_socket.family
        assert transport.extra(SocketAttribute.sockname) == ("local_address", 11111)
        assert transport.extra(SocketAttribute.peername) == ("remote_address", 12345)

        assert transport.extra(TLSAttribute.sslcontext) is mock_ssl_context
        assert transport.extra(TLSAttribute.peercert) is mocker.sentinel.peercert
        assert transport.extra(TLSAttribute.cipher) is mocker.sentinel.cipher
        assert transport.extra(TLSAttribute.compression) is mocker.sentinel.compression
        assert transport.extra(TLSAttribute.tls_version) is mocker.sentinel.tls_version
        assert transport.extra(TLSAttribute.standard_compatible) is True
        assert mock_tcp_socket.mock_calls == []

        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=False,
            server_hostname=mocker.sentinel.server_hostname,
            suppress_ragged_eofs=False,
            do_handshake_on_connect=False,
            session=None,
        )

        mock_ssl_socket.getsockname.assert_called_once_with()
        mock_ssl_socket.getpeername.assert_called()
        mock_ssl_socket.setblocking.assert_called_once_with(False)
        mock_ssl_socket.settimeout.assert_not_called()
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, SSL_HANDSHAKE_TIMEOUT)
        assert mock_ssl_socket.do_handshake.call_args_list == [mocker.call() for _ in range(3)]

    @pytest.mark.parametrize("standard_compatible", [False, True], ids=lambda p: f"standard_compatible__{p}", indirect=True)
    def test____dunder_init____ssl_context_parameters(
        self,
        request: pytest.FixtureRequest,
        standard_compatible: bool,
        mock_tcp_socket: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport = SSLStreamTransport(
            mock_tcp_socket,
            mock_ssl_context,
            handshake_timeout=123456789,
            shutdown_timeout=987654321,
            retry_interval=math.inf,
            server_side=mocker.sentinel.server_side,
            server_hostname=mocker.sentinel.server_hostname,
            standard_compatible=standard_compatible,
            session=mocker.sentinel.ssl_session,
        )
        request.addfinalizer(transport.close)

        # Assert
        mock_ssl_context.wrap_socket.assert_called_once_with(
            mock_tcp_socket,
            server_side=mocker.sentinel.server_side,
            server_hostname=mocker.sentinel.server_hostname,
            suppress_ragged_eofs=not standard_compatible,
            do_handshake_on_connect=False,
            session=mocker.sentinel.ssl_session,
        )
        assert transport.extra(TLSAttribute.standard_compatible) is standard_compatible

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SSLStreamTransport(mock_ssl_socket, mock_ssl_context, math.inf)

    def test____dunder_init____forbid_non_stream_sockets(
        self,
        mock_udp_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = SSLStreamTransport(mock_udp_socket, mock_ssl_context, math.inf)

    @pytest.mark.parametrize("timeout", [math.nan, -4], ids=repr)
    @pytest.mark.parametrize("parameter", ["handshake_timeout", "shutdown_timeout", "retry_interval"])
    def test____dunder_init____invalid_timeout(
        self,
        timeout: float,
        parameter: str,
        mock_tcp_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange
        kwargs: dict[str, Any] = {
            "retry_interval": math.inf,
        }
        kwargs[parameter] = timeout

        # Act & Assert
        with pytest.raises(ValueError):
            _ = SSLStreamTransport(mock_tcp_socket, mock_ssl_context, **kwargs)

    def test____dunder_init____handshake_error(
        self,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_socket.do_handshake.side_effect = ConnectionError

        # Act & Assert
        with pytest.raises(ConnectionError):
            _ = SSLStreamTransport(mock_tcp_socket, mock_ssl_context, math.inf)

        mock_ssl_socket.close.assert_called_once_with()

    @pytest.mark.usefixtures("simulate_no_ssl_module")
    def test____dunder_init____ssl_module_not_available(
        self,
        mock_tcp_socket: MagicMock,
        mock_ssl_context: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^stdlib ssl module not available$"):
            _ = SSLStreamTransport(mock_tcp_socket, mock_ssl_context, math.inf)

    def test____dunder_del____ResourceWarning(
        self,
        mock_tcp_socket: MagicMock,
        mock_ssl_socket: MagicMock,
        mock_ssl_context: MagicMock,
        mock_transport_retry: MagicMock,
    ) -> None:
        # Arrange
        transport = SSLStreamTransport(mock_tcp_socket, mock_ssl_context, math.inf)
        mock_transport_retry.reset_mock()

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_ssl_socket.close.assert_called()

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SSLStreamTransport,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    @pytest.mark.parametrize("shutdown_error", [None, OSError])
    @pytest.mark.parametrize("standard_compatible", [False, True], ids=lambda p: f"standard_compatible__{p}", indirect=True)
    def test____abort____default(
        self,
        shutdown_error: type[OSError] | None,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if shutdown_error is not None:
            mock_ssl_socket.shutdown.side_effect = shutdown_error
        mock_transport_retry.reset_mock()

        # Act
        transport.abort()

        # Assert
        assert mock_ssl_socket.mock_calls == [
            mocker.call.shutdown(SHUT_RDWR),
            mocker.call.close(),
        ]
        mock_transport_retry.assert_not_called()

    @pytest.mark.parametrize("unwrap_error", [None, OSError])
    @pytest.mark.parametrize("shutdown_error", [None, OSError])
    @pytest.mark.parametrize("standard_compatible", [False, True], ids=lambda p: f"standard_compatible__{p}", indirect=True)
    def test____close____default(
        self,
        standard_compatible: bool,
        unwrap_error: type[OSError] | None,
        shutdown_error: type[OSError] | None,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if unwrap_error is not None:
            mock_ssl_socket.unwrap.side_effect = [ssl.SSLWantReadError, ssl.SSLWantWriteError, unwrap_error]
        if shutdown_error is not None:
            mock_ssl_socket.shutdown.side_effect = shutdown_error
        mock_transport_retry.reset_mock()

        # Act
        transport.close()

        # Assert
        if standard_compatible:
            assert mock_ssl_socket.mock_calls == [
                mocker.call.fileno(),
                mocker.call.unwrap(),
                mocker.call.fileno(),
                mocker.call.unwrap(),
                mocker.call.fileno(),
                mocker.call.unwrap(),
                mocker.call.shutdown(SHUT_RDWR),
                mocker.call.close(),
            ]
            mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 987654321)
        else:
            assert mock_ssl_socket.mock_calls == [
                mocker.call.shutdown(SHUT_RDWR),
                mocker.call.close(),
            ]
            mock_transport_retry.assert_not_called()

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____read_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SSLStreamTransport,
    ) -> None:
        # Arrange

        # Act
        fd = transport.read_fileno()

        # Assert
        assert fd == socket_fileno

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____write_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SSLStreamTransport,
    ) -> None:
        # Arrange

        # Act
        fd = transport.write_fileno()

        # Assert
        assert fd == socket_fileno

    def test____recv_noblock____default(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv.return_value = mocker.sentinel.bytes

        # Act
        result = transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_ssl_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_ssl_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes

    @pytest.mark.parametrize(
        ["error", "expected_blocking_error"],
        [
            pytest.param(ssl.SSLWantReadError, WouldBlockOnRead),
            pytest.param(ssl.SSLSyscallError, WouldBlockOnRead),
            pytest.param(ssl.SSLWantWriteError, WouldBlockOnWrite),
        ],
    )
    def test____recv_noblock____blocking_error(
        self,
        error: type[OSError],
        expected_blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv.side_effect = error

        # Act
        with pytest.raises(expected_blocking_error):
            transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_ssl_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_ssl_socket.fileno.assert_not_called()

    def test____recv_noblock____SSLZeroReturnError(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv.side_effect = ssl.SSLZeroReturnError

        # Act
        result = transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_ssl_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_ssl_socket.fileno.assert_not_called()
        assert result == b""

    def test____recv_noblock_into____default(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv_into.return_value = mocker.sentinel.nb_bytes_written

        # Act
        result = transport.recv_noblock_into(mocker.sentinel.buffer)

        # Assert
        mock_ssl_socket.recv_into.assert_called_once_with(mocker.sentinel.buffer)
        mock_ssl_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.nb_bytes_written

    @pytest.mark.parametrize(
        ["error", "expected_blocking_error"],
        [
            pytest.param(ssl.SSLWantReadError, WouldBlockOnRead),
            pytest.param(ssl.SSLSyscallError, WouldBlockOnRead),
            pytest.param(ssl.SSLWantWriteError, WouldBlockOnWrite),
        ],
    )
    def test____recv_noblock_into____blocking_error(
        self,
        error: type[OSError],
        expected_blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv_into.side_effect = error

        # Act
        with pytest.raises(expected_blocking_error):
            transport.recv_noblock_into(mocker.sentinel.buffer)

        # Assert
        mock_ssl_socket.recv_into.assert_called_once_with(mocker.sentinel.buffer)
        mock_ssl_socket.fileno.assert_not_called()

    def test____recv_noblock_into____SSLZeroReturnError(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.recv_into.side_effect = ssl.SSLZeroReturnError

        # Act
        result = transport.recv_noblock_into(mocker.sentinel.buffer)

        # Assert
        mock_ssl_socket.recv_into.assert_called_once_with(mocker.sentinel.buffer)
        mock_ssl_socket.fileno.assert_not_called()
        assert result == 0

    def test____send_noblock____default(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.send.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_ssl_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_ssl_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.nb_bytes_sent

    @pytest.mark.parametrize(
        ["error", "expected_blocking_error"],
        [
            pytest.param(ssl.SSLWantReadError, WouldBlockOnRead),
            pytest.param(ssl.SSLSyscallError, WouldBlockOnRead),
            pytest.param(ssl.SSLWantWriteError, WouldBlockOnWrite),
        ],
    )
    def test____send_noblock____blocking_error(
        self,
        error: type[OSError],
        expected_blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.send.side_effect = error

        # Act
        with pytest.raises(expected_blocking_error):
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_ssl_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_ssl_socket.fileno.assert_not_called()

    def test____send_noblock____SSLZeroReturnError(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_ssl_socket.send.side_effect = ssl.SSLZeroReturnError

        # Act
        with pytest.raises(ConnectionError) as exc_info:
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_ssl_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_ssl_socket.fileno.assert_not_called()
        assert exc_info.value.errno == errno.ECONNRESET

    def test____send_all_from_iterable____concatenate_data(
        self,
        transport: SSLStreamTransport,
        mock_transport_send_all: MagicMock,
    ) -> None:
        # Arrange

        # Act
        transport.send_all_from_iterable(iter([b"data", b" to ", b"send"]), 123456)

        # Assert
        mock_transport_send_all.assert_called_once_with(b"data to send", 123456)

    def test____send_eof____default(
        self,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.send_eof()

        # Assert
        mock_ssl_socket.shutdown.assert_not_called()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method", "os_error"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", errno.EINVAL, id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", errno.ENOTCONN, id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_raises_OSError(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        os_error: int,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_ssl_socket, called_socket_method)
        mock_get_address.side_effect = OSError(os_error, os.strerror(os_error))

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_called_once()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_on_closed_socket(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_ssl_socket, called_socket_method)
        transport.close()
        assert mock_ssl_socket.fileno.return_value == -1

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_not_called()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method"],
        [
            pytest.param(TLSAttribute.peercert, "getpeercert", id="socket.getpeercert()"),
            pytest.param(TLSAttribute.cipher, "cipher", id="socket.cipher()"),
            pytest.param(TLSAttribute.compression, "compression", id="socket.compression()"),
            pytest.param(TLSAttribute.tls_version, "version", id="socket.version()"),
        ],
    )
    def test____extra_attributes____ssl_object_values_not_available(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        transport: SSLStreamTransport,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_value: MagicMock = getattr(mock_ssl_socket, called_socket_method)
        mock_get_value.return_value = None

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_value.assert_called_once()


class TestSocketDatagramTransport(BaseTestSocketTransport):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_transport_retry(mocker: MockerFixture) -> MagicMock:
        mock_transport_retry = mocker.patch.object(SocketDatagramTransport, "_retry", autospec=True)
        mock_transport_retry.side_effect = _retry_side_effect
        return mock_transport_retry

    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @classmethod
    def mock_datagram_socket(
        cls,
        socket_family_name: str,
        socket_fileno: int,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_udp_socket_factory: Callable[[int, int], MagicMock],
        mock_unix_datagram_socket_factory: Callable[[int], MagicMock],
    ) -> MagicMock:
        mock_datagram_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_datagram_socket = mock_udp_socket_factory(AF_INET, socket_fileno)
            case "AF_UNIX":
                mock_datagram_socket = mock_unix_datagram_socket_factory(socket_fileno)
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_datagram_socket, mock_datagram_socket.family, local_address)
        cls.set_remote_address_to_socket_mock(mock_datagram_socket, mock_datagram_socket.family, remote_address)

        return mock_datagram_socket

    @pytest.fixture
    @staticmethod
    def max_datagram_size(request: pytest.FixtureRequest) -> int | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def transport(mock_datagram_socket: MagicMock, max_datagram_size: int | None) -> Generator[SocketDatagramTransport]:
        if max_datagram_size is None:
            transport = SocketDatagramTransport(mock_datagram_socket, math.inf)
        else:
            transport = SocketDatagramTransport(mock_datagram_socket, math.inf, max_datagram_size=max_datagram_size)
        mock_datagram_socket.reset_mock()
        with transport:
            yield transport

    def test____dunder_init____default(
        self,
        request: pytest.FixtureRequest,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SocketDatagramTransport(mock_datagram_socket, math.inf, selector_factory=mock_selector_factory)
        request.addfinalizer(transport.close)

        # Assert
        assert transport._retry_interval is math.inf
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_datagram_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        assert transport.extra(SocketAttribute.peername) == remote_address

        mock_datagram_socket.getsockname.assert_called_once_with()
        mock_datagram_socket.getpeername.assert_called()
        mock_datagram_socket.setblocking.assert_called_once_with(False)
        mock_datagram_socket.settimeout.assert_not_called()

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SocketDatagramTransport(mock_ssl_socket, math.inf)

    def test____dunder_init____forbid_non_datagram_sockets(
        self,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = SocketDatagramTransport(mock_tcp_socket, math.inf)

    @pytest.mark.parametrize("max_datagram_size", [0, -42], ids=lambda p: f"max_datagram_size__{p}")
    def test____dunder_init____invalid_datagram_size(
        self,
        max_datagram_size: int,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^max_datagram_size must not be <= 0$"):
            _ = SocketDatagramTransport(mock_datagram_socket, math.inf, max_datagram_size=max_datagram_size)

    def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        transport = SocketDatagramTransport(mock_datagram_socket, math.inf)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_datagram_socket.close.assert_called()

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SocketDatagramTransport,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    def test____abort____default(
        self,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.abort()

        # Assert
        assert mock_datagram_socket.mock_calls == [mocker.call.close()]

    def test____close____default(
        self,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.close()

        # Assert
        assert mock_datagram_socket.mock_calls == [mocker.call.close()]

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____read_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SocketDatagramTransport,
    ) -> None:
        # Arrange

        # Act
        fd = transport.read_fileno()

        # Assert
        assert fd == socket_fileno

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____write_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SocketDatagramTransport,
    ) -> None:
        # Arrange

        # Act
        fd = transport.write_fileno()

        # Assert
        assert fd == socket_fileno

    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock____default(
        self,
        max_datagram_size: int | None,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recv.return_value = mocker.sentinel.bytes

        # Act
        result = transport.recv_noblock()

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        else:
            mock_datagram_socket.recv.assert_called_once_with(max_datagram_size)
        mock_datagram_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock____blocking_error(
        self,
        max_datagram_size: int | None,
        error: type[OSError],
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket.recv.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock()

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        else:
            mock_datagram_socket.recv.assert_called_once_with(max_datagram_size)
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock_with_ancillary____default(
        self,
        max_datagram_size: int | None,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvmsg.return_value = (mocker.sentinel.bytes, mocker.sentinel.ancdata, 0, mocker.sentinel.addr)

        # Act
        result, ancdata = transport.recv_noblock_with_ancillary(mocker.sentinel.ancbufsize)

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recvmsg.assert_called_once_with(MAX_DATAGRAM_BUFSIZE, mocker.sentinel.ancbufsize)
        else:
            mock_datagram_socket.recvmsg.assert_called_once_with(max_datagram_size, mocker.sentinel.ancbufsize)
        mock_datagram_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes
        assert ancdata is mocker.sentinel.ancdata

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _ANCILLARY_UNSUPPORTED, indirect=True)
    def test____recv_noblock_with_ancillary____socket_family_unsupported(
        self,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvmsg.return_value = (mocker.sentinel.bytes, mocker.sentinel.ancdata, 0, mocker.sentinel.addr)

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.recv_noblock_with_ancillary(mocker.sentinel.ancbufsize)

        # Assert
        mock_datagram_socket.recvmsg.assert_not_called()
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock_with_ancillary____blocking_error(
        self,
        max_datagram_size: int | None,
        error: type[OSError],
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvmsg.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock_with_ancillary(mocker.sentinel.ancbufsize)

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recvmsg.assert_called_once_with(MAX_DATAGRAM_BUFSIZE, mocker.sentinel.ancbufsize)
        else:
            mock_datagram_socket.recvmsg.assert_called_once_with(max_datagram_size, mocker.sentinel.ancbufsize)
        mock_datagram_socket.fileno.assert_not_called()

    def test____send_noblock____default(
        self,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.send.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_datagram_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_datagram_socket.fileno.assert_not_called()
        assert result is None

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_noblock____blocking_error(
        self,
        error: type[OSError],
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.send.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite):
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_datagram_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    def test____send_noblock_with_ancillary____default(
        self,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendmsg.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock_with_ancillary(mocker.sentinel.data, mocker.sentinel.ancdata)

        # Assert
        mock_datagram_socket.sendmsg.assert_called_once_with([mocker.sentinel.data], mocker.sentinel.ancdata)
        mock_datagram_socket.fileno.assert_not_called()
        assert result is None

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _ANCILLARY_UNSUPPORTED, indirect=True)
    def test____send_noblock_with_ancillary____socket_family_unsupported(
        self,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendmsg.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.send_noblock_with_ancillary(mocker.sentinel.data, mocker.sentinel.ancdata)

        # Assert
        mock_datagram_socket.sendmsg.assert_not_called()
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_noblock_with_ancillary____blocking_error(
        self,
        error: type[OSError],
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendmsg.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite):
            transport.send_noblock_with_ancillary(mocker.sentinel.data, mocker.sentinel.ancdata)

        # Assert
        mock_datagram_socket.sendmsg.assert_called_once_with([mocker.sentinel.data], mocker.sentinel.ancdata)
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("ancillary_data_is_iterator", [False, True], ids=lambda p: f"ancillary_data_is_iterator__{p}")
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_with_ancillary____correctly_handle_iterables(
        self,
        error: type[OSError],
        ancillary_data_is_iterator: bool,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        to_raise: list[type[OSError]] = [error]
        chunks: list[list[bytes]] = []
        ancillary_data_sent: list[list[Any]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer], ancdata: Iterable[Any]) -> int:
            buffers = list(buffers)
            ancdata = list(ancdata)
            if to_raise:
                raise to_raise.pop(0)
            chunks.append(list(map(bytes, buffers)))
            ancillary_data_sent.append(ancdata)
            return sum(memoryview(v).nbytes for v in buffers)

        mock_datagram_socket.sendmsg.side_effect = sendmsg_side_effect

        ancillary_data: Iterable[Any] = [mocker.sentinel.ancdata]
        if ancillary_data_is_iterator:
            ancillary_data = iter(ancillary_data)

        # Act
        transport.send_with_ancillary(b"data", ancillary_data, 123456)

        # Assert
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 123456)
        assert mock_datagram_socket.sendmsg.call_count == 2
        assert chunks == [[b"data"]]
        assert ancillary_data_sent == [[mocker.sentinel.ancdata]]

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method", "os_error"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", errno.EINVAL, id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", errno.ENOTCONN, id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_raises_OSError(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        os_error: int,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_datagram_socket, called_socket_method)
        mock_get_address.side_effect = OSError(os_error, os.strerror(os_error))

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_called_once()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_on_closed_socket(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        transport: SocketDatagramTransport,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_datagram_socket, called_socket_method)
        transport.close()
        assert mock_datagram_socket.fileno.return_value == -1

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_not_called()


@dataclasses.dataclass
class _RequestHandlerNoSSL:
    request: pytest.FixtureRequest
    stub: MagicMock
    transport: SocketStreamTransport | None = dataclasses.field(init=False, default=None)

    def __call__(self, transport: SocketStreamTransport) -> Any:
        self.transport = transport
        self.request.addfinalizer(transport.close)
        return self.stub()


class TestSocketStreamListener(BaseTestSocketTransport):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_transport_retry(mocker: MockerFixture) -> MagicMock:
        mock_transport_retry = mocker.patch.object(SocketStreamListener, "_retry", autospec=True)
        mock_transport_retry.side_effect = _retry_side_effect
        return mock_transport_retry

    @pytest.fixture
    @staticmethod
    def mock_executor(mocker: MockerFixture) -> MagicMock:
        mock_executor = mocker.NonCallableMagicMock(spec=Executor)
        mock_executor.submit.side_effect = executor_submit_default_side_effect
        return mock_executor

    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @classmethod
    def mock_accepted_stream_socket(
        cls,
        socket_family_name: str,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_tcp_socket_factory: Callable[[int, int], MagicMock],
        mock_unix_stream_socket_factory: Callable[[int], MagicMock],
    ) -> MagicMock:
        mock_accepted_stream_socket: MagicMock
        socket_fileno: int = 567

        match socket_family_name:
            case "AF_INET":
                mock_accepted_stream_socket = mock_tcp_socket_factory(AF_INET, socket_fileno)
            case "AF_UNIX":
                mock_accepted_stream_socket = mock_unix_stream_socket_factory(socket_fileno)
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_accepted_stream_socket, mock_accepted_stream_socket.family, local_address)
        cls.set_remote_address_to_socket_mock(mock_accepted_stream_socket, mock_accepted_stream_socket.family, remote_address)
        return mock_accepted_stream_socket

    @pytest.fixture
    @classmethod
    def mock_stream_listener_socket(
        cls,
        socket_family_name: str,
        socket_fileno: int,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_tcp_socket_factory: Callable[[int, int], MagicMock],
        mock_unix_stream_socket_factory: Callable[[int], MagicMock],
        mock_accepted_stream_socket: MagicMock,
    ) -> MagicMock:
        mock_stream_listener_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_stream_listener_socket = mock_tcp_socket_factory(AF_INET, socket_fileno)
            case "AF_UNIX":
                mock_stream_listener_socket = mock_unix_stream_socket_factory(socket_fileno)
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_stream_listener_socket, mock_stream_listener_socket.family, local_address)
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_stream_listener_socket)
        mock_stream_listener_socket.accept.return_value = (mock_accepted_stream_socket, remote_address)

        return mock_stream_listener_socket

    @pytest.fixture
    @staticmethod
    def transport(mock_stream_listener_socket: MagicMock) -> Generator[SocketStreamListener]:
        transport = SocketStreamListener(mock_stream_listener_socket)
        mock_stream_listener_socket.reset_mock()
        with transport:
            yield transport

    def test____dunder_init____default(
        self,
        request: pytest.FixtureRequest,
        mock_stream_listener_socket: MagicMock,
        local_address: tuple[str, int] | bytes,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SocketStreamListener(mock_stream_listener_socket, selector_factory=mock_selector_factory)
        request.addfinalizer(transport.close)

        # Assert
        assert transport._retry_interval == 1.0
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_stream_listener_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(SocketAttribute.peername)

        mock_stream_listener_socket.getsockname.assert_called_once_with()
        mock_stream_listener_socket.getpeername.assert_called()
        mock_stream_listener_socket.setblocking.assert_called_once_with(False)
        mock_stream_listener_socket.settimeout.assert_not_called()

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SocketStreamListener(mock_ssl_socket)

    def test____dunder_init____forbid_non_stream_sockets(
        self,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = SocketStreamListener(mock_udp_socket)

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        transport = SocketStreamListener(mock_stream_listener_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del transport

        mock_stream_listener_socket.close.assert_called()

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SocketStreamListener,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    def test____abort____default(
        self,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.abort()

        # Assert
        assert mock_stream_listener_socket.mock_calls == [mocker.call.close()]

    def test____close____default(
        self,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.close()

        # Assert
        assert mock_stream_listener_socket.mock_calls == [mocker.call.close()]

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____read_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SocketStreamListener,
    ) -> None:
        # Arrange

        # Act
        fd = transport.read_fileno()

        # Assert
        assert fd == socket_fileno

    def test____accept_noblock____accept_socket(
        self,
        request: pytest.FixtureRequest,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
        mock_accepted_stream_socket: MagicMock,
        mock_executor: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        handler = _RequestHandlerNoSSL(request, mocker.stub())
        handler.stub.return_value = mocker.sentinel.handler_ret_val

        # Act
        task: Future[Any] = transport.accept_noblock(handler, mock_executor)

        # Assert
        assert mock_stream_listener_socket.mock_calls == [mocker.call.accept()]
        assert isinstance(handler.transport, SocketStreamTransport)
        assert handler.transport.read_fileno() == mock_accepted_stream_socket.fileno()
        assert task.result(timeout=0) is mocker.sentinel.handler_ret_val

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____accept_noblock___blocking_error(
        self,
        error: type[OSError],
        request: pytest.FixtureRequest,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
        mock_executor: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_listener_socket.accept.side_effect = error

        handler = _RequestHandlerNoSSL(request, mocker.stub())
        handler.stub.return_value = mocker.sentinel.handler_ret_val

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.accept_noblock(handler, mock_executor)

        # Assert
        assert mock_stream_listener_socket.mock_calls == [mocker.call.accept()]
        mock_executor.submit.assert_not_called()
        assert handler.transport is None

    @pytest.mark.parametrize(
        "os_error",
        list(map(pytest.param, sorted(IGNORABLE_ACCEPT_ERRNOS | CLOSED_SOCKET_ERRNOS))),
        ids=lambda p: errno.errorcode.get(p, repr(p)),
    )
    def test____accept_noblock___os_error(
        self,
        os_error: int,
        request: pytest.FixtureRequest,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
        mock_executor: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_listener_socket.accept.side_effect = OSError(os_error, os.strerror(os_error))

        handler = _RequestHandlerNoSSL(request, mocker.stub())
        handler.stub.return_value = mocker.sentinel.handler_ret_val

        # Act
        task: Future[Any] | None = None
        with (
            pytest.raises(OSError, check=lambda exc: exc.errno == os_error)
            if os_error not in IGNORABLE_ACCEPT_ERRNOS
            else contextlib.nullcontext()
        ):
            task = transport.accept_noblock(handler, mock_executor)

        # Assert
        assert mock_stream_listener_socket.mock_calls == [mocker.call.accept()]
        mock_executor.submit.assert_not_called()
        assert handler.transport is None
        if os_error in IGNORABLE_ACCEPT_ERRNOS:
            assert task is not None
            assert task.cancelled()
        else:
            assert task is None

    def test____accept_noblock___executor_shut_down(
        self,
        request: pytest.FixtureRequest,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
        mock_accepted_stream_socket: MagicMock,
        mock_executor: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_executor.submit.side_effect = RuntimeError("executor shut down")

        handler = _RequestHandlerNoSSL(request, mocker.stub())
        handler.stub.return_value = mocker.sentinel.handler_ret_val

        # Act
        with pytest.raises(RuntimeError, match="executor shut down"):
            transport.accept_noblock(handler, mock_executor)

        # Assert
        assert mock_stream_listener_socket.mock_calls == [mocker.call.accept()]
        assert handler.transport is None
        mock_accepted_stream_socket.close.assert_called_once()

    def test____accept_noblock___task_cancelled_before_execution(
        self,
        request: pytest.FixtureRequest,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
        mock_accepted_stream_socket: MagicMock,
        mock_executor: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_executor.submit.side_effect = make_executor_submit_side_effect(request, interval=math.inf)

        handler = _RequestHandlerNoSSL(request, mocker.stub())
        handler.stub.return_value = mocker.sentinel.handler_ret_val

        # Act
        task: Future[Any] = transport.accept_noblock(handler, mock_executor)
        assert not task.done()
        task.cancel()
        assert task.cancelled()

        # Assert
        assert mock_stream_listener_socket.mock_calls == [mocker.call.accept()]
        assert handler.transport is None
        mock_accepted_stream_socket.close.assert_called_once()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method", "os_error"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", errno.EINVAL, id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", errno.ENOTCONN, id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_raises_OSError(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        os_error: int,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_stream_listener_socket, called_socket_method)
        mock_get_address.side_effect = OSError(os_error, os.strerror(os_error))

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_called_once()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_on_closed_socket(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        transport: SocketStreamListener,
        mock_stream_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_stream_listener_socket, called_socket_method)
        transport.close()
        assert mock_stream_listener_socket.fileno.return_value == -1

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_not_called()


class TestSocketDatagramListener(BaseTestSocketTransport):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_transport_retry(mocker: MockerFixture) -> MagicMock:
        mock_transport_retry = mocker.patch.object(SocketDatagramListener, "_retry", autospec=True)
        mock_transport_retry.side_effect = _retry_side_effect
        return mock_transport_retry

    @pytest.fixture
    @staticmethod
    def socket_fileno(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 12345)

    @pytest.fixture
    @classmethod
    def mock_datagram_socket(
        cls,
        socket_family_name: str,
        socket_fileno: int,
        local_address: tuple[str, int] | bytes,
        mock_udp_socket_factory: Callable[[int, int], MagicMock],
        mock_unix_datagram_socket_factory: Callable[[int], MagicMock],
    ) -> MagicMock:
        mock_datagram_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_datagram_socket = mock_udp_socket_factory(AF_INET, socket_fileno)
            case "AF_UNIX":
                mock_datagram_socket = mock_unix_datagram_socket_factory(socket_fileno)
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_datagram_socket, mock_datagram_socket.family, local_address)
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_datagram_socket)

        return mock_datagram_socket

    @pytest.fixture
    @staticmethod
    def max_datagram_size(request: pytest.FixtureRequest) -> int | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def transport(mock_datagram_socket: MagicMock, max_datagram_size: int | None) -> Generator[SocketDatagramListener]:
        if max_datagram_size is None:
            transport = SocketDatagramListener(mock_datagram_socket)
        else:
            transport = SocketDatagramListener(mock_datagram_socket, max_datagram_size=max_datagram_size)
        mock_datagram_socket.reset_mock()
        with transport:
            yield transport

    def test____dunder_init____default(
        self,
        request: pytest.FixtureRequest,
        local_address: tuple[str, int] | bytes,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_factory = mocker.stub()

        # Act
        transport = SocketDatagramListener(mock_datagram_socket, selector_factory=mock_selector_factory)
        request.addfinalizer(transport.close)

        # Assert
        assert transport._retry_interval == 1.0
        assert transport._selector_factory is mock_selector_factory
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_datagram_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(SocketAttribute.peername)

        mock_datagram_socket.getsockname.assert_called_once_with()
        mock_datagram_socket.getpeername.assert_called()
        mock_datagram_socket.setblocking.assert_called_once_with(False)
        mock_datagram_socket.settimeout.assert_not_called()

    def test____dunder_init____forbid_ssl_sockets(
        self,
        mock_ssl_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = SocketDatagramListener(mock_ssl_socket)

    def test____dunder_init____forbid_non_datagram_sockets(
        self,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = SocketDatagramListener(mock_tcp_socket)

    @pytest.mark.parametrize("max_datagram_size", [0, -42], ids=lambda p: f"max_datagram_size__{p}")
    def test____dunder_init____invalid_datagram_size(
        self,
        max_datagram_size: int,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^max_datagram_size must not be <= 0$"):
            _ = SocketDatagramListener(mock_datagram_socket, max_datagram_size=max_datagram_size)

    def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        transport = SocketDatagramListener(mock_datagram_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del transport

        mock_datagram_socket.close.assert_called()

    @pytest.mark.parametrize(
        ["socket_fileno", "expected_state"],
        [
            pytest.param(0, False),
            pytest.param(12345, False),
            pytest.param(-1, True),
            pytest.param(-42, True),
        ],
        indirect=["socket_fileno"],
    )
    def test____is_closed____returned_state(
        self,
        expected_state: bool,
        transport: SocketDatagramListener,
    ) -> None:
        # Arrange

        # Act
        state = transport.is_closed()

        # Assert
        assert state is expected_state

    def test____abort____default(
        self,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.abort()

        # Assert
        assert mock_datagram_socket.mock_calls == [mocker.call.close()]

    def test____close____default(
        self,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.close()

        # Assert
        assert mock_datagram_socket.mock_calls == [mocker.call.close()]

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____read_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SocketDatagramListener,
    ) -> None:
        # Arrange

        # Act
        fd = transport.read_fileno()

        # Assert
        assert fd == socket_fileno

    @pytest.mark.parametrize("socket_fileno", [0, 12345, -1, -42], indirect=True)
    def test____write_fileno____socket_fileno(
        self,
        socket_fileno: int,
        transport: SocketDatagramListener,
    ) -> None:
        # Arrange

        # Act
        fd = transport.write_fileno()

        # Assert
        assert fd == socket_fileno

    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock_from____default(
        self,
        max_datagram_size: int | None,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvfrom.return_value = (mocker.sentinel.bytes, mocker.sentinel.addr)

        # Act
        result, sender_address = transport.recv_noblock_from()

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        else:
            mock_datagram_socket.recvfrom.assert_called_once_with(max_datagram_size)
        mock_datagram_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes
        assert sender_address is mocker.sentinel.addr

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock_from____blocking_error(
        self,
        max_datagram_size: int | None,
        error: type[OSError],
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvfrom.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock_from()

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recvfrom.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        else:
            mock_datagram_socket.recvfrom.assert_called_once_with(max_datagram_size)
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock_with_ancillary_from____default(
        self,
        max_datagram_size: int | None,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvmsg.return_value = (mocker.sentinel.bytes, mocker.sentinel.ancdata, 0, mocker.sentinel.addr)

        # Act
        result, ancdata, sender_address = transport.recv_noblock_with_ancillary_from(mocker.sentinel.ancbufsize)

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recvmsg.assert_called_once_with(MAX_DATAGRAM_BUFSIZE, mocker.sentinel.ancbufsize)
        else:
            mock_datagram_socket.recvmsg.assert_called_once_with(max_datagram_size, mocker.sentinel.ancbufsize)
        mock_datagram_socket.fileno.assert_not_called()
        assert result is mocker.sentinel.bytes
        assert ancdata is mocker.sentinel.ancdata
        assert sender_address is mocker.sentinel.addr

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _ANCILLARY_UNSUPPORTED, indirect=True)
    def test____recv_noblock_with_ancillary_from____socket_family_unsupported(
        self,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvmsg.return_value = (mocker.sentinel.bytes, mocker.sentinel.ancdata, 0, mocker.sentinel.addr)

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.recv_noblock_with_ancillary_from(mocker.sentinel.ancbufsize)

        # Assert
        mock_datagram_socket.recvmsg.assert_not_called()
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_recvmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size__{p}", indirect=True)
    def test____recv_noblock_with_ancillary_from____blocking_error(
        self,
        max_datagram_size: int | None,
        error: type[OSError],
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.recvmsg.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnRead):
            transport.recv_noblock_with_ancillary_from(mocker.sentinel.ancbufsize)

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recvmsg.assert_called_once_with(MAX_DATAGRAM_BUFSIZE, mocker.sentinel.ancbufsize)
        else:
            mock_datagram_socket.recvmsg.assert_called_once_with(max_datagram_size, mocker.sentinel.ancbufsize)
        mock_datagram_socket.fileno.assert_not_called()

    def test____send_noblock_to____default(
        self,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendto.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock_to(mocker.sentinel.data, mocker.sentinel.addr)

        # Assert
        mock_datagram_socket.sendto.assert_called_once_with(mocker.sentinel.data, mocker.sentinel.addr)
        mock_datagram_socket.fileno.assert_not_called()
        assert result is None

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_noblock_to____blocking_error(
        self,
        error: type[OSError],
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendto.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite):
            transport.send_noblock_to(mocker.sentinel.data, mocker.sentinel.addr)

        # Assert
        mock_datagram_socket.sendto.assert_called_once_with(mocker.sentinel.data, mocker.sentinel.addr)
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    def test____send_noblock_with_ancillary_to____default(
        self,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendmsg.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        result = transport.send_noblock_with_ancillary_to(mocker.sentinel.data, mocker.sentinel.ancdata, mocker.sentinel.addr)

        # Assert
        mock_datagram_socket.sendmsg.assert_called_once_with(
            [mocker.sentinel.data],
            mocker.sentinel.ancdata,
            0,
            mocker.sentinel.addr,
        )
        mock_datagram_socket.fileno.assert_not_called()
        assert result is None

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _ANCILLARY_UNSUPPORTED, indirect=True)
    def test____send_noblock_with_ancillary_to____socket_family_unsupported(
        self,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendmsg.return_value = mocker.sentinel.nb_bytes_sent

        # Act
        with pytest.raises(UnsupportedOperation):
            transport.send_noblock_with_ancillary_to(mocker.sentinel.data, mocker.sentinel.ancdata, mocker.sentinel.addr)

        # Assert
        mock_datagram_socket.sendmsg.assert_not_called()
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_noblock_with_ancillary_to____blocking_error(
        self,
        error: type[OSError],
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_socket.sendmsg.side_effect = error

        # Act
        with pytest.raises(WouldBlockOnWrite):
            transport.send_noblock_with_ancillary_to(mocker.sentinel.data, mocker.sentinel.ancdata, mocker.sentinel.addr)

        # Assert
        mock_datagram_socket.sendmsg.assert_called_once_with(
            [mocker.sentinel.data],
            mocker.sentinel.ancdata,
            0,
            mocker.sentinel.addr,
        )
        mock_datagram_socket.fileno.assert_not_called()

    @PlatformMarkers.supports_socket_sendmsg
    @pytest.mark.parametrize("socket_family_name", _SUPPORTS_ANCILLARY, indirect=True)
    @pytest.mark.parametrize("ancillary_data_is_iterator", [False, True], ids=lambda p: f"ancillary_data_is_iterator__{p}")
    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_with_ancillary_to____correctly_handle_iterables(
        self,
        error: type[OSError],
        ancillary_data_is_iterator: bool,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        to_raise: list[type[OSError]] = [error]
        chunks: list[list[bytes]] = []
        ancillary_data_sent: list[list[Any]] = []

        def sendmsg_side_effect(buffers: Iterable[Buffer], ancdata: Iterable[Any], _flags: int, _addr: Any) -> int:
            buffers = list(buffers)
            ancdata = list(ancdata)
            if to_raise:
                raise to_raise.pop(0)
            chunks.append(list(map(bytes, buffers)))
            ancillary_data_sent.append(ancdata)
            return sum(memoryview(v).nbytes for v in buffers)

        mock_datagram_socket.sendmsg.side_effect = sendmsg_side_effect

        ancillary_data: Iterable[Any] = [mocker.sentinel.ancdata]
        if ancillary_data_is_iterator:
            ancillary_data = iter(ancillary_data)

        # Act
        transport.send_with_ancillary_to(b"data", ancillary_data, mocker.sentinel.addr, 123456)

        # Assert
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 123456)
        assert mock_datagram_socket.sendmsg.call_count == 2
        assert chunks == [[b"data"]]
        assert ancillary_data_sent == [[mocker.sentinel.ancdata]]

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method", "os_error"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", errno.EINVAL, id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", errno.ENOTCONN, id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_raises_OSError(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        os_error: int,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_datagram_socket, called_socket_method)
        mock_get_address.side_effect = OSError(os_error, os.strerror(os_error))

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_called_once()

    @pytest.mark.parametrize(
        ["extra_attribute", "called_socket_method"],
        [
            pytest.param(SocketAttribute.sockname, "getsockname", id="socket.getsockname()"),
            pytest.param(SocketAttribute.peername, "getpeername", id="socket.getpeername()"),
        ],
    )
    def test____extra_attributes____address_lookup_on_closed_socket(
        self,
        extra_attribute: Any,
        called_socket_method: str,
        transport: SocketDatagramListener,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_get_address: MagicMock = getattr(mock_datagram_socket, called_socket_method)
        transport.close()
        assert mock_datagram_socket.fileno.return_value == -1

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_address.assert_not_called()
