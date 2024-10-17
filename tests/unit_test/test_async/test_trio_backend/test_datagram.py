from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend
from easynetwork.lowlevel.api_async.backend.abc import TaskGroup
from easynetwork.lowlevel.socket import SocketAttribute, SocketProxy

import pytest

from ....fixtures.trio import trio_fixture
from ...base import BaseTestSocketTransport

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter
    from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioDatagramSocketAdapter(BaseTestSocketTransport):
    @pytest.fixture
    @classmethod
    def mock_trio_datagram_socket(
        cls,
        socket_family_name: str,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_trio_udp_socket_factory: Callable[[], MagicMock],
        mock_trio_unix_datagram_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_trio_datagram_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_trio_datagram_socket = mock_trio_udp_socket_factory()
            case "AF_UNIX":
                mock_trio_datagram_socket = mock_trio_unix_datagram_socket_factory()
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_trio_datagram_socket, mock_trio_datagram_socket.family, local_address)
        cls.set_remote_address_to_socket_mock(mock_trio_datagram_socket, mock_trio_datagram_socket.family, remote_address)
        return mock_trio_datagram_socket

    @trio_fixture
    @staticmethod
    async def transport(
        trio_backend: TrioBackend,
        mock_trio_datagram_socket: MagicMock,
    ) -> AsyncIterator[TrioDatagramSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        transport = TrioDatagramSocketAdapter(trio_backend, mock_trio_datagram_socket)
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
        mock_trio_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        transport = TrioDatagramSocketAdapter(trio_backend, mock_trio_datagram_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_trio_datagram_socket.close.assert_called()

    async def test____aclose____close_transport_and_wait(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        import trio.testing

        assert not transport.is_closing()

        # Act
        with trio.testing.assert_checkpoints():
            await transport.aclose()

        # Assert
        mock_trio_datagram_socket.close.assert_called_once()
        assert transport.is_closing()

    async def test____recv____read_from_reader(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.socket import TrioDatagramSocketAdapter

        mock_trio_datagram_socket.recv.return_value = b"data"

        # Act
        data: bytes = await transport.recv()

        # Assert
        mock_trio_datagram_socket.recv.assert_awaited_once_with(TrioDatagramSocketAdapter.MAX_DATAGRAM_BUFSIZE)
        assert data == b"data"

    async def test____send____write_on_socket(
        self,
        transport: TrioDatagramSocketAdapter,
        mock_trio_datagram_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_trio_datagram_socket.send.side_effect = lambda data: memoryview(data).nbytes

        # Act
        await transport.send(b"data to send")

        # Assert
        mock_trio_datagram_socket.send.assert_awaited_once_with(b"data to send")

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
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_trio_datagram_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = transport.extra(SocketAttribute.socket)
        assert isinstance(trsock, SocketProxy)
        assert transport.extra(SocketAttribute.family) == mock_trio_datagram_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        assert transport.extra(SocketAttribute.peername) == remote_address

        mock_trio_datagram_socket.reset_mock()
        trsock.fileno()
        mock_trio_datagram_socket.fileno.assert_called_once()


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioDatagramListenerSocketAdapter(BaseTestSocketTransport):
    @pytest.fixture
    @classmethod
    def mock_datagram_listener_socket(
        cls,
        socket_family_name: str,
        local_address: tuple[str, int] | bytes,
        mock_udp_socket_factory: Callable[[], MagicMock],
        mock_unix_datagram_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_datagram_listener_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_datagram_listener_socket = mock_udp_socket_factory()
            case "AF_UNIX":
                mock_datagram_listener_socket = mock_unix_datagram_socket_factory()
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_datagram_listener_socket, mock_datagram_listener_socket.family, local_address)
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_datagram_listener_socket)
        return mock_datagram_listener_socket

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
        mock_datagram_listener_socket: MagicMock,
    ) -> AsyncIterator[TrioDatagramListenerSocketAdapter]:
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        listener = TrioDatagramListenerSocketAdapter(trio_backend, mock_datagram_listener_socket)
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
        mock_datagram_listener_socket: MagicMock,
        mock_trio_lowlevel_notify_closing: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.datagram.listener import TrioDatagramListenerSocketAdapter

        listener = TrioDatagramListenerSocketAdapter(trio_backend, mock_datagram_listener_socket)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del listener

        mock_datagram_listener_socket.close.assert_called()
        mock_trio_lowlevel_notify_closing.assert_not_called()

    async def test____aclose____close_socket(
        self,
        listener: TrioDatagramListenerSocketAdapter,
        mock_datagram_listener_socket: MagicMock,
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
        mock_trio_lowlevel_notify_closing.assert_called_once_with(mock_datagram_listener_socket)
        mock_datagram_listener_socket.close.assert_called_once_with()

    async def test____aclose____do_not_notify_twice(
        self,
        listener: TrioDatagramListenerSocketAdapter,
        mock_datagram_listener_socket: MagicMock,
        mock_trio_lowlevel_notify_closing: MagicMock,
    ) -> None:
        # Arrange
        await listener.aclose()
        assert listener.is_closing()

        # Act
        await listener.aclose()

        # Assert
        mock_trio_lowlevel_notify_closing.assert_called_once_with(mock_datagram_listener_socket)
        mock_datagram_listener_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    @pytest.mark.parametrize(
        ["socket_family_name", "sender_address_1", "sender_address_2", "sender_address_3"],
        [
            pytest.param("AF_INET", ("127.0.0.1", 12345), ("127.0.0.1", 54321), ("127.0.0.1", 11111)),
            pytest.param("AF_UNIX", "/path/to/unix.sock", "/path/to/other.sock", "/path/to/third.sock"),
            pytest.param("AF_UNIX", b"\x00abstract_address", b"\x00abstract_other_address", b"\x00abstract_third_address"),
            pytest.param("AF_UNIX", None, None, None),
            pytest.param("AF_UNIX", b"", b"", b""),
            pytest.param("AF_UNIX", "", "", ""),
        ],
        indirect=["socket_family_name"],
    )
    async def test____serve____default(
        self,
        trio_backend: TrioBackend,
        listener: TrioDatagramListenerSocketAdapter,
        external_group: bool,
        sender_address_1: tuple[str, int] | str | bytes | None,
        sender_address_2: tuple[str, int] | str | bytes | None,
        sender_address_3: tuple[str, int] | str | bytes | None,
        handler: AsyncMock,
        mock_datagram_listener_socket: MagicMock,
        mock_trio_lowlevel_wait_readable: AsyncMock,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level("INFO", listener.__class__.__module__)

        import trio

        mock_datagram_listener_socket.recvfrom.side_effect = [
            BlockingIOError,
            (b"received_datagram", sender_address_1),
            (b"received_datagram_2", sender_address_2),
            BlockingIOError,
            OSError("Unrelated OS Error"),
            (b"received_datagram_3", sender_address_3),
            BlockingIOError,
            (await self._get_cancelled_exc()),
        ]

        # Act
        task_group: TaskGroup | None
        async with trio_backend.create_task_group() if external_group else contextlib.nullcontext() as task_group:
            with pytest.raises(trio.Cancelled):
                await listener.serve(handler, task_group)

        # Assert
        assert handler.await_args_list == [
            mocker.call(b"received_datagram", sender_address_1),
            mocker.call(b"received_datagram_2", sender_address_2),
            mocker.call(b"received_datagram_3", sender_address_3),
        ]
        assert mock_trio_lowlevel_wait_readable.await_args_list == [mocker.call(mock_datagram_listener_socket) for _ in range(3)]
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].getMessage() == "Unrelated error occurred on datagram reception: OSError: Unrelated OS Error"
        assert caplog.records[0].exc_info is not None and isinstance(caplog.records[0].exc_info[1], OSError)

    @pytest.mark.parametrize("block_count", [2, 1, 0], ids=lambda count: f"block_count=={count}")
    @pytest.mark.parametrize(
        ["socket_family_name", "destination_address"],
        [
            pytest.param("AF_INET", ("127.0.0.1", 12345)),
            pytest.param("AF_UNIX", "/path/to/unix.sock"),
            pytest.param("AF_UNIX", b"\x00abstract_address"),
        ],
        indirect=["socket_family_name"],
    )
    async def test____send_to____write_on_socket(
        self,
        block_count: int,
        destination_address: tuple[str, int] | str | bytes,
        listener: TrioDatagramListenerSocketAdapter,
        mock_datagram_listener_socket: MagicMock,
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

        mock_datagram_listener_socket.sendto.side_effect = sendto_side_effect

        # Act
        await listener.send_to(b"data to send", destination_address)

        # Assert
        mock_datagram_listener_socket.sendto.assert_called_with(b"data to send", destination_address)
        assert mock_trio_lowlevel_wait_writable.await_args_list == [
            mocker.call(mock_datagram_listener_socket) for _ in range(expected_wait_writable_nb_calls)
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
        local_address: tuple[str, int] | bytes,
        mock_datagram_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = listener.extra(SocketAttribute.socket)
        assert isinstance(trsock, SocketProxy)
        assert listener.extra(SocketAttribute.family) == mock_datagram_listener_socket.family
        assert listener.extra(SocketAttribute.sockname) == local_address
        assert listener.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value

        mock_datagram_listener_socket.reset_mock()
        trsock.fileno()
        mock_datagram_listener_socket.fileno.assert_called_once()
