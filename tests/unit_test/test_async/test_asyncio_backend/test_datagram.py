from __future__ import annotations

import asyncio
from collections.abc import Callable
from socket import AI_PASSIVE
from typing import TYPE_CHECKING, Any, cast

from easynetwork_asyncio.datagram.endpoint import DatagramEndpoint, DatagramEndpointProtocol, create_datagram_endpoint
from easynetwork_asyncio.datagram.socket import AsyncioTransportDatagramSocketAdapter, RawDatagramSocketAdapter

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

from ...base import BaseTestSocket


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
        socket=mocker.sentinel.stdlib_socket,
    )

    # Assert
    mock_loop_create_datagram_endpoint.assert_awaited_once_with(
        mocker.ANY,  # protocol_factory
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
    def mock_asyncio_protocol(mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=DatagramEndpointProtocol)
        # Currently, _get_close_waiter() is a synchronous function returning a Future, but it will be awaited so this works
        mock._get_close_waiter = mocker.AsyncMock()
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

    async def test____transport____property(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert endpoint.transport is mock_asyncio_transport

    async def test____close____close_transport(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange

        # Act
        endpoint.close()

        # Assert
        mock_asyncio_transport.close.assert_called_once_with()
        mock_asyncio_transport.abort.assert_not_called()

    async def test____wait_closed___wait_for_protocol_to_close_connection(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await endpoint.wait_closed()

        # Assert
        mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()

    async def test____aclose____close_transport_and_wait(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await endpoint.aclose()

        # Assert
        mock_asyncio_transport.close.assert_called_once_with()
        mock_asyncio_transport.abort.assert_not_called()
        mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()

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
        assert data == b"some data"
        assert address == ("an_address", 12345)

    async def test____recvfrom____connection_lost____transport_already_closed(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        from errno import ECONNABORTED

        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty
        mock_asyncio_transport.is_closing.return_value = True

        # Act
        with pytest.raises(OSError) as exc_info:
            await endpoint.recvfrom()

        # Assert
        assert exc_info.value.errno == ECONNABORTED
        mock_asyncio_exception_queue.get_nowait.assert_called_once()
        mock_asyncio_recv_queue.get.assert_not_awaited()

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
        assert len(mock_asyncio_exception_queue.get_nowait.mock_calls) == 2
        mock_asyncio_recv_queue.get.assert_awaited_once_with()

    async def test____recvfrom____raise_exception____protocol_already_sent_exception_in_queue(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_exception_queue.get_nowait.return_value = CustomException()

        # Act
        with pytest.raises(CustomException):
            await endpoint.recvfrom()

        # Assert
        mock_asyncio_exception_queue.get_nowait.assert_called_once_with()
        mock_asyncio_recv_queue.get.assert_not_awaited()

    async def test____recvfrom____raise_exception____transport_closed_by_protocol_with_exception_while_waiting(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_recv_queue: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        from itertools import count

        mock_asyncio_recv_queue.get.return_value = None  # None is sent to queue when readers must wake up

        _count = count()

        # Cannot use list for side_effect because returned value is an exception instance...
        def get_nowait_side_effect() -> Exception:
            if next(_count) == 0:
                raise asyncio.QueueEmpty
            return CustomException()

        mock_asyncio_exception_queue.get_nowait.side_effect = get_nowait_side_effect

        mock_asyncio_transport.is_closing.side_effect = [False, True]  # 1st call OK, 2nd not so much

        # Act
        with pytest.raises(CustomException):
            await endpoint.recvfrom()

        # Assert
        assert len(mock_asyncio_exception_queue.get_nowait.mock_calls) == 2
        mock_asyncio_recv_queue.get.assert_awaited_once_with()

    @pytest.mark.parametrize("address", [("127.0.0.1", 12345), None], ids=repr)
    async def test____sendto____send_and_await_drain(
        self,
        endpoint: DatagramEndpoint,
        address: tuple[str, int] | None,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty

        # Act
        await endpoint.sendto(b"some data", address)

        # Assert
        mock_asyncio_exception_queue.get_nowait.assert_called_once_with()
        mock_asyncio_transport.sendto.assert_called_once_with(b"some data", address)
        mock_asyncio_protocol._drain_helper.assert_awaited_once_with()

    @pytest.mark.parametrize("address", [("127.0.0.1", 12345), None], ids=repr)
    async def test____sendto____transport_already_closed(
        self,
        endpoint: DatagramEndpoint,
        address: tuple[str, int] | None,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
        mock_asyncio_exception_queue: MagicMock,
    ) -> None:
        # Arrange
        from errno import ECONNABORTED

        mock_asyncio_transport.is_closing.return_value = True
        mock_asyncio_exception_queue.get_nowait.side_effect = asyncio.QueueEmpty

        # Act
        with pytest.raises(OSError) as exc_info:
            await endpoint.sendto(b"some data", address)

        # Assert
        assert exc_info.value.errno == ECONNABORTED
        mock_asyncio_exception_queue.get_nowait.assert_called_once()
        mock_asyncio_transport.sendto.assert_not_called()
        mock_asyncio_protocol._drain_helper.assert_not_awaited()

    async def test____get_extra_info____get_transport_extra_info(
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

    async def test____get_loop____get_protocol_bound_loop(
        self,
        endpoint: DatagramEndpoint,
        mock_asyncio_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_protocol._get_loop.return_value = mocker.sentinel.event_loop

        # Act
        loop = endpoint.get_loop()

        # Assert
        mock_asyncio_protocol._get_loop.assert_called_once_with()
        assert loop is mocker.sentinel.event_loop


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
        mock_asyncio_transport.close.assert_called_once_with()  # just to be sure :)

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
        assert close_waiter.done() and close_waiter.exception() is exception
        mock_asyncio_recv_queue.put_nowait.assert_called_once_with(None)
        mock_asyncio_exception_queue.put_nowait.assert_called_once_with(exception)
        mock_asyncio_transport.close.assert_called_once_with()  # just to be sure :)

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

    def test____datagram_received____do_not_push_to_queue_ater_connection_lost(
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

    def test____error_received____do_not_push_to_queue_ater_connection_lost(
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
class TestAsyncioTransportDatagramSocketAdapter:
    @pytest.fixture
    @staticmethod
    def mock_udp_socket(mock_udp_socket: MagicMock) -> MagicMock:
        mock_udp_socket.getsockname.return_value = ("127.0.0.1", 11111)
        return mock_udp_socket

    @pytest.fixture
    @staticmethod
    def endpoint_extra_info() -> dict[str, Any]:
        return {}

    @pytest.fixture
    @staticmethod
    def mock_endpoint(
        endpoint_extra_info: dict[str, Any],
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        endpoint_extra_info.update(
            {
                "socket": mock_udp_socket,
                "sockname": mock_udp_socket.getsockname.return_value,
                "peername": None,
            }
        )
        mock = mock_datagram_endpoint_factory()
        mock.get_extra_info.side_effect = endpoint_extra_info.get
        return mock

    @pytest.fixture
    @staticmethod
    def socket(mock_endpoint: MagicMock) -> AsyncioTransportDatagramSocketAdapter:
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
        mock_endpoint.close.assert_called_once_with()
        mock_endpoint.wait_closed.assert_awaited_once_with()
        mock_endpoint.transport.abort.assert_not_called()

    async def test____aclose____abort_transport_if_cancelled(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_endpoint.wait_closed.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await socket.aclose()

        # Assert
        mock_endpoint.close.assert_called_once_with()
        mock_endpoint.wait_closed.assert_awaited_once_with()
        mock_endpoint.transport.abort.assert_called_once_with()

    async def test____context____close_transport_and_wait_at_end(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        async with socket:
            mock_endpoint.close.assert_not_called()

        # Assert
        mock_endpoint.close.assert_called_once_with()
        mock_endpoint.wait_closed.assert_awaited_once_with()

    async def test____is_closing____return_endpoint_state(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_endpoint.is_closing.return_value = mocker.sentinel.is_closing

        # Act
        state = socket.is_closing()

        # Assert
        mock_endpoint.is_closing.assert_called_once_with()
        assert state is mocker.sentinel.is_closing

    async def test____recvfrom____read_from_reader(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        received_data = b"data"
        mock_endpoint.recvfrom.return_value = (received_data, ("an_address", 12345))

        # Act
        data, address = await socket.recvfrom(65536)

        # Assert
        mock_endpoint.recvfrom.assert_awaited_once_with()
        assert data is received_data  # Should not be copied
        assert address == ("an_address", 12345)

    async def test____recvfrom____read_from_reader____exact_size(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        received_data = b"data"
        mock_endpoint.recvfrom.return_value = (received_data, ("an_address", 12345))

        # Act
        data, address = await socket.recvfrom(len(received_data))

        # Assert
        mock_endpoint.recvfrom.assert_awaited_once_with()
        assert data is received_data  # Should not be copied
        assert address == ("an_address", 12345)

    async def test____recvfrom____read_from_reader____too_big_datagram(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange
        mock_endpoint.recvfrom.return_value = (b"data", ("an_address", 12345))

        # Act
        data, address = await socket.recvfrom(2)

        # Assert
        mock_endpoint.recvfrom.assert_awaited_once_with()
        assert data == b"da"
        assert address == ("an_address", 12345)

    @pytest.mark.parametrize("address", [("127.0.0.1", 12345), None], ids=repr)
    async def test____sendto____write_and_drain(
        self,
        address: tuple[str, int] | None,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_endpoint: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.sendto(b"data to send", address)

        # Assert
        mock_endpoint.sendto.assert_awaited_once_with(b"data to send", address)

    async def test____socket____returns_transport_socket(
        self,
        socket: AsyncioTransportDatagramSocketAdapter,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        transport_socket = socket.socket()

        # Assert
        assert transport_socket is mock_udp_socket


@pytest.mark.asyncio
class TestRawDatagramSocketAdapter(BaseTestSocket):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_async_socket_cls(mock_async_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(f"{RawDatagramSocketAdapter.__module__}.AsyncSocket", return_value=mock_async_socket)

    @pytest.fixture
    @classmethod
    def mock_udp_socket(cls, mock_udp_socket: MagicMock) -> MagicMock:
        cls.set_local_address_to_socket_mock(mock_udp_socket, mock_udp_socket.family, ("127.0.0.1", 11111))
        cls.set_remote_address_to_socket_mock(mock_udp_socket, mock_udp_socket.family, ("127.0.0.1", 12345))
        return mock_udp_socket

    @pytest.fixture
    @staticmethod
    def mock_async_socket(
        mock_async_socket: MagicMock,
        mock_udp_socket: MagicMock,
    ) -> MagicMock:
        mock_async_socket.socket = mock_udp_socket
        return mock_async_socket

    @pytest.fixture
    @staticmethod
    def socket(event_loop: asyncio.AbstractEventLoop, mock_udp_socket: MagicMock) -> RawDatagramSocketAdapter:
        return RawDatagramSocketAdapter(mock_udp_socket, event_loop)

    async def test____dunder_init____default(
        self,
        socket: RawDatagramSocketAdapter,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act

        # Assert
        assert socket.socket() is mock_udp_socket

    async def test____dunder_init____invalid_socket_type(
        self,
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
            _ = RawDatagramSocketAdapter(mock_tcp_socket, event_loop)

    async def test____is_closing____default(
        self,
        socket: RawDatagramSocketAdapter,
        mock_async_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_async_socket.is_closing.return_value = mocker.sentinel.is_closing

        # Act
        state = socket.is_closing()

        # Assert
        assert state is mocker.sentinel.is_closing
        mock_async_socket.is_closing.assert_called_once_with()

    async def test____aclose____close_socket(
        self,
        socket: RawDatagramSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.aclose()

        # Assert
        mock_async_socket.aclose.assert_awaited_once_with()

    async def test____context____close_socket(
        self,
        socket: RawDatagramSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        async with socket:
            mock_async_socket.aclose.assert_not_awaited()

        # Assert
        mock_async_socket.aclose.assert_awaited_once_with()

    async def test_____recvfrom____returns_data_from_async_socket(
        self,
        socket: RawDatagramSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.recvfrom.return_value = (b"data", ("127.0.0.1", 12345))

        # Act
        data, address = await socket.recvfrom(123456789)

        # Assert
        assert data == b"data"
        assert address == ("127.0.0.1", 12345)
        mock_async_socket.recvfrom.assert_awaited_once_with(123456789)

    @pytest.mark.parametrize("address", [("127.0.0.1", 12345), None])
    async def test_____sendto____sends_data_to_async_socket(
        self,
        address: tuple[str, int] | None,
        socket: RawDatagramSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.sendto.return_value = None

        # Act
        await socket.sendto(b"data", address)

        # Assert
        if address is None:
            mock_async_socket.sendall.assert_awaited_once_with(b"data")
            mock_async_socket.sendto.assert_not_called()
        else:
            mock_async_socket.sendall.assert_not_called()
            mock_async_socket.sendto.assert_awaited_once_with(b"data", address)
