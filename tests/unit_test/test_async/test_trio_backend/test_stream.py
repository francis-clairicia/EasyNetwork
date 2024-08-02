from __future__ import annotations

import errno
import os
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend
from easynetwork.lowlevel.constants import CLOSED_SOCKET_ERRNOS
from easynetwork.lowlevel.socket import SocketAttribute, SocketProxy

import pytest

from ....fixtures.trio import trio_fixture
from ...base import BaseTestSocket, MixinTestSocketSendMSG

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from easynetwork.lowlevel.api_async.backend._trio.stream.socket import TrioStreamSocketAdapter

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture
    from trio import BrokenResourceError as _BrokenResourceError, ClosedResourceError as _ClosedResourceError


class BaseTestTransportStreamSocket(BaseTestSocket):
    @staticmethod
    def _make_broken_resource_error(connection_error_errno: int) -> _BrokenResourceError:
        import trio

        cause = OSError(connection_error_errno, os.strerror(connection_error_errno))

        exc = trio.BrokenResourceError()
        exc.__context__ = cause
        exc.__cause__ = cause
        return exc

    @staticmethod
    def _make_closed_resource_error(closed_socket_errno: int = errno.EBADF) -> _ClosedResourceError:
        import trio

        exc = trio.ClosedResourceError()
        exc.__context__ = OSError(closed_socket_errno, os.strerror(closed_socket_errno))
        exc.__cause__ = None
        return exc


