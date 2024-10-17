from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from errno import ECONNABORTED
from socket import AI_PASSIVE
from typing import TYPE_CHECKING, Any, Literal, cast

from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.endpoint import (
    DatagramEndpoint,
    DatagramEndpointProtocol,
    create_datagram_endpoint,
)
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.listener import (
    DatagramListenerProtocol,
    DatagramListenerSocketAdapter,
)
from easynetwork.lowlevel.api_async.backend._asyncio.datagram.socket import AsyncioTransportDatagramSocketAdapter
from easynetwork.lowlevel.api_async.backend._asyncio.tasks import TaskGroup as AsyncIOTaskGroup
from easynetwork.lowlevel.socket import SocketAttribute

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

from ..._utils import partial_eq
from ...base import BaseTestSocketTransport


class CustomException(Exception):
    """Helper to test exception_queue usage"""


@pytest.mark.asyncio
@pytest.mark.parametrize("local_address", ["local_address", None], ids=lambda p: f"local_address=={p}")
@pytest.mark.parametrize("remote_address", ["remote_address", None], ids=lambda p: f"remote_address=={p}")
@pytest.mark.parametrize("reuse_port", [False, True], ids=lambda p: f"reuse_port=={p}")
async def test____create_datagram_endpoint____return_DatagramEndpoint_instance(
    local_address: Any | None,
    remote_address: Any | None,
    reuse_port: bool,
    mocker: MockerFixture,
) -> None:
    # Arrange
    event_loop = asyncio.get_running_loop()
    if local_address is not None:
        local_address = getattr(mocker.sentinel, local_address)
    if remote_address is not None:
        remote_address = getattr(mocker.sentinel, remote_address)
    mock_DatagramEndpoint = mocker.patch(
        f"{create_datagram_endpoint.__module__}.DatagramEndpoint",
        return_value=mocker.sentinel.endpoint,
    )
    mock_loop_create_datagram_endpoint: AsyncMock = cast(
        "AsyncMock",
        mocker.patch.object(
            event_loop,
            "create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=(
                mocker.sentinel.transport,
                mocker.sentinel.protocol,
            ),
        ),
    )
    expected_flags: int = 0
    if remote_address is not None:
        expected_flags |= AI_PASSIVE

    # Act
    endpoint = await create_datagram_endpoint(
        family=mocker.sentinel.socket_family,
        local_addr=local_address,
        remote_addr=remote_address,
        reuse_port=reuse_port,
        sock=mocker.sentinel.stdlib_socket,
    )

    # Assert
    mock_loop_create_datagram_endpoint.assert_awaited_once_with(
        partial_eq(DatagramEndpointProtocol, loop=event_loop, recv_queue=mocker.ANY, exception_queue=mocker.ANY),
        family=mocker.sentinel.socket_family,
        local_addr=local_address,
        remote_addr=remote_address,
        reuse_port=reuse_port,
        sock=mocker.sentinel.stdlib_socket,
        flags=expected_flags,
    )
    mock_DatagramEndpoint.assert_called_once_with(
        mocker.sentinel.transport,
        mocker.sentinel.protocol,
        recv_queue=mocker.ANY,
        exception_queue=mocker.ANY,
    )
    assert endpoint is mocker.sentinel.endpoint


