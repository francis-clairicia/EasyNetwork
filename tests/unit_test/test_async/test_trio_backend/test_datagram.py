from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable, Coroutine
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

    from pytest_mock import MockerFixture


@pytest.mark.feature_trio
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


@pytest.mark.feature_trio
class TestTrioDatagramListenerSocketAdapter(BaseTestSocket):
    @pytest.fixture
    @classmethod
    def mock_trio_udp_listener_socket(
        cls,
        mock_trio_udp_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_socket = mock_trio_udp_socket_factory()
        cls.set_local_address_to_socket_mock(mock_socket, mock_socket.family, ("127.0.0.1", 11111))
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_socket)
        return mock_socket

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
        mock_trio_udp_listener_socket: MagicMock,
    ) -> AsyncIterator[TrioDatagramListenerSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        listener = TrioDatagramListenerSocketAdapter(trio_backend, mock_trio_udp_listener_socket)
        async with listener:
            yield listener

    @staticmethod
    def _make_recvfrom_into_side_effect(
        side_effect: Any,
        mocker: MockerFixture,
        sleep_time: float = 0,
    ) -> Callable[[bytearray | memoryview], Coroutine[Any, Any, tuple[int, Any]]]:
        import trio

        next_datagram_cb = mocker.AsyncMock(side_effect=side_effect)

        def write_in_buffer(buffer: memoryview, to_write: bytes) -> int:
            nbytes = len(to_write)
            buffer[:nbytes] = to_write
            return nbytes

        async def recvfrom_into_side_effect(buffer: bytearray | memoryview) -> tuple[int, Any]:
            await trio.sleep(sleep_time)
            datagram: bytes
            address: tuple[Any, ...]
            datagram, address = await next_datagram_cb()
            with memoryview(buffer) as buffer:
                return write_in_buffer(buffer, datagram), address

        return recvfrom_into_side_effect

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
        mock_trio_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = TrioDatagramListenerSocketAdapter(trio_backend, mock_trio_tcp_socket)

    async def test____dunder_del____ResourceWarning(
        self,
        trio_backend: TrioBackend,
        mock_trio_udp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        listener = TrioDatagramListenerSocketAdapter(trio_backend, mock_trio_udp_listener_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del listener

        mock_trio_udp_listener_socket.close.assert_called()

    async def test____aclose____close_socket(
        self,
        listener: TrioDatagramListenerSocketAdapter,
        mock_trio_udp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        import trio.testing

        assert not listener.is_closing()

        # Act
        with trio.testing.assert_checkpoints():
            await listener.aclose()

        # Assert
        assert listener.is_closing()
        mock_trio_udp_listener_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____default(
        self,
        trio_backend: TrioBackend,
        listener: TrioDatagramListenerSocketAdapter,
        external_group: bool,
        handler: AsyncMock,
        mock_trio_udp_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        import trio

        mock_trio_udp_listener_socket.recvfrom_into.side_effect = self._make_recvfrom_into_side_effect(
            [(b"received_datagram", ("127.0.0.1", 12345)), (await self._get_cancelled_exc())],
            mocker,
            sleep_time=0.1,
        )

        # Act
        task_group: TaskGroup | None
        async with trio_backend.create_task_group() if external_group else contextlib.nullcontext() as task_group:  # type: ignore[attr-defined]
            with pytest.raises(trio.Cancelled):
                await listener.serve(handler, task_group)

        # Assert
        handler.assert_awaited_once_with(b"received_datagram", ("127.0.0.1", 12345))

    async def test____send_to____write_on_socket(
        self,
        listener: TrioDatagramListenerSocketAdapter,
        mock_trio_udp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_udp_listener_socket.sendto.side_effect = lambda data, *args: memoryview(data).nbytes

        # Act
        await listener.send_to(b"data to send", ("127.0.0.1", 12345))

        # Assert
        mock_trio_udp_listener_socket.sendto.assert_awaited_once_with(b"data to send", ("127.0.0.1", 12345))

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
        mock_trio_udp_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = listener.extra(SocketAttribute.socket)
        assert isinstance(trsock, SocketProxy)
        assert listener.extra(SocketAttribute.family) == mock_trio_udp_listener_socket.family
        assert listener.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert listener.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value

        mock_trio_udp_listener_socket.reset_mock()
        trsock.fileno()
        mock_trio_udp_listener_socket.fileno.assert_called_once()