@pytest.mark.feature_trio
class TestTrioStreamSocketAdapter(BaseTestTransportStreamSocket, MixinTestSocketSendMSG):
    @pytest.fixture
    @classmethod
    def mock_trio_tcp_socket(cls, mock_trio_tcp_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        cls.set_local_address_to_socket_mock(mock_trio_tcp_socket, mock_trio_tcp_socket.family, ("127.0.0.1", 11111))
        cls.set_remote_address_to_socket_mock(mock_trio_tcp_socket, mock_trio_tcp_socket.family, ("127.0.0.1", 12345))

        # Always create a new mock instance because sendmsg() is not available on all platforms
        # therefore the mocker's autospec will consider sendmsg() unknown on these ones.
        mock_trio_tcp_socket.sendmsg = mocker.AsyncMock(
            spec=lambda *args: None,
            side_effect=lambda buffers, *args: sum(map(len, map(memoryview, buffers))),
        )
        return mock_trio_tcp_socket

    @pytest.fixture
    @staticmethod
    def mock_trio_socket_stream(
        mock_trio_tcp_socket: MagicMock,
        mock_trio_socket_stream_factory: Callable[[MagicMock], MagicMock],
    ) -> MagicMock:
        mock_trio_socket_stream = mock_trio_socket_stream_factory(mock_trio_tcp_socket)
        assert mock_trio_socket_stream.socket is mock_trio_tcp_socket

        mock_trio_socket_stream.send_all.return_value = None

        return mock_trio_socket_stream

    @trio_fixture
    @staticmethod
    async def transport(
        trio_backend: TrioBackend,
        mock_trio_socket_stream: MagicMock,
    ) -> AsyncIterator[TrioStreamSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.stream.socket import TrioStreamSocketAdapter

        transport = TrioStreamSocketAdapter(trio_backend, mock_trio_socket_stream)
        async with transport:
            yield transport

    async def test____dunder_del____ResourceWarning(
        self,
        trio_backend: TrioBackend,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.stream.socket import TrioStreamSocketAdapter

        transport = TrioStreamSocketAdapter(trio_backend, mock_trio_socket_stream)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_trio_socket_stream.socket.close.assert_called()

    async def test____aclose____close_transport_and_wait(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        assert not transport.is_closing()

        # Act
        await transport.aclose()

        # Assert
        mock_trio_socket_stream.aclose.assert_awaited_once()
        assert transport.is_closing()

    async def test____recv____read_from_reader(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.receive_some.return_value = b"data"

        # Act
        data: bytes = await transport.recv(1024)

        # Assert
        mock_trio_socket_stream.receive_some.assert_awaited_once_with(1024)
        assert data == b"data"

    async def test____recv____null_bufsize(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.receive_some.return_value = b""

        # Act
        data: bytes = await transport.recv(0)

        # Assert
        mock_trio_socket_stream.receive_some.assert_awaited_once_with(0)
        assert data == b""

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____recv____convert_trio_ClosedResourceError(
        self,
        closed_socket_errno: int,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.receive_some.side_effect = self._make_closed_resource_error(closed_socket_errno)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = await transport.recv(1024)

        # Assert
        assert exc_info.value.errno == errno.EBADF

    @pytest.mark.parametrize(
        "connection_error_errno",
        [
            errno.ECONNABORTED,
            errno.ECONNRESET,
            errno.EPIPE,
        ],
        ids=errno.errorcode.__getitem__,
    )
    async def test____recv____convert_trio_BrokenResourceError(
        self,
        connection_error_errno: int,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.receive_some.side_effect = self._make_broken_resource_error(connection_error_errno)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = await transport.recv(1024)

        # Assert
        assert exc_info.value.errno == connection_error_errno

    async def test____recv_into____read_from_reader(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.socket.recv_into.return_value = 4
        buffer = bytearray(4)

        # Act
        nbytes = await transport.recv_into(buffer)

        # Assert
        mock_trio_socket_stream.socket.recv_into.assert_awaited_once_with(buffer)
        assert nbytes == 4

    async def test____recv_into____null_buffer(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.socket.recv_into.return_value = 0
        buffer = bytearray()

        # Act
        nbytes = await transport.recv_into(buffer)

        # Assert
        mock_trio_socket_stream.socket.recv_into.assert_awaited_once_with(buffer)
        assert nbytes == 0

    async def test____send_all____use_stream_send_all(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await transport.send_all(b"data to send")

        # Assert
        mock_trio_socket_stream.send_all.assert_awaited_once_with(b"data to send")

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____send_all____convert_trio_ClosedResourceError(
        self,
        closed_socket_errno: int,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.send_all.side_effect = self._make_closed_resource_error(closed_socket_errno)

        # Act
        with pytest.raises(OSError) as exc_info:
            await transport.send_all(b"data to send")

        # Assert
        assert exc_info.value.errno == errno.EBADF

    @pytest.mark.parametrize(
        "connection_error_errno",
        [
            errno.ECONNABORTED,
            errno.ECONNRESET,
            errno.EPIPE,
        ],
        ids=errno.errorcode.__getitem__,
    )
    async def test____send_all____convert_trio_BrokenResourceError(
        self,
        connection_error_errno: int,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.send_all.side_effect = self._make_broken_resource_error(connection_error_errno)

        # Act
        with pytest.raises(OSError) as exc_info:
            await transport.send_all(b"data to send")

        # Assert
        assert exc_info.value.errno == connection_error_errno

    async def test____send_all_from_iterable____use_socket_sendmsg_when_available(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[ReadableBuffer]) -> int:
            # Ensure we are not giving the islice directly.
            assert not isinstance(buffers, Iterator)

            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(map(len, map(memoryview, buffers)))

        mock_trio_socket_stream.socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        await transport.send_all_from_iterable(iter([b"data", b"to", b"send"]))

        # Assert
        mock_trio_socket_stream.send_all.assert_not_called()
        mock_trio_socket_stream.socket.sendmsg.assert_called_once()
        assert chunks == [[b"data", b"to", b"send"]]

    @pytest.mark.parametrize("SC_IOV_MAX", [2], ids=lambda p: f"SC_IOV_MAX=={p}", indirect=True)
    async def test____send_all_from_iterable____nb_buffers_greather_than_SC_IOV_MAX(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[ReadableBuffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return sum(map(len, map(memoryview, buffers)))

        mock_trio_socket_stream.socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        await transport.send_all_from_iterable(iter([b"a", b"b", b"c", b"d", b"e"]))

        # Assert
        assert mock_trio_socket_stream.socket.sendmsg.await_count == 3
        assert chunks == [
            [b"a", b"b"],
            [b"c", b"d"],
            [b"e"],
        ]

    async def test____send_all_from_iterable____adjust_leftover_buffer(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        chunks: list[list[bytes]] = []

        def sendmsg_side_effect(buffers: Iterable[ReadableBuffer]) -> int:
            buffers = list(buffers)
            chunks.append(list(map(bytes, buffers)))
            return min(sum(map(len, map(memoryview, buffers))), 3)

        mock_trio_socket_stream.socket.sendmsg.side_effect = sendmsg_side_effect

        # Act
        await transport.send_all_from_iterable(iter([b"abcd", b"efg", b"hijkl", b"mnop"]))

        # Assert
        assert mock_trio_socket_stream.socket.sendmsg.await_count == 6
        assert chunks == [
            [b"abcd", b"efg", b"hijkl", b"mnop"],
            [b"d", b"efg", b"hijkl", b"mnop"],
            [b"g", b"hijkl", b"mnop"],
            [b"jkl", b"mnop"],
            [b"mnop"],
            [b"p"],
        ]

    async def test____send_all_from_iterable____fallback_to_send_all____sendmsg_unavailable(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        del mock_trio_socket_stream.socket.sendmsg

        # Act
        await transport.send_all_from_iterable(iter([b"data", b"to", b"send"]))

        # Assert
        assert mock_trio_socket_stream.send_all.await_args_list == [
            mocker.call(b"".join([b"data", b"to", b"send"])),
        ]

    @pytest.mark.parametrize("SC_IOV_MAX", [-1, 0], ids=lambda p: f"SC_IOV_MAX=={p}", indirect=True)
    async def test____send_all_from_iterable____fallback_to_send_all____sendmsg_available_but_no_defined_limit(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await transport.send_all_from_iterable(iter([b"data", b"to", b"send"]))

        # Assert
        assert mock_trio_socket_stream.send_all.await_args_list == [
            mocker.call(b"".join([b"data", b"to", b"send"])),
        ]

    async def test____send_all_from_iterable____fallback_to_send_all____empty_buffer_list(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await transport.send_all_from_iterable(iter([]))

        # Assert
        mock_trio_socket_stream.send_all.assert_awaited_once_with(b"")

    async def test____send_eo____use_stream_eof(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await transport.send_eof()

        # Assert
        mock_trio_socket_stream.send_eof.assert_awaited_once_with()

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____send_eof____convert_trio_ClosedResourceError(
        self,
        closed_socket_errno: int,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.send_eof.side_effect = self._make_closed_resource_error(closed_socket_errno)

        # Act
        with pytest.raises(OSError) as exc_info:
            await transport.send_eof()

        # Assert
        assert exc_info.value.errno == errno.EBADF

    @pytest.mark.parametrize(
        "connection_error_errno",
        [
            errno.ECONNABORTED,
            errno.ECONNRESET,
            errno.EPIPE,
        ],
        ids=errno.errorcode.__getitem__,
    )
    async def test____send_eof____convert_trio_BrokenResourceError(
        self,
        connection_error_errno: int,
        transport: TrioStreamSocketAdapter,
        mock_trio_socket_stream: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.send_eof.side_effect = self._make_broken_resource_error(connection_error_errno)

        # Act
        with pytest.raises(OSError) as exc_info:
            await transport.send_eof()

        # Assert
        assert exc_info.value.errno == connection_error_errno

    async def test____get_backend____returns_linked_instance(
        self,
        transport: TrioStreamSocketAdapter,
        trio_backend: TrioBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert transport.backend() is trio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        transport: TrioStreamSocketAdapter,
        mock_trio_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert isinstance(transport.extra(SocketAttribute.socket), SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_trio_tcp_socket.family
        assert transport.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert transport.extra(SocketAttribute.peername) == ("127.0.0.1", 12345)

        mock_trio_tcp_socket.reset_mock()
        transport.extra(SocketAttribute.socket).fileno()
        mock_trio_tcp_socket.fileno.assert_called_once()
