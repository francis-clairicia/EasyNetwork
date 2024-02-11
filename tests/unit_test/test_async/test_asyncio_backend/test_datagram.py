from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from errno import ECONNABORTED
from socket import AI_PASSIVE
from typing import TYPE_CHECKING, Any, Literal, cast

from easynetwork.lowlevel.api_async.backend.abc import TaskGroup
from easynetwork.lowlevel.api_async.backend.factory import current_async_backend
from easynetwork.lowlevel.socket import SocketAttribute
from easynetwork.lowlevel.std_asyncio.datagram.endpoint import (
    DatagramEndpoint,
    DatagramEndpointProtocol,
    create_datagram_endpoint,
)
from easynetwork.lowlevel.std_asyncio.datagram.listener import DatagramListenerProtocol, DatagramListenerSocketAdapter
from easynetwork.lowlevel.std_asyncio.datagram.socket import AsyncioTransportDatagramSocketAdapter

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

from ..._utils import partial_eq
from ...base import BaseTestSocket


class CustomException(Exception):
    """Helper to test exception_queue usage"""


@pytest.mark.asyncio
@pytest.mark.parametrize("local_address", ["local_address", None], ids=lambda p: f"local_address=={p}")
@pytest.mark.parametrize("remote_address", ["remote_address", None], ids=lambda p: f"remote_address=={p}")
@pytest.mark.parametrize("reuse_port", [False, True], ids=lambda p: f"reuse_port=={p}")
async def test____create_datagram_endpoint____return_DatagramEndpoint_instance(
    event_loop: asyncio.AbstractEventLoop,
    local_address: Any | None,
    remote_address: Any | None,
    reuse_port: bool,
    mocker: MockerFixture,
) -> None:
    # Arrange
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
            asyncio.get_running_loop(),
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
        mock.is_closing.return_value = False
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
    ) -> DatagramEndpoint:
        return DatagramEndpoint(
            mock_asyncio_transport,
            mock_asyncio_protocol,
            recv_queue=mock_asyncio_recv_queue,
            exception_queue=mock_asyncio_exception_queue,
        )

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

    async def test____recvfrom____await_recv_queue(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_recv_queue.get.return_value = (b"some data", ("an_address", 12345))
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty

        # Act
        data, address = await endpoint.recvfrom()

        # Assert
        mock_asyncio_recv_queue.get.assert_awaited_once_with()
        mock_asyncio_recv_queue.get_nowait.assert_not_called()
        assert data == b"some data"
        assert address == ("an_address", 12345)

    async def test____recvfrom____connection_lost____transport_already_closed____data_in_queue(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty
        mock_asyncio_transport.is_closing.return_value = True
        mock_asyncio_recv_queue.get_nowait.return_value = (b"some data", ("an_address", 12345))

        # Act
        data, address = await endpoint.recvfrom()

        # Assert
        mock_asyncio_exception_queue.get_nowait.assert_not_called()
        mock_asyncio_recv_queue.get.assert_not_awaited()
        mock_asyncio_recv_queue.get_nowait.assert_called_once()
        assert data == b"some data"
        assert address == ("an_address", 12345)

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

    @pytest.mark.parametrize("address", [("127.0.0.1", 12345), None], ids=repr)
    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____sendto____send_and_await_drain(
        self,
        transport_is_closing: bool,
        endpoint: DatagramEndpoint,
        address: tuple[str, int] | None,
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
        event_loop: asyncio.AbstractEventLoop,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange

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

    def test____datagram_received____push_to_queue(
        self,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_recv_queue: MagicMock,
    ) -> None:
        # Arrange

        # Act
        protocol.datagram_received(b"datagram", ("an_address", 12345))

        # Assert
        mock_asyncio_recv_queue.put_nowait.assert_called_once_with((b"datagram", ("an_address", 12345)))

    def test____datagram_received____do_not_push_to_queue_after_connection_lost(
        self,
        protocol: DatagramEndpointProtocol,
        mock_asyncio_recv_queue: MagicMock,
    ) -> None:
        # Arrange
        protocol.connection_lost(None)
        mock_asyncio_recv_queue.put_nowait.reset_mock()  # Needed to use assert_not_called()

        # Act
        protocol.datagram_received(b"datagram", ("an_address", 12345))

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
        event_loop: asyncio.AbstractEventLoop,
        protocol: DatagramEndpointProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
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
            assert all(t.done() and t.exception() is None and t.result() is None for t in tasks), tasks
        else:
            assert all(t.done() and t.exception() is exception for t in tasks)


@pytest.mark.asyncio
class BaseTestAsyncioDatagramTransport(BaseTestSocket):
    @pytest.fixture
    @classmethod
    def mock_udp_socket(cls, mock_udp_socket: MagicMock, remote_address: tuple[Any, ...] | None) -> MagicMock:
        cls.set_local_address_to_socket_mock(mock_udp_socket, mock_udp_socket.family, ("127.0.0.1", 11111))
        if remote_address is None:
            cls.configure_socket_mock_to_raise_ENOTCONN(mock_udp_socket)
        else:
            cls.set_remote_address_to_socket_mock(mock_udp_socket, mock_udp_socket.family, remote_address)
        return mock_udp_socket

    @pytest.fixture
    @staticmethod
    def asyncio_transport_extra_info(mock_udp_socket: MagicMock, remote_address: tuple[Any, ...] | None) -> dict[str, Any]:
        return {
            "socket": mock_udp_socket,
            "sockname": mock_udp_socket.getsockname.return_value,
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
    @pytest.fixture
    @classmethod
    def remote_address(cls) -> tuple[Any, ...] | None:
        return ("127.0.0.1", 12345)

    @pytest.fixture
    @classmethod
    def socket(cls, mock_endpoint: MagicMock) -> AsyncioTransportDatagramSocketAdapter:
        return AsyncioTransportDatagramSocketAdapter(mock_endpoint)

    async def test____aclose____close_transport_and_wait(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.aclose()

        # Assert
        mock_endpoint.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    async def test____is_closing____return_internal_flag(
        self,
        transport_closed: bool,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        if transport_closed:
            await socket.aclose()
            mock_endpoint.reset_mock()
        mock_endpoint.is_closing.side_effect = AssertionError

        # Act
        state = socket.is_closing()

        # Assert
        mock_endpoint.is_closing.assert_not_called()
        assert state is transport_closed

    async def test____recv____read_from_reader(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        received_data = b"data"
        mock_endpoint.recvfrom.return_value = (received_data, ("127.0.0.1", 12345))

        # Act
        data = await socket.recv()

        # Assert
        mock_endpoint.recvfrom.assert_awaited_once_with()
        assert data is received_data  # Should not be copied

    async def test____send____write_and_drain(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.send(b"data to send")

        # Assert
        mock_endpoint.sendto.assert_awaited_once_with(b"data to send", None)

    async def test____extra_attributes____returns_socket_info(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert socket.extra(SocketAttribute.socket) is mock_udp_socket
        assert socket.extra(SocketAttribute.family) == mock_udp_socket.family
        assert socket.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert socket.extra(SocketAttribute.peername) == ("127.0.0.1", 12345)


@pytest.mark.asyncio
class TestDatagramListenerSocketAdapter(BaseTestAsyncioDatagramTransport):
    @pytest.fixture
    @staticmethod
    def mock_endpoint() -> Any:  # type: ignore[override]
        raise ValueError("Do not use this fixture here")

    @pytest.fixture
    @classmethod
    def remote_address(cls) -> tuple[Any, ...] | None:
        return None

    @pytest.fixture
    @staticmethod
    def mock_asyncio_protocol(mocker: MockerFixture, event_loop: asyncio.AbstractEventLoop) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=DatagramListenerProtocol)
        # Currently, _get_close_waiter() is a synchronous function returning a Future, but it will be awaited so this works
        mock._get_close_waiter = mocker.AsyncMock()
        mock._get_loop.return_value = event_loop
        return mock

    @pytest.fixture
    @staticmethod
    def socket(
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> DatagramListenerSocketAdapter:
        return DatagramListenerSocketAdapter(mock_asyncio_transport, mock_asyncio_protocol)

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____close_transport_and_wait(
        self,
        transport_is_closing: bool,
        socket: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing

        # Act
        await socket.aclose()

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
        socket: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing
        mock_asyncio_protocol._get_close_waiter.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await socket.aclose()

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
        socket: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        if transport_closed:
            await socket.aclose()
            mock_asyncio_transport.reset_mock()
        mock_asyncio_transport.is_closing.side_effect = AssertionError

        # Act
        state = socket.is_closing()

        # Assert
        mock_asyncio_transport.is_closing.assert_not_called()
        assert state is transport_closed

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____task_group(
        self,
        external_group: bool,
        socket: DatagramListenerSocketAdapter,
        mock_asyncio_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_task_group = mocker.NonCallableMagicMock(spec=TaskGroup)
        mock_task_group.__aenter__.return_value = mock_task_group
        mock_task_group.start_soon.return_value = None
        mock_AsyncIOTaskGroup = mocker.patch(
            f"{DatagramListenerSocketAdapter.__module__}.AsyncIOTaskGroup",
            side_effect=[mock_task_group],
        )
        datagram_received_cb = mocker.async_stub()
        mock_asyncio_protocol.serve.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            if external_group:
                await socket.serve(datagram_received_cb, mock_task_group)
            else:
                await socket.serve(datagram_received_cb)

        # Assert
        if external_group:
            mock_AsyncIOTaskGroup.assert_not_called()
            mock_task_group.__aenter__.assert_not_awaited()
        else:
            mock_AsyncIOTaskGroup.assert_called_once_with()
            mock_task_group.__aenter__.assert_awaited_once()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____send_to____write_and_drain(
        self,
        transport_is_closing: bool,
        socket: DatagramListenerSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        address: tuple[str, int] = ("127.0.0.1", 12345)
        mock_asyncio_transport.is_closing.side_effect = [transport_is_closing]

        # Act
        await socket.send_to(b"data to send", address)

        # Assert
        mock_asyncio_transport.sendto.assert_called_once_with(b"data to send", address)
        mock_asyncio_protocol.writer_drain.assert_awaited_once_with()

    async def test____extra_attributes____returns_socket_info(
        self,
        socket: DatagramListenerSocketAdapter,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        assert socket.extra(SocketAttribute.socket) is mock_udp_socket
        assert socket.extra(SocketAttribute.family) == mock_udp_socket.family
        assert socket.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert socket.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value


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
    async def test____dunder_init____use_running_loop(
        self,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        # Arrange

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
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        backend = current_async_backend()
        datagram_received_stub = mocker.async_stub()

        # Act & Assert
        async with backend.create_task_group() as tg:
            with pytest.raises(RuntimeError, match=r"^DatagramListenerProtocol.serve\(\) awaited twice"):
                task = await tg.start(protocol.serve, datagram_received_stub, tg)
                try:
                    with backend.timeout(10):
                        await protocol.serve(datagram_received_stub, tg)
                finally:
                    task.cancel()

    @pytest.mark.asyncio
    async def test____serve____datagram_received____start_task(
        self,
        event_loop: asyncio.AbstractEventLoop,
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        backend = current_async_backend()
        serve_scope = backend.move_on_after(10)
        datagram_received_stub = mocker.async_stub()
        datagram_received_stub.side_effect = lambda *args: serve_scope.cancel()

        # Act
        async with backend.create_task_group() as tg:
            with serve_scope:
                event_loop.call_later(0.1, protocol.datagram_received, b"datagram", ("an_address", 12345))
                await protocol.serve(datagram_received_stub, tg)

        # Assert
        datagram_received_stub.assert_awaited_once_with(b"datagram", ("an_address", 12345))

    @pytest.mark.asyncio
    async def test____serve____datagram_received____start_task_for_datagrams_received_before_serving(
        self,
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        backend = current_async_backend()
        serve_scope = backend.move_on_after(10)
        datagram_received_stub = mocker.async_stub()
        datagram_received_stub.side_effect = lambda *args: serve_scope.cancel()
        protocol.datagram_received(b"datagram", ("an_address", 12345))
        protocol.datagram_received(b"datagram_2", ("other_address", 54321))

        # Act
        async with backend.create_task_group() as tg:
            with serve_scope:
                await protocol.serve(datagram_received_stub, tg)

        # Assert
        assert datagram_received_stub.await_args_list == [
            mocker.call(b"datagram", ("an_address", 12345)),
            mocker.call(b"datagram_2", ("other_address", 54321)),
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
        event_loop: asyncio.AbstractEventLoop,
        protocol: DatagramListenerProtocol,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
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
            assert all(t.done() and t.exception() is None and t.result() is None for t in tasks), tasks
        else:
            assert all(t.done() and t.exception() is exception for t in tasks)