@pytest.mark.asyncio
class TestDatagramEndpoint:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_protocol(mocker: MockerFixture, event_loop: asyncio.AbstractEventLoop) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=DatagramEndpointProtocol)
        # Currently, _get_close_waiter() is a synchronous function returning a Future, but it will be awaited so this works
        mock._get_close_waiter = mocker.AsyncMock()
        mock._get_loop.return_value = event_loop
        return mock

    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.DatagramTransport)

        def close_side_effect() -> None:
            mock.is_closing.return_value = True

        mock.is_closing.return_value = False
        mock.close.side_effect = close_side_effect
        return mock

    @staticmethod
    def _mock_queue_factory(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=asyncio.Queue)

    @pytest.fixture
    @classmethod
    def mock_asyncio_recv_queue(cls, mocker: MockerFixture) -> MagicMock:
        return cls._mock_queue_factory(mocker)

    @pytest.fixture
    @classmethod
    def mock_asyncio_exception_queue(cls, mocker: MockerFixture) -> MagicMock:
        return cls._mock_queue_factory(mocker)

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> Iterator[DatagramEndpoint]:
        endpoint = DatagramEndpoint(
            mock_asyncio_transport,
            mock_asyncio_protocol,
            recv_queue=mock_asyncio_recv_queue,
            exception_queue=mock_asyncio_exception_queue,
        )
        try:
            yield endpoint
        finally:
            mock_asyncio_transport.is_closing.side_effect = None
            endpoint.close_nowait()
            mock_asyncio_transport.is_closing.return_value = True

    async def test____dunder_del____ResourceWarning(
        self,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        endpoint = DatagramEndpoint(
            mock_asyncio_transport,
            mock_asyncio_protocol,
            recv_queue=mock_asyncio_recv_queue,
            exception_queue=mock_asyncio_exception_queue,
        )

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed endpoint .+$"):
            del endpoint

        mock_asyncio_transport.close.assert_called()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____close_transport_and_wait(
        self,
        transport_is_closing: bool,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing

        # Act
        await endpoint.aclose()

        # Assert
        if transport_is_closing:
            mock_asyncio_transport.close.assert_not_called()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        else:
            mock_asyncio_transport.close.assert_called_once_with()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        mock_asyncio_transport.abort.assert_not_called()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____abort_transport_if_cancelled(
        self,
        transport_is_closing: bool,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing
        mock_asyncio_protocol._get_close_waiter.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await endpoint.aclose()

        # Assert
        if transport_is_closing:
            mock_asyncio_transport.close.assert_not_called()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        else:
            mock_asyncio_transport.close.assert_called_once_with()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        mock_asyncio_transport.abort.assert_not_called()

    async def test____is_closing____return_transport_state(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = mocker.sentinel.is_closing

        # Act
        state = endpoint.is_closing()

        # Assert
        mock_asyncio_transport.is_closing.assert_called_once_with()
        assert state is mocker.sentinel.is_closing

    @pytest.mark.parametrize(
        "expected_address",
        [("an_address", 12345), "/path/to/unix.sock", b"\x00abstract_sock", None],
        ids=repr,
    )
    async def test____recvfrom____await_recv_queue(
        self,
        expected_address: Any,
        endpoint: DatagramEndpoint,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_recv_queue.get.return_value = (b"some data", expected_address)
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty

        # Act
        data, address = await endpoint.recvfrom()

        # Assert
        mock_asyncio_recv_queue.get.assert_awaited_once_with()
        mock_asyncio_recv_queue.get_nowait.assert_not_called()
        assert data == b"some data"
        assert address == expected_address

    @pytest.mark.parametrize(
        "expected_address",
        [("an_address", 12345), "/path/to/unix.sock", b"\x00abstract_sock", None],
        ids=repr,
    )
    async def test____recvfrom____connection_lost____transport_already_closed____data_in_queue(
        self,
        expected_address: Any,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty
        mock_asyncio_transport.is_closing.return_value = True
        mock_asyncio_recv_queue.get_nowait.return_value = (b"some data", expected_address)

        # Act
        data, address = await endpoint.recvfrom()

        # Assert
        mock_asyncio_exception_queue.get_nowait.assert_not_called()
        mock_asyncio_recv_queue.get.assert_not_awaited()
        mock_asyncio_recv_queue.get_nowait.assert_called_once()
        assert data == b"some data"
        assert address == expected_address

    @pytest.mark.parametrize("condition", ["empty_queue", "None_pushed"])
    @pytest.mark.parametrize("exception", [CustomException, None])
    async def test____recvfrom____connection_lost____transport_already_closed____no_more_data(
        self,
        endpoint: DatagramEndpoint,
        exception: type[CustomException] | None,
        condition: Literal["empty_queue", "None_pushed"],
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        if exception is None:
            mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty
        else:
            mock_asyncio_exception_queue.get_nowait.return_value = exception()
        mock_asyncio_transport.is_closing.return_value = True

        match condition:
            case "empty_queue":
                mock_asyncio_recv_queue.get_nowait.side_effect = asyncio.QueueEmpty
            case "None_pushed":
                mock_asyncio_recv_queue.get_nowait.side_effect = [None]
            case _:
                pytest.fail("Invalid condition")

        # Act & Assert
        if exception is None:
            with pytest.raises(OSError) as exc_info:
                await endpoint.recvfrom()
            assert exc_info.value.errno == ECONNABORTED
        else:
            with pytest.raises(exception):
                await endpoint.recvfrom()

        # Assert
        mock_asyncio_exception_queue.get_nowait.assert_called_once()
        mock_asyncio_recv_queue.get.assert_not_awaited()
        mock_asyncio_recv_queue.get_nowait.assert_called_once()

    async def test____recvfrom____connection_lost____transport_closed_by_protocol_while_waiting(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        from errno import ECONNABORTED

        mock_asyncio_recv_queue.get.return_value = None  # None is sent to queue when readers must wake up
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty
        mock_asyncio_transport.is_closing.side_effect = [False, True]  # 1st call OK, 2nd not so much

        # Act
        with pytest.raises(OSError) as exc_info:
            await endpoint.recvfrom()

        # Assert
        assert exc_info.value.errno == ECONNABORTED
        mock_asyncio_exception_queue.get_nowait.assert_called_once_with()
        mock_asyncio_recv_queue.get.assert_awaited_once_with()

    async def test____recvfrom____raise_exception____transport_closed_by_protocol_with_exception_while_waiting(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_recv_queue.get.return_value = None  # None is sent to queue when readers must wake up
        mock_asyncio_exception_queue.get_nowait.return_value = CustomException()
        mock_asyncio_transport.is_closing.side_effect = [False, True]  # 1st call OK, 2nd not so much

        # Act
        with pytest.raises(CustomException):
            await endpoint.recvfrom()

        # Assert
        mock_asyncio_exception_queue.get_nowait.assert_called_once_with()
        mock_asyncio_recv_queue.get.assert_awaited_once_with()

    @pytest.mark.parametrize("address", [("127.0.0.1", 12345), "/path/to/unix.sock", b"\x00abstract_sock", None], ids=repr)
    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____sendto____send_and_await_drain(
        self,
        transport_is_closing: bool,
        endpoint: DatagramEndpoint,
        address: tuple[str, int] | str | bytes | None,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.side_effect = [transport_is_closing]
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty

        # Act
        await endpoint.sendto(b"some data", address)

        # Assert
        mock_asyncio_exception_queue.get_nowait.assert_not_called()
        mock_asyncio_transport.sendto.assert_called_once_with(b"some data", address)
        mock_asyncio_protocol._drain_helper.assert_awaited_once_with()

    async def test____extra_attributes____get_transport_extra_info(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_transport.get_extra_info.return_value = mocker.sentinel.extra_info

        # Act
        value = endpoint.get_extra_info(mocker.sentinel.name, mocker.sentinel.default)

        # Assert
        mock_asyncio_transport.get_extra_info.assert_called_once_with(mocker.sentinel.name, mocker.sentinel.default)
        assert value is mocker.sentinel.extra_info


class TestDatagramEndpointProtocol:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.DatagramTransport)
        mock.is_closing.return_value = False

        # Tell connection_made() not to try to monkeypatch this mock object
        del mock._address

        return mock

    @staticmethod
    def _mock_queue_factory(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=asyncio.Queue)

    @pytest.fixture
    @classmethod
    def mock_asyncio_recv_queue(cls, mocker: MockerFixture) -> MagicMock:
        return cls._mock_queue_factory(mocker)

    @pytest.fixture
    @classmethod
    def mock_asyncio_exception_queue(cls, mocker: MockerFixture) -> MagicMock:
        return cls._mock_queue_factory(mocker)

    @pytest.fixture
    @staticmethod
    def protocol(
        event_loop: asyncio.AbstractEventLoop,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
        mock_asyncio_transport: MagicMock,
    ) -> DatagramEndpointProtocol:
        protocol = DatagramEndpointProtocol(
            loop=event_loop,
            recv_queue=mock_asyncio_recv_queue,
            exception_queue=mock_asyncio_exception_queue,
        )
        protocol.connection_made(mock_asyncio_transport)
        return protocol

    @pytest.mark.asyncio
    async def test____dunder_init____use_running_loop(
        self,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()

        # Act
        protocol = DatagramEndpointProtocol(recv_queue=mock_asyncio_recv_queue, exception_queue=mock_asyncio_exception_queue)

        # Assert
        assert protocol._get_loop() is event_loop

    def test____dunder_init____use_running_loop____not_in_asyncio_loop(
        self,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError):
            _ = DatagramEndpointProtocol(recv_queue=mock_asyncio_recv_queue, exception_queue=mock_asyncio_exception_queue)

    def test____connection_lost____by_closed_transport(
        self,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        close_waiter = protocol._get_close_waiter()
        assert not close_waiter.done()

        # Act
        protocol.connection_lost(None)
        protocol.connection_lost(None)  # Double call must not change anything

        # Assert
        assert close_waiter.done() and close_waiter.exception() is None and close_waiter.result() is None
        mock_asyncio_recv_queue.put_nowait.assert_called_once_with(None)
        mock_asyncio_exception_queue.put_nowait.assert_not_called()
        mock_asyncio_transport.close.assert_not_called()  # just to be sure :)

    def test____connection_lost____by_unrelated_error(
        self,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        exception = OSError("Something bad happen")

        close_waiter = protocol._get_close_waiter()
        assert not close_waiter.done()

        # Act
        protocol.connection_lost(exception)
        protocol.connection_lost(exception)  # Double call must not change anything

        # Assert
        assert close_waiter.done() and close_waiter.exception() is None
        mock_asyncio_recv_queue.put_nowait.assert_called_once_with(None)
        mock_asyncio_exception_queue.put_nowait.assert_called_once_with(exception)
        mock_asyncio_transport.close.assert_not_called()  # just to be sure :)

    @pytest.mark.parametrize(
        "expected_address",
        [("an_address", 12345), "/path/to/unix.sock", b"\x00abstract_sock", None],
        ids=repr,
    )
    def test____datagram_received____push_to_queue(
        self,
        expected_address: Any,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_recv_queue: MagicMock,
    ) -> None:
        # Arrange

        # Act
        protocol.datagram_received(b"datagram", expected_address)

        # Assert
        mock_asyncio_recv_queue.put_nowait.assert_called_once_with((b"datagram", expected_address))

    @pytest.mark.parametrize(
        "expected_address",
        [("an_address", 12345), "/path/to/unix.sock", b"\x00abstract_sock", None],
        ids=repr,
    )
    def test____datagram_received____do_not_push_to_queue_after_connection_lost(
        self,
        expected_address: Any,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_recv_queue: MagicMock,
    ) -> None:
        # Arrange
        protocol.connection_lost(None)
        mock_asyncio_recv_queue.put_nowait.reset_mock()  # Needed to use assert_not_called()

        # Act
        protocol.datagram_received(b"datagram", expected_address)

        # Assert
        mock_asyncio_recv_queue.put_nowait.assert_not_called()

    def test____error_received____push_to_queue(
        self,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        exception = OSError("Something bad happen")

        # Act
        protocol.error_received(exception)

        # Assert
        mock_asyncio_exception_queue.put_nowait.assert_called_once_with(exception)
        mock_asyncio_recv_queue.put_nowait.assert_called_once_with(None)

    def test____error_received____do_not_push_to_queue_after_connection_lost(
        self,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        exception = OSError("Something bad happen")
        protocol.connection_lost(None)
        mock_asyncio_exception_queue.put_nowait.reset_mock()  # Needed to use assert_not_called()
        mock_asyncio_recv_queue.put_nowait.reset_mock()  # Needed to use assert_not_called()

        # Act
        protocol.error_received(exception)

        # Assert
        mock_asyncio_exception_queue.put_nowait.assert_not_called()
        mock_asyncio_recv_queue.put_nowait.assert_not_called()

    @pytest.mark.asyncio
    async def test____drain_helper____quick_exit_if_not_paused(
        self,
        protocol: DatagramEndpointProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        assert not protocol._writing_paused()
        mock_create_future: MagicMock = mocker.patch.object(event_loop, "create_future")

        # Act
        await protocol._drain_helper()

        # Assert
        mock_create_future.assert_not_called()

    @pytest.mark.asyncio
    async def test____drain_helper____raise_connection_aborted_if_connection_is_lost(
        self,
        protocol: DatagramEndpointProtocol,
    ) -> None:
        # Arrange
        assert not protocol._writing_paused()

        from errno import ECONNABORTED

        protocol.connection_lost(None)

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            await protocol._drain_helper()

        assert exc_info.value.errno == ECONNABORTED

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cancel_tasks", [False, True], ids=lambda p: f"cancel_tasks_before=={p}")
    async def test____drain_helper____wait_during_writing_pause(
        self,
        cancel_tasks: bool,
        protocol: DatagramEndpointProtocol,
    ) -> None:
        # Arrange
        import inspect

        # Act
        protocol.pause_writing()
        assert protocol._writing_paused()
        tasks: set[asyncio.Task[None]] = set()
        for _ in range(10):
            tasks.add(asyncio.create_task(protocol._drain_helper()))
        await asyncio.sleep(0)  # Suspend to let the event loop start all tasks
        assert all(inspect.getcoroutinestate(t.get_coro()) == "CORO_SUSPENDED" for t in tasks)  # type: ignore[arg-type]
        if cancel_tasks:
            for t in tasks:
                t.cancel()
        protocol.resume_writing()
        await asyncio.sleep(0)  # Suspend to let the event loop run all tasks

        # Assert
        if cancel_tasks:
            assert all(t.done() and t.cancelled() for t in tasks)
        else:
            assert all(t.done() and t.exception() is None and t.result() is None for t in tasks)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception", [None, OSError("Something bad happen")])
    @pytest.mark.parametrize("cancel_tasks", [False, True], ids=lambda p: f"cancel_tasks_before=={p}")
    async def test____drain_helper____wait_during_writing_pause____connection_lost_while_waiting(
        self,
        cancel_tasks: bool,
        exception: Exception | None,
        protocol: DatagramEndpointProtocol,
    ) -> None:
        # Arrange
        import inspect

        protocol.pause_writing()
        assert protocol._writing_paused()
        tasks: set[asyncio.Task[None]] = set()
        for _ in range(10):
            tasks.add(asyncio.create_task(protocol._drain_helper()))
        await asyncio.sleep(0)  # Suspend to let the event loop start all tasks
        assert all(inspect.getcoroutinestate(t.get_coro()) == "CORO_SUSPENDED" for t in tasks)  # type: ignore[arg-type]
        if cancel_tasks:
            for t in tasks:
                t.cancel()

        # Act
        protocol.connection_lost(exception)
        await asyncio.sleep(0)  # Suspend to let the event loop run all tasks

        # Assert
        if cancel_tasks:
            assert all(t.done() and t.cancelled() for t in tasks)
        elif exception is None:
            assert all(t.done() and isinstance(t.exception(), ConnectionAbortedError) for t in tasks), tasks
        else:
            assert all(t.done() and t.exception() is exception for t in tasks)


@pytest.mark.asyncio
class BaseTestAsyncioDatagramTransport(BaseTestSocketTransport):
    @pytest.fixture
    @classmethod
    def mock_datagram_socket(
        cls,
        socket_family_name: str,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes | None,
        mock_udp_socket_factory: Callable[[], MagicMock],
        mock_unix_datagram_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_datagram_socket: MagicMock

        match socket_family_name:
            case "AF_INET":
                mock_datagram_socket = mock_udp_socket_factory()
            case "AF_UNIX":
                mock_datagram_socket = mock_unix_datagram_socket_factory()
            case _:
                pytest.fail(f"Invalid param: {socket_family_name!r}")

        cls.set_local_address_to_socket_mock(mock_datagram_socket, mock_datagram_socket.family, local_address)
        if remote_address is None:
            cls.configure_socket_mock_to_raise_ENOTCONN(mock_datagram_socket)
        else:
            cls.set_remote_address_to_socket_mock(mock_datagram_socket, mock_datagram_socket.family, remote_address)

        return mock_datagram_socket

    @pytest.fixture
    @staticmethod
    def asyncio_transport_extra_info(
        mock_datagram_socket: MagicMock,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes | None,
    ) -> dict[str, Any]:
        return {
            "socket": mock_datagram_socket,
            "sockname": local_address,
            "peername": remote_address,
        }

    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(asyncio_transport_extra_info: dict[str, Any], mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.DatagramTransport)
        mock.get_extra_info.side_effect = asyncio_transport_extra_info.get
        mock.is_closing.return_value = False
        return mock

    @pytest.fixture
    @staticmethod
    def endpoint_extra_info(asyncio_transport_extra_info: dict[str, Any]) -> dict[str, Any]:
        return asyncio_transport_extra_info

    @pytest.fixture
    @staticmethod
    def mock_endpoint(
        endpoint_extra_info: dict[str, Any],
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock = mock_datagram_endpoint_factory()
        mock.get_extra_info.side_effect = endpoint_extra_info.get
        return mock


@pytest.mark.asyncio
class TestAsyncioTransportDatagramSocketAdapter(BaseTestAsyncioDatagramTransport):
    @pytest_asyncio.fixture
    @classmethod
    async def transport(
        cls,
        asyncio_backend: AsyncIOBackend,
        mock_endpoint: MagicMock,
    ) -> AsyncIterator[AsyncioTransportDatagramSocketAdapter]:
        transport = AsyncioTransportDatagramSocketAdapter(asyncio_backend, mock_endpoint)
        try:
            async with transport:
                yield transport
        finally:
            mock_endpoint.is_closing.side_effect = None
            mock_endpoint.is_closing.return_value = True

    async def test____dunder_del____ResourceWarning(
        self,
        asyncio_backend: AsyncIOBackend,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        transport = AsyncioTransportDatagramSocketAdapter(asyncio_backend, mock_endpoint)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_endpoint.close_nowait.assert_called()
        mock_endpoint.aclose.assert_not_called()

    async def test____aclose____close_transport_and_wait(
        self,
        transport: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await transport.aclose()

        # Assert
        mock_endpoint.aclose.assert_awaited_once_with()
        mock_endpoint.close_nowait.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    async def test____is_closing____return_internal_flag(
        self,
        transport_closed: bool,
        transport: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        if transport_closed:
            await transport.aclose()
            mock_endpoint.reset_mock()

        # Act
        state = transport.is_closing()

        # Assert
        mock_endpoint.is_closing.assert_not_called()
        assert state is transport_closed

    async def test____recv____read_from_reader(
        self,
        transport: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        received_data = b"data"
        mock_endpoint.recvfrom.return_value = (received_data, ("127.0.0.1", 12345))

        # Act
        data = await transport.recv()

        # Assert
        mock_endpoint.recvfrom.assert_awaited_once_with()
        assert data is received_data  # Should not be copied

    async def test____send____write_and_drain(
        self,
        transport: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await transport.send(b"data to send")

        # Assert
        mock_endpoint.sendto.assert_awaited_once_with(b"data to send", None)

    async def test____get_backend____returns_linked_instance(
        self,
        transport: AsyncioTransportDatagramSocketAdapter,
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert transport.backend() is asyncio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        transport: AsyncioTransportDatagramSocketAdapter,
        local_address: tuple[str, int] | bytes,
        remote_address: tuple[str, int] | bytes,
        mock_datagram_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert transport.extra(SocketAttribute.socket) is mock_datagram_socket
        assert transport.extra(SocketAttribute.family) == mock_datagram_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        assert transport.extra(SocketAttribute.peername) == remote_address


@pytest.mark.asyncio
class TestDatagramListenerSocketAdapter(BaseTestAsyncioDatagramTransport):
    @pytest.fixture
    @staticmethod
    def mock_endpoint() -> Any:  # type: ignore[override]
        raise ValueError("Do not use this fixture here")

    @pytest.fixture
    @classmethod
    def remote_address(cls) -> None:  # type: ignore[override]
        return None

    @pytest.fixture
    @staticmethod
    def mock_asyncio_protocol(mocker: MockerFixture, event_loop: asyncio.AbstractEventLoop) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=DatagramListenerProtocol)
        # Currently, _get_close_waiter() is a synchronous function returning a Future, but it will be awaited so this works
        mock._get_close_waiter = mocker.AsyncMock()
        mock._get_loop.return_value = event_loop
        return mock

    @pytest_asyncio.fixture
    @staticmethod
    async def transport(
        asyncio_backend: AsyncIOBackend,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> AsyncIterator[DatagramListenerSocketAdapter]:
        listener = DatagramListenerSocketAdapter(asyncio_backend, mock_asyncio_transport, mock_asyncio_protocol)
        try:
            async with listener:
                yield listener
        finally:
            mock_asyncio_transport.is_closing.side_effect = None
            mock_asyncio_transport.is_closing.return_value = True

    async def test____dunder_del____ResourceWarning(
        self,
        asyncio_backend: AsyncIOBackend,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        listener = DatagramListenerSocketAdapter(asyncio_backend, mock_asyncio_transport, mock_asyncio_protocol)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del listener

        mock_asyncio_transport.close.assert_called()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____close_transport_and_wait(
        self,
        transport_is_closing: bool,
        transport: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing

        # Act
        await transport.aclose()

        # Assert
        if transport_is_closing:
            mock_asyncio_transport.close.assert_not_called()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        else:
            mock_asyncio_transport.close.assert_called_once_with()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        mock_asyncio_transport.abort.assert_not_called()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____abort_transport_if_cancelled(
        self,
        transport_is_closing: bool,
        transport: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing
        mock_asyncio_protocol._get_close_waiter.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await transport.aclose()
        mock_asyncio_protocol._get_close_waiter.side_effect = None

        # Assert
        if transport_is_closing:
            mock_asyncio_transport.close.assert_not_called()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        else:
            mock_asyncio_transport.close.assert_called_once_with()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        mock_asyncio_transport.abort.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    async def test____is_closing____return_internal_flag(
        self,
        transport_closed: bool,
        transport: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        if transport_closed:
            await transport.aclose()
            mock_asyncio_transport.reset_mock()

        # Act
        state = transport.is_closing()

        # Assert
        mock_asyncio_transport.is_closing.assert_not_called()
        assert state is transport_closed

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____task_group(
        self,
        external_group: bool,
        transport: DatagramListenerSocketAdapter,
        mock_asyncio_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        datagram_received_cb = mocker.async_stub()
        mock_asyncio_protocol.serve.side_effect = asyncio.CancelledError

        # Act
        task_group: AsyncIOTaskGroup | None
        async with AsyncIOTaskGroup() if external_group else contextlib.nullcontext() as task_group:
            with pytest.raises(asyncio.CancelledError):
                await transport.serve(datagram_received_cb, task_group)

        # Assert
        if external_group:
            mock_asyncio_protocol.serve.assert_awaited_once_with(datagram_received_cb, task_group)
        else:
            mock_asyncio_protocol.serve.assert_awaited_once_with(datagram_received_cb, mocker.ANY)

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____send_to____write_and_drain(
        self,
        transport_is_closing: bool,
        transport: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        address: tuple[str, int] = ("127.0.0.1", 12345)
        mock_asyncio_transport.is_closing.side_effect = [transport_is_closing]

        # Act
        await transport.send_to(b"data to send", address)

        # Assert
        mock_asyncio_transport.sendto.assert_called_once_with(b"data to send", address)
        mock_asyncio_protocol.writer_drain.assert_awaited_once_with()

    async def test____get_backend____returns_linked_instance(
        self,
        transport: DatagramListenerSocketAdapter,
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert transport.backend() is asyncio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        transport: DatagramListenerSocketAdapter,
        local_address: tuple[str, int] | bytes,
        mock_datagram_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        assert transport.extra(SocketAttribute.socket) is mock_datagram_socket
        assert transport.extra(SocketAttribute.family) == mock_datagram_socket.family
        assert transport.extra(SocketAttribute.sockname) == local_address
        assert transport.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value


class TestDatagramListenerProtocol:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.DatagramTransport)
        mock.is_closing.return_value = False

        # Tell connection_made() not to try to monkeypatch this mock object
        del mock._address

        return mock

    @pytest.fixture
    @staticmethod
    def protocol(
        event_loop: asyncio.AbstractEventLoop,
        mock_asyncio_transport: MagicMock,
    ) -> DatagramListenerProtocol:
        protocol = DatagramListenerProtocol(loop=event_loop)
        protocol.connection_made(mock_asyncio_transport)
        return protocol

    @pytest.mark.asyncio
    async def test____dunder_init____use_running_loop(self) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()

        # Act
        protocol = DatagramListenerProtocol()

        # Assert
        assert protocol._get_loop() is event_loop

    def test____dunder_init____use_running_loop____not_in_asyncio_loop(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError):
            _ = DatagramListenerProtocol()

    def test____connection_lost____by_closed_transport(
        self,
        protocol: DatagramListenerProtocol,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        close_waiter = protocol._get_close_waiter()
        assert not close_waiter.done()

        # Act
        protocol.connection_lost(None)
        protocol.connection_lost(None)  # Double call must not change anything

        # Assert
        assert close_waiter.done() and close_waiter.exception() is None and close_waiter.result() is None
        mock_asyncio_transport.close.assert_not_called()  # just to be sure :)

    def test____connection_lost____by_unrelated_error(
        self,
        protocol: DatagramListenerProtocol,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        exception = OSError("Something bad happen")

        close_waiter = protocol._get_close_waiter()
        assert not close_waiter.done()

        # Act
        protocol.connection_lost(exception)
        protocol.connection_lost(exception)  # Double call must not change anything

        # Assert
        assert close_waiter.done() and close_waiter.exception() is None
        mock_asyncio_transport.close.assert_not_called()  # just to be sure :)

    @pytest.mark.asyncio
    async def test____serve____called_twice(
        self,
        asyncio_backend: AsyncIOBackend,
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        datagram_received_stub = mocker.async_stub()

        # Act & Assert
        async with asyncio_backend.create_task_group() as tg:
            with pytest.raises(RuntimeError, match=r"^DatagramListenerProtocol.serve\(\) awaited twice"):
                task = await tg.start(protocol.serve, datagram_received_stub, tg)
                try:
                    with asyncio_backend.timeout(10):
                        await protocol.serve(datagram_received_stub, tg)
                finally:
                    task.cancel()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "expected_address",
        [("an_address", 12345), "/path/to/unix.sock", b"\x00abstract_sock", b"", "", None],
        ids=repr,
    )
    async def test____serve____datagram_received____start_task(
        self,
        expected_address: Any,
        asyncio_backend: AsyncIOBackend,
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        serve_scope = asyncio_backend.move_on_after(0.5)
        datagram_received_stub = mocker.async_stub()
        datagram_received_stub.side_effect = lambda *args: serve_scope.cancel()

        # Act
        async with asyncio_backend.create_task_group() as tg:
            with serve_scope:
                event_loop.call_later(0.01, protocol.datagram_received, b"datagram", expected_address)
                await protocol.serve(datagram_received_stub, tg)

        # Assert
        datagram_received_stub.assert_awaited_once_with(b"datagram", expected_address)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ["expected_address", "expected_other_address"],
        [
            pytest.param(("an_address", 12345), ("other_address", 54321)),
            pytest.param("/path/to/unix.sock", "/path/to/other.sock"),
            pytest.param(b"\x00abstract_sock", b"\x00other_abstract_sock"),
            pytest.param(None, None),
            pytest.param(b"", b""),
            pytest.param("", ""),
        ],
        ids=repr,
    )
    async def test____serve____datagram_received____start_task_for_datagrams_received_before_serving(
        self,
        expected_address: Any | None,
        expected_other_address: Any | None,
        asyncio_backend: AsyncIOBackend,
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serve_scope = asyncio_backend.move_on_after(0.5)
        datagram_received_stub = mocker.async_stub()
        datagram_received_stub.side_effect = lambda *args: serve_scope.cancel()
        protocol.datagram_received(b"datagram", expected_address)
        protocol.datagram_received(b"datagram_2", expected_other_address)

        # Act
        async with asyncio_backend.create_task_group() as tg:
            with serve_scope:
                await protocol.serve(datagram_received_stub, tg)

        # Assert
        assert datagram_received_stub.await_args_list == [
            mocker.call(b"datagram", expected_address),
            mocker.call(b"datagram_2", expected_other_address),
        ]

    @pytest.mark.parametrize("event_loop_debug", [False, True], ids=lambda p: f"event_loop_debug=={p}")
    def test____error_received____log_error(
        self,
        event_loop_debug: bool,
        event_loop: asyncio.AbstractEventLoop,
        protocol: DatagramListenerProtocol,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        event_loop.set_debug(event_loop_debug)
        assert event_loop.get_debug() is event_loop_debug
        caplog.set_level(logging.INFO, DatagramListenerProtocol.__module__)
        exception = OSError("Something bad happen")

        # Act
        protocol.error_received(exception)

        # Assert
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].getMessage() == "Unrelated error occurred on datagram reception: OSError: Something bad happen"
        if event_loop_debug:
            assert caplog.records[0].exc_info == (type(exception), exception, exception.__traceback__)
        else:
            assert caplog.records[0].exc_info is None

    @pytest.mark.parametrize("event_loop_debug", [False, True], ids=lambda p: f"event_loop_debug=={p}")
    def test____error_received____do_not_log_after_connection_lost(
        self,
        event_loop_debug: bool,
        event_loop: asyncio.AbstractEventLoop,
        protocol: DatagramListenerProtocol,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        event_loop.set_debug(event_loop_debug)
        assert event_loop.get_debug() is event_loop_debug
        caplog.set_level(logging.INFO, DatagramListenerProtocol.__module__)
        exception = OSError("Something bad happen")
        protocol.connection_lost(None)

        # Act
        protocol.error_received(exception)

        # Assert
        assert len(caplog.records) == 0

    @pytest.mark.asyncio
    async def test____drain_helper____quick_exit_if_not_paused(
        self,
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        assert not protocol._writing_paused()
        mock_create_future: MagicMock = mocker.patch.object(event_loop, "create_future")

        # Act
        await protocol.writer_drain()

        # Assert
        mock_create_future.assert_not_called()

    @pytest.mark.asyncio
    async def test____drain_helper____raise_connection_aborted_if_connection_is_lost(
        self,
        protocol: DatagramListenerProtocol,
    ) -> None:
        # Arrange
        assert not protocol._writing_paused()

        from errno import ECONNABORTED

        protocol.connection_lost(None)

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            await protocol.writer_drain()

        assert exc_info.value.errno == ECONNABORTED

    @pytest.mark.asyncio
    async def test____drain_helper____raise_given_exception_if_connection_is_lost(
        self,
        protocol: DatagramListenerProtocol,
    ) -> None:
        # Arrange
        error = OSError("socket error")
        assert not protocol._writing_paused()

        protocol.connection_lost(error)

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            await protocol.writer_drain()

        assert exc_info.value is error

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cancel_tasks", [False, True], ids=lambda p: f"cancel_tasks_before=={p}")
    async def test____drain_helper____wait_during_writing_pause(
        self,
        cancel_tasks: bool,
        protocol: DatagramListenerProtocol,
    ) -> None:
        # Arrange
        import inspect

        # Act
        protocol.pause_writing()
        assert protocol._writing_paused()
        tasks: set[asyncio.Task[None]] = set()
        for _ in range(10):
            tasks.add(asyncio.create_task(protocol.writer_drain()))
        await asyncio.sleep(0)  # Suspend to let the event loop start all tasks
        assert all(inspect.getcoroutinestate(t.get_coro()) == "CORO_SUSPENDED" for t in tasks)  # type: ignore[arg-type]
        if cancel_tasks:
            for t in tasks:
                t.cancel()
        protocol.resume_writing()
        await asyncio.sleep(0)  # Suspend to let the event loop run all tasks

        # Assert
        if cancel_tasks:
            assert all(t.done() and t.cancelled() for t in tasks)
        else:
            assert all(t.done() and t.exception() is None and t.result() is None for t in tasks)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception", [None, OSError("Something bad happen")])
    @pytest.mark.parametrize("cancel_tasks", [False, True], ids=lambda p: f"cancel_tasks_before=={p}")
    async def test____drain_helper____wait_during_writing_pause____connection_lost_while_waiting(
        self,
        cancel_tasks: bool,
        exception: Exception | None,
        protocol: DatagramListenerProtocol,
    ) -> None:
        # Arrange
        import inspect

        protocol.pause_writing()
        assert protocol._writing_paused()
        tasks: set[asyncio.Task[None]] = set()
        for _ in range(10):
            tasks.add(asyncio.create_task(protocol.writer_drain()))
        await asyncio.sleep(0)  # Suspend to let the event loop start all tasks
        assert all(inspect.getcoroutinestate(t.get_coro()) == "CORO_SUSPENDED" for t in tasks)  # type: ignore[arg-type]
        if cancel_tasks:
            for t in tasks:
                t.cancel()

        # Act
        protocol.connection_lost(exception)
        await asyncio.sleep(0)  # Suspend to let the event loop run all tasks

        # Assert
        if cancel_tasks:
            assert all(t.done() and t.cancelled() for t in tasks)
        elif exception is None:
            assert all(t.done() and isinstance(t.exception(), ConnectionAbortedError) for t in tasks), tasks
        else:
            assert all(t.done() and t.exception() is exception for t in tasks)
