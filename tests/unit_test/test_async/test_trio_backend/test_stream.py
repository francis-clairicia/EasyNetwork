from __future__ import annotations

import contextlib
import errno
import logging
import os
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable, Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend
from easynetwork.lowlevel.api_async.backend.abc import TaskGroup
from easynetwork.lowlevel.constants import ACCEPT_CAPACITY_ERRNOS, CLOSED_SOCKET_ERRNOS
from easynetwork.lowlevel.socket import SocketAttribute, SocketProxy

import pytest

from ....fixtures.trio import trio_fixture
from ....tools import PlatformMarkers
from ...base import BaseTestSocketTransport, MixinTestSocketSendMSG

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from trio import BrokenResourceError as _BrokenResourceError, ClosedResourceError as _ClosedResourceError

    from easynetwork.lowlevel.api_async.backend._trio.stream.listener import TrioListenerSocketAdapter
    from easynetwork.lowlevel.api_async.backend._trio.stream.socket import TrioStreamSocketAdapter

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture


class BaseTestTrioSocketStream(BaseTestSocketTransport):
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


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioStreamSocketAdapter(BaseTestTrioSocketStream, MixinTestSocketSendMSG):
    @pytest.fixture
    @classmethod
    def mock_trio_stream_socket(
        cls,
        socket_family_name: str,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_trio_tcp_socket_factory: Callable[[], MagicMock],
        mock_trio_unix_stream_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_trio_stream_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_trio_stream_socket = mock_trio_tcp_socket_factory()
            case "AF_UNIX":
                mock_trio_stream_socket = mock_trio_unix_stream_socket_factory()
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_trio_stream_socket, mock_trio_stream_socket.family, local_address)
        cls.set_remote_address_to_socket_mock(mock_trio_stream_socket, mock_trio_stream_socket.family, remote_address)
        return mock_trio_stream_socket

    @pytest.fixture
    @staticmethod
    def mock_trio_socket_stream(
        mock_trio_stream_socket: MagicMock,
        mock_trio_socket_stream_factory: Callable[[MagicMock], MagicMock],
        mocker: MockerFixture,
    ) -> MagicMock:
        # Always create a new mock instance because sendmsg() is not available on all platforms
        # therefore the mocker's autospec will consider sendmsg() unknown on these ones.
        if not hasattr(mock_trio_stream_socket, "sendmsg"):
            mock_trio_stream_socket.sendmsg = mocker.AsyncMock(spec=lambda *args: None)
        mock_trio_stream_socket.sendmsg.side_effect = lambda buffers, *args: sum(map(len, map(lambda v: memoryview(v), buffers)))

        mock_trio_socket_stream = mock_trio_socket_stream_factory(mock_trio_stream_socket)
        assert mock_trio_socket_stream.socket is mock_trio_stream_socket

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
            return sum(map(len, map(lambda v: memoryview(v), buffers)))

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
            return sum(map(len, map(lambda v: memoryview(v), buffers)))

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
            return min(sum(map(len, map(lambda v: memoryview(v), buffers))), 3)

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
        mock_trio_stream_socket: MagicMock,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = transport.extra(SocketAttribute.socket)
        assert isinstance(trsock, SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_trio_stream_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        assert transport.extra(SocketAttribute.peername) == remote_address

        mock_trio_stream_socket.reset_mock()
        trsock.fileno()
        mock_trio_stream_socket.fileno.assert_called_once()


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioListenerSocketAdapter(BaseTestTrioSocketStream):
    @pytest.fixture
    @classmethod
    def mock_accepted_trio_stream_socket(
        cls,
        socket_family_name: str,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_trio_tcp_socket_factory: Callable[[], MagicMock],
        mock_trio_unix_stream_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_accepted_trio_stream_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_accepted_trio_stream_socket = mock_trio_tcp_socket_factory()
            case "AF_UNIX":
                mock_accepted_trio_stream_socket = mock_trio_unix_stream_socket_factory()
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(
            mock_accepted_trio_stream_socket,
            mock_accepted_trio_stream_socket.family,
            local_address,
        )
        cls.set_remote_address_to_socket_mock(
            mock_accepted_trio_stream_socket,
            mock_accepted_trio_stream_socket.family,
            remote_address,
        )
        return mock_accepted_trio_stream_socket

    @pytest.fixture
    @staticmethod
    def mock_accepted_trio_socket_stream(
        mock_accepted_trio_stream_socket: MagicMock,
        mock_trio_socket_stream_factory: Callable[[MagicMock], MagicMock],
    ) -> MagicMock:
        mock_accepted_trio_socket_stream = mock_trio_socket_stream_factory(mock_accepted_trio_stream_socket)
        assert mock_accepted_trio_socket_stream.socket is mock_accepted_trio_stream_socket

        return mock_accepted_trio_socket_stream

    @pytest.fixture
    @classmethod
    def mock_trio_stream_listener_socket(
        cls,
        socket_family_name: str,
        local_address: tuple[str, int] | bytes,
        mock_trio_tcp_socket_factory: Callable[[], MagicMock],
        mock_trio_unix_stream_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_trio_stream_listener_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_trio_stream_listener_socket = mock_trio_tcp_socket_factory()
            case "AF_UNIX":
                mock_trio_stream_listener_socket = mock_trio_unix_stream_socket_factory()
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(
            mock_trio_stream_listener_socket,
            mock_trio_stream_listener_socket.family,
            local_address,
        )
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_trio_stream_listener_socket)
        return mock_trio_stream_listener_socket

    @pytest.fixture
    @staticmethod
    def mock_trio_socket_listener(
        mock_trio_stream_listener_socket: MagicMock,
        mock_trio_socket_listener_factory: Callable[[MagicMock], MagicMock],
        mock_accepted_trio_socket_stream: MagicMock,
    ) -> MagicMock:
        mock_trio_socket_listener = mock_trio_socket_listener_factory(mock_trio_stream_listener_socket)
        assert mock_trio_socket_listener.socket is mock_trio_stream_listener_socket
        mock_trio_socket_listener.accept.return_value = mock_accepted_trio_socket_stream
        return mock_trio_socket_listener

    @pytest.fixture
    @staticmethod
    def handler(mocker: MockerFixture) -> AsyncMock:
        handler = mocker.async_stub("handler")
        handler.return_value = None
        return handler

    @trio_fixture
    @staticmethod
    async def listener(
        trio_backend: TrioBackend,
        mock_trio_socket_listener: MagicMock,
    ) -> AsyncIterator[TrioListenerSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.stream.listener import TrioListenerSocketAdapter

        listener = TrioListenerSocketAdapter(trio_backend, mock_trio_socket_listener)
        async with listener:
            yield listener

    @staticmethod
    def _make_accept_side_effect(
        side_effect: Any,
        mocker: MockerFixture,
        sleep_time: float = 0,
    ) -> Callable[[], Coroutine[Any, Any, MagicMock]]:
        import trio

        accept_cb = mocker.AsyncMock(side_effect=side_effect)

        async def accept_side_effect() -> MagicMock:
            await trio.sleep(sleep_time)
            return await accept_cb()

        return accept_side_effect

    @staticmethod
    async def _get_cancelled_exc() -> BaseException:
        import outcome
        import trio

        with trio.move_on_after(0):
            result = await outcome.acapture(trio.sleep_forever)

        assert isinstance(result, outcome.Error)
        return result.error.with_traceback(None)

    async def test____dunder_del____ResourceWarning(
        self,
        trio_backend: TrioBackend,
        mock_trio_socket_listener: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.stream.listener import TrioListenerSocketAdapter

        listener = TrioListenerSocketAdapter(trio_backend, mock_trio_socket_listener)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del listener

        mock_trio_socket_listener.socket.close.assert_called()

    async def test____aclose____close_socket(
        self,
        listener: TrioListenerSocketAdapter,
        mock_trio_socket_listener: MagicMock,
    ) -> None:
        # Arrange
        assert not listener.is_closing()

        # Act
        await listener.aclose()

        # Assert
        assert listener.is_closing()
        mock_trio_socket_listener.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____default(
        self,
        trio_backend: TrioBackend,
        listener: TrioListenerSocketAdapter,
        external_group: bool,
        handler: AsyncMock,
        mock_trio_socket_listener: MagicMock,
        mock_accepted_trio_socket_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import trio

        from easynetwork.lowlevel.api_async.backend._trio.stream.socket import TrioStreamSocketAdapter

        accepted_client_transport = mocker.NonCallableMagicMock(spec=TrioStreamSocketAdapter)
        mock_trio_socket_listener.accept.side_effect = self._make_accept_side_effect(
            [mock_accepted_trio_socket_stream, (await self._get_cancelled_exc())],
            mocker,
            sleep_time=0.1,
        )
        mock_TrioStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork.lowlevel.api_async.backend._trio.stream.listener.TrioStreamSocketAdapter",
            side_effect=[accepted_client_transport],
        )

        # Act
        task_group: TaskGroup | None
        async with trio_backend.create_task_group() if external_group else contextlib.nullcontext() as task_group:
            with pytest.raises(trio.Cancelled):
                await listener.serve(handler, task_group)

        # Assert
        mock_TrioStreamSocketAdapter.assert_called_once_with(trio_backend, mock_accepted_trio_socket_stream)
        handler.assert_awaited_once_with(accepted_client_transport)

    @pytest.mark.parametrize("closed_socket_errno", sorted(CLOSED_SOCKET_ERRNOS), ids=errno.errorcode.__getitem__)
    async def test____serve____convert_trio_ClosedResourceError(
        self,
        closed_socket_errno: int,
        trio_backend: TrioBackend,
        listener: TrioListenerSocketAdapter,
        handler: AsyncMock,
        mock_trio_socket_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_trio_socket_listener.accept.side_effect = self._make_accept_side_effect(
            self._make_closed_resource_error(closed_socket_errno),
            mocker,
            sleep_time=0.1,
        )

        # Act
        async with trio_backend.create_task_group() as task_group:
            with pytest.raises(OSError) as exc_info:
                await listener.serve(handler, task_group)

        # Assert
        assert exc_info.value.errno == errno.EBADF
        handler.assert_not_awaited()

    @PlatformMarkers.skipif_platform_win32_because("test failures are all too frequent on CI", skip_only_on_ci=True)
    @PlatformMarkers.skipif_platform_bsd_because("test failures are all too frequent on CI", skip_only_on_ci=True)
    @pytest.mark.parametrize("errno_value", sorted(ACCEPT_CAPACITY_ERRNOS), ids=errno.errorcode.__getitem__)
    @pytest.mark.flaky(retries=3, delay=0.1)
    async def test____accept____accept_capacity_error(
        self,
        errno_value: int,
        listener: TrioListenerSocketAdapter,
        mock_trio_socket_listener: MagicMock,
        handler: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        import trio

        caplog.set_level(logging.ERROR)
        mock_trio_socket_listener.accept.side_effect = OSError(errno_value, os.strerror(errno_value))

        # Act
        # It retries every 100 ms, so in 950 ms it will retry at 0, 100, ..., 900
        # = 10 times total
        with trio.CancelScope(deadline=trio.current_time() + 0.950):
            await listener.serve(handler)

        # Assert
        assert len(caplog.records) in {9, 10}
        for record in caplog.records:
            assert "retrying" in record.message
            assert (
                record.exc_info is not None
                and isinstance(record.exc_info[1], OSError)
                and record.exc_info[1].errno == errno_value
            )

    async def test____accept____reraise_other_OSErrors(
        self,
        listener: TrioListenerSocketAdapter,
        trio_backend: TrioBackend,
        mock_trio_socket_listener: MagicMock,
        handler: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)
        exc = OSError()
        mock_trio_socket_listener.accept.side_effect = exc

        # Act
        async with trio_backend.create_task_group() as task_group:
            with pytest.raises(OSError) as exc_info:
                await listener.serve(handler, task_group)

        # Assert
        assert len(caplog.records) == 0
        assert exc_info.value is exc

    async def test____get_backend____returns_linked_instance(
        self,
        trio_backend: TrioBackend,
        listener: TrioListenerSocketAdapter,
    ) -> None:
        # Arrange

        # Act & Assert
        assert listener.backend() is trio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        listener: TrioListenerSocketAdapter,
        local_address: tuple[str, int] | bytes,
        mock_trio_stream_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = listener.extra(SocketAttribute.socket)
        assert isinstance(trsock, SocketProxy)
        assert listener.extra(SocketAttribute.family) == mock_trio_stream_listener_socket.family
        assert listener.extra(SocketAttribute.sockname) == local_address
        assert listener.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value

        mock_trio_stream_listener_socket.reset_mock()
        trsock.fileno()
        mock_trio_stream_listener_socket.fileno.assert_called_once()
