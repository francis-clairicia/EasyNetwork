from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend
from easynetwork.lowlevel.api_async.backend.abc import TaskGroup
from easynetwork.lowlevel.socket import SocketAttribute, SocketProxy

import pytest

from ....fixtures.trio import trio_fixture
from ...base import BaseTestSocket

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter
    from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioDatagramSocketAdapter(BaseTestSocket):
    @pytest.fixture
    @classmethod
    def mock_trio_udp_socket(cls, mock_trio_udp_socket: MagicMock) -> MagicMock:
        cls.set_local_address_to_socket_mock(mock_trio_udp_socket, mock_trio_udp_socket.family, ("127.0.0.1", 11111))
        cls.set_remote_address_to_socket_mock(mock_trio_udp_socket, mock_trio_udp_socket.family, ("127.0.0.1", 12345))
        return mock_trio_udp_socket

    @trio_fixture
    @staticmethod
    async def transport(
        trio_backend: TrioBackend,
        mock_trio_udp_socket: MagicMock,
    ) -> AsyncIterator[TrioDatagramSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        transport = TrioDatagramSocketAdapter(trio_backend, mock_trio_udp_socket)
        async with transport:
            yield transport

    async def test____dunder_init____invalid_socket_type(
        self,
        trio_backend: TrioBackend,
        mock_trio_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = TrioDatagramSocketAdapter(trio_backend, mock_trio_tcp_socket)

    async def test____dunder_del____ResourceWarning(
        self,
        trio_backend: TrioBackend,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        transport = TrioDatagramSocketAdapter(trio_backend, mock_trio_udp_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_trio_udp_socket.close.assert_called()

    async def test____aclose____close_transport_and_wait(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        import trio.testing

        assert not transport.is_closing()

        # Act
        with trio.testing.assert_checkpoints():
            await transport.aclose()

        # Assert
        mock_trio_udp_socket.close.assert_called_once()
        assert transport.is_closing()

    async def test____recv____read_from_reader(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        mock_trio_udp_socket.recv.return_value = b"data"

        # Act
        data: bytes = await transport.recv()

        # Assert
        mock_trio_udp_socket.recv.assert_awaited_once_with(TrioDatagramSocketAdapter.MAX_DATAGRAM_BUFSIZE)
        assert data == b"data"

    async def test____send____write_on_socket(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_udp_socket.send.side_effect = lambda data: memoryview(data).nbytes

        # Act
        await transport.send(b"data to send")

        # Assert
        mock_trio_udp_socket.send.assert_awaited_once_with(b"data to send")

    async def test____get_backend____returns_linked_instance(
        self,
        transport: TrioDatagramSocketAdapter,
        trio_backend: TrioBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert transport.backend() is trio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = transport.extra(SocketAttribute.socket)
        assert isinstance(trsock, SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_trio_udp_socket.family
        assert transport.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert transport.extra(SocketAttribute.peername) == ("127.0.0.1", 12345)

        mock_trio_udp_socket.reset_mock()
        trsock.fileno()
        mock_trio_udp_socket.fileno.assert_called_once()


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioDatagramListenerSocketAdapter(BaseTestSocket):
    @pytest.fixture
    @classmethod
    def mock_udp_listener_socket(
        cls,
        mock_udp_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_socket = mock_udp_socket_factory()
        cls.set_local_address_to_socket_mock(mock_socket, mock_socket.family, ("127.0.0.1", 11111))
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_socket)
        return mock_socket

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_trio_lowlevel_notify_closing(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("trio.lowlevel.notify_closing", autospec=True, return_value=None)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_trio_lowlevel_wait_readable(mocker: MockerFixture) -> AsyncMock:
        import trio

        async def wait_readable(sock: Any) -> None:
            await trio.lowlevel.checkpoint()

        return mocker.patch("trio.lowlevel.wait_readable", autospec=True, side_effect=wait_readable)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_trio_lowlevel_wait_writable(mocker: MockerFixture) -> AsyncMock:
        import trio

        async def wait_writable(sock: Any) -> None:
            await trio.lowlevel.checkpoint()

        return mocker.patch("trio.lowlevel.wait_writable", autospec=True, side_effect=wait_writable)

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
        mock_udp_listener_socket: MagicMock,
    ) -> AsyncIterator[TrioDatagramListenerSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        listener = TrioDatagramListenerSocketAdapter(trio_backend, mock_udp_listener_socket)
        async with listener:
            yield listener

    @staticmethod
    async def _get_cancelled_exc() -> BaseException:
        import outcome
        import trio

        with trio.move_on_after(0):
            result = await outcome.acapture(trio.sleep_forever)

        assert isinstance(result, outcome.Error)
        return result.error.with_traceback(None)

    async def test____dunder_init____invalid_socket_type(
        self,
        trio_backend: TrioBackend,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = TrioDatagramListenerSocketAdapter(trio_backend, mock_tcp_socket)

    async def test____dunder_del____ResourceWarning(
        self,
        trio_backend: TrioBackend,
        mock_udp_listener_socket: MagicMock,
        mock_trio_lowlevel_notify_closing: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        listener = TrioDatagramListenerSocketAdapter(trio_backend, mock_udp_listener_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del listener

        mock_udp_listener_socket.close.assert_called()
        mock_trio_lowlevel_notify_closing.assert_not_called()

    async def test____aclose____close_socket(
        self,
        listener: TrioDatagramListenerSocketAdapter,
        mock_udp_listener_socket: MagicMock,
        mock_trio_lowlevel_notify_closing: MagicMock,
    ) -> None:
        # Arrange
        import trio.testing

        assert not listener.is_closing()

        # Act
        with trio.testing.assert_checkpoints():
            await listener.aclose()

        # Assert
        assert listener.is_closing()
        mock_trio_lowlevel_notify_closing.assert_called_once_with(mock_udp_listener_socket)
        mock_udp_listener_socket.close.assert_called_once_with()

    async def test____aclose____do_not_notify_twice(
        self,
        listener: TrioDatagramListenerSocketAdapter,
        mock_udp_listener_socket: MagicMock,
        mock_trio_lowlevel_notify_closing: MagicMock,
    ) -> None:
        # Arrange
        await listener.aclose()
        assert listener.is_closing()

        # Act
        await listener.aclose()

        # Assert
        mock_trio_lowlevel_notify_closing.assert_called_once_with(mock_udp_listener_socket)
        mock_udp_listener_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____default(
        self,
        trio_backend: TrioBackend,
        listener: TrioDatagramListenerSocketAdapter,
        external_group: bool,
        handler: AsyncMock,
        mock_udp_listener_socket: MagicMock,
        mock_trio_lowlevel_wait_readable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        import trio

        mock_udp_listener_socket.recvfrom.side_effect = [
            BlockingIOError,
            (b"received_datagram", ("127.0.0.1", 12345)),
            (b"received_datagram_2", ("127.0.0.1", 54321)),
            BlockingIOError,
            (await self._get_cancelled_exc()),
        ]

        # Act
        task_group: TaskGroup | None
        async with trio_backend.create_task_group() if external_group else contextlib.nullcontext() as task_group:  # type: ignore[attr-defined]
            with pytest.raises(trio.Cancelled):
                await listener.serve(handler, task_group)

        # Assert
        assert handler.await_args_list == [
            mocker.call(b"received_datagram", ("127.0.0.1", 12345)),
            mocker.call(b"received_datagram_2", ("127.0.0.1", 54321)),
        ]
        assert mock_trio_lowlevel_wait_readable.await_args_list == [mocker.call(mock_udp_listener_socket) for _ in range(2)]

    @pytest.mark.parametrize("block_count", [2, 1, 0], ids=lambda count: f"block_count=={count}")
    async def test____send_to____write_on_socket(
        self,
        block_count: int,
        listener: TrioDatagramListenerSocketAdapter,
        mock_udp_listener_socket: MagicMock,
        mock_trio_lowlevel_wait_writable: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_wait_writable_nb_calls: int = block_count

        def sendto_side_effect(data: ReadableBuffer, *args: Any) -> int:
            nonlocal block_count

            if block_count > 0:
                block_count -= 1
                raise BlockingIOError
            return memoryview(data).nbytes

        mock_udp_listener_socket.sendto.side_effect = sendto_side_effect

        # Act
        await listener.send_to(b"data to send", ("127.0.0.1", 12345))

        # Assert
        mock_udp_listener_socket.sendto.assert_called_with(b"data to send", ("127.0.0.1", 12345))
        assert mock_trio_lowlevel_wait_writable.await_args_list == [
            mocker.call(mock_udp_listener_socket) for _ in range(expected_wait_writable_nb_calls)
        ]

    async def test____get_backend____returns_linked_instance(
        self,
        trio_backend: TrioBackend,
        listener: TrioDatagramListenerSocketAdapter,
    ) -> None:
        # Arrange

        # Act & Assert
        assert listener.backend() is trio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        listener: TrioDatagramListenerSocketAdapter,
        mock_udp_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = listener.extra(SocketAttribute.socket)
        assert isinstance(trsock, SocketProxy)
        assert listener.extra(SocketAttribute.family) == mock_udp_listener_socket.family
        assert listener.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert listener.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value

        mock_udp_listener_socket.reset_mock()
        trsock.fileno()
        mock_udp_listener_socket.fileno.assert_called_once()
