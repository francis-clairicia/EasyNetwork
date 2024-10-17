# mypy: disable-error-code=func-returns-value

from __future__ import annotations

import errno
import math
import os
import ssl
from collections.abc import Callable, Iterable, Iterator
from socket import AF_INET, SHUT_RDWR, SHUT_WR
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import TypedAttributeLookupError, UnsupportedOperation
from easynetwork.lowlevel.api_sync.transports.base_selector import WouldBlockOnRead, WouldBlockOnWrite
from easynetwork.lowlevel.api_sync.transports.socket import SocketDatagramTransport, SocketStreamTransport, SSLStreamTransport
from easynetwork.lowlevel.constants import (
    CLOSED_SOCKET_ERRNOS,
    MAX_DATAGRAM_BUFSIZE,
    NOT_CONNECTED_SOCKET_ERRNOS,
    SSL_HANDSHAKE_TIMEOUT,
)
from easynetwork.lowlevel.socket import SocketAttribute, SocketProxy, TLSAttribute

import pytest

from ....base import BaseTestSocketTransport, MixinTestSocketSendMSG

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture


def _retry_side_effect(self: Any, callback: Callable[[], Any], timeout: float) -> tuple[Any, float]:
    while True:
        try:
            return callback(), timeout
        except (WouldBlockOnRead, WouldBlockOnWrite):
            pass


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
        mocker: MockerFixture,
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

        # Always create a new mock instance because sendmsg() is not available on all platforms
        # therefore the mocker's autospec will consider sendmsg() unknown on these ones.
        if not hasattr(mock_stream_socket, "sendmsg"):
            mock_stream_socket.sendmsg = mocker.MagicMock(spec=lambda *args: None)
        mock_stream_socket.sendmsg.side_effect = lambda buffers, *args: sum(map(len, map(lambda v: memoryview(v), buffers)))
        return mock_stream_socket

    @pytest.fixture
    @staticmethod
    def transport(mock_stream_socket: MagicMock) -> Iterator[SocketStreamTransport]:
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
        with pytest.raises(WouldBlockOnRead) as exc_info:
            transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_stream_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_stream_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_stream_socket.fileno.return_value

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
        with pytest.raises(WouldBlockOnRead) as exc_info:
            transport.recv_noblock_into(mocker.sentinel.buffer)

        # Assert
        mock_stream_socket.recv_into.assert_called_once_with(mocker.sentinel.buffer)
        mock_stream_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_stream_socket.fileno.return_value

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
        with pytest.raises(WouldBlockOnWrite) as exc_info:
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_stream_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_stream_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_stream_socket.fileno.return_value

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

        def sendmsg_side_effect(buffers: Iterable[ReadableBuffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(map(len, map(lambda v: memoryview(v), buffers)))

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_from_iterable(iter([b"data", b"to", b"send"]), 123456)

        # Assert
        mock_transport_send_all.assert_not_called()
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 123456)
        mock_stream_socket.sendmsg.assert_called_once()
        assert chunks == [[b"data", b"to", b"send"]]

    @pytest.mark.parametrize("SC_IOV_MAX", [2], ids=lambda p: f"SC_IOV_MAX=={p}", indirect=True)
    def test____send_all_from_iterable____nb_buffers_greather_than_SC_IOV_MAX(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[ReadableBuffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(map(len, map(lambda v: memoryview(v), buffers)))

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

    def test____send_all_from_iterable____adjust_leftover_buffer(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[ReadableBuffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return min(sum(map(len, map(lambda v: memoryview(v), buffers))), 3)

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

    @pytest.mark.parametrize("error", [BlockingIOError, InterruptedError])
    def test____send_all_from_iterable____blocking_error(
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

        def sendmsg_side_effect(buffers: Iterable[ReadableBuffer]) -> int:
            if to_raise:
                raise to_raise.pop(0)
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(map(len, map(lambda v: memoryview(v), buffers)))

        mock_stream_socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        transport.send_all_from_iterable(iter([b"data"]), 123456)

        # Assert
        mock_transport_send_all.assert_not_called()
        mock_transport_retry.assert_called_once_with(transport, mocker.ANY, 123456)
        assert mock_stream_socket.sendmsg.call_count == 2
        assert chunks == [[b"data"]]

    def test____send_all_from_iterable____fallback_to_send_all____sendmsg_unavailable(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mock_transport_send_all: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        del mock_stream_socket.sendmsg

        # Act
        transport.send_all_from_iterable(iter([b"data", b"to", b"send"]), 123456)

        # Assert
        mock_transport_retry.assert_not_called()
        assert mock_transport_send_all.call_args_list == [
            mocker.call(b"".join([b"data", b"to", b"send"]), mocker.ANY),
        ]

    @pytest.mark.parametrize("SC_IOV_MAX", [-1, 0], ids=lambda p: f"SC_IOV_MAX=={p}", indirect=True)
    def test____send_all_from_iterable____fallback_to_send_all____sendmsg_available_but_no_defined_limit(
        self,
        transport: SocketStreamTransport,
        mock_stream_socket: MagicMock,
        mock_transport_retry: MagicMock,
        mock_transport_send_all: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        transport.send_all_from_iterable(iter([b"data", b"to", b"send"]), 123456)

        # Assert
        mock_transport_retry.assert_not_called()
        mock_stream_socket.sendmsg.assert_not_called()
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
        mocker: MockerFixture,
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
    ) -> Iterator[SSLStreamTransport]:
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

    @pytest.mark.parametrize("standard_compatible", [False, True], ids=lambda p: f"standard_compatible=={p}", indirect=True)
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

    @pytest.mark.parametrize("unwrap_error", [None, OSError])
    @pytest.mark.parametrize("shutdown_error", [None, OSError])
    @pytest.mark.parametrize("standard_compatible", [False, True], ids=lambda p: f"standard_compatible=={p}", indirect=True)
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
        with pytest.raises(expected_blocking_error) as exc_info:
            transport.recv_noblock(mocker.sentinel.bufsize)

        # Assert
        mock_ssl_socket.recv.assert_called_once_with(mocker.sentinel.bufsize)
        mock_ssl_socket.fileno.assert_called_once()
        assert isinstance(exc_info.value, (WouldBlockOnRead, WouldBlockOnWrite))
        assert exc_info.value.fileno is mock_ssl_socket.fileno.return_value

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
        with pytest.raises(expected_blocking_error) as exc_info:
            transport.recv_noblock_into(mocker.sentinel.buffer)

        # Assert
        mock_ssl_socket.recv_into.assert_called_once_with(mocker.sentinel.buffer)
        mock_ssl_socket.fileno.assert_called_once()
        assert isinstance(exc_info.value, (WouldBlockOnRead, WouldBlockOnWrite))
        assert exc_info.value.fileno is mock_ssl_socket.fileno.return_value

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
        with pytest.raises(expected_blocking_error) as exc_info:
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_ssl_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_ssl_socket.fileno.assert_called_once()
        assert isinstance(exc_info.value, (WouldBlockOnRead, WouldBlockOnWrite))
        assert exc_info.value.fileno is mock_ssl_socket.fileno.return_value

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
        mocker: MockerFixture,
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
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_get_value: MagicMock = getattr(mock_ssl_socket, called_socket_method)
        mock_get_value.return_value = None

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError):
            transport.extra(extra_attribute)
        mock_get_value.assert_called_once()


class TestSocketDatagramTransport(BaseTestSocketTransport):
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
    def transport(mock_datagram_socket: MagicMock, max_datagram_size: int | None) -> Iterator[SocketDatagramTransport]:
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

    @pytest.mark.parametrize("max_datagram_size", [0, -42], ids=lambda p: f"max_datagram_size=={p}")
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

    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size=={p}", indirect=True)
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
    @pytest.mark.parametrize("max_datagram_size", [None, 1024], ids=lambda p: f"max_datagram_size=={p}", indirect=True)
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
        with pytest.raises(WouldBlockOnRead) as exc_info:
            transport.recv_noblock()

        # Assert
        if max_datagram_size is None:
            mock_datagram_socket.recv.assert_called_once_with(MAX_DATAGRAM_BUFSIZE)
        else:
            mock_datagram_socket.recv.assert_called_once_with(max_datagram_size)
        mock_datagram_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_datagram_socket.fileno.return_value

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
        with pytest.raises(WouldBlockOnWrite) as exc_info:
            transport.send_noblock(mocker.sentinel.data)

        # Assert
        mock_datagram_socket.send.assert_called_once_with(mocker.sentinel.data)
        mock_datagram_socket.fileno.assert_called_once()
        assert exc_info.value.fileno is mock_datagram_socket.fileno.return_value

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
        mocker: MockerFixture,
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
