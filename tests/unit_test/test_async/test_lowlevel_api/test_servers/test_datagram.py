from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, NoReturn

from easynetwork.exceptions import DatagramProtocolParseError
from easynetwork.lowlevel.api_async.backend._asyncio.tasks import TaskGroup
from easynetwork.lowlevel.api_async.servers.datagram import AsyncDatagramServer, _ClientData, _ClientState
from easynetwork.lowlevel.api_async.transports.abc import AsyncDatagramListener

import pytest
import pytest_asyncio

from ...._utils import stub_decorator
from ....base import BaseTestWithDatagramProtocol
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncDatagramServer(BaseTestWithDatagramProtocol):
    @pytest.fixture
    @staticmethod
    def mock_datagram_listener(mock_backend: MagicMock, mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=AsyncDatagramListener, backend=mock_backend)

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncIterator[AsyncDatagramServer[Any, Any, Any]]:
        server: AsyncDatagramServer[Any, Any, Any] = AsyncDatagramServer(mock_datagram_listener, mock_datagram_protocol)
        async with contextlib.aclosing(server):
            yield server

    async def test____dunder_init____invalid_transport(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_listener = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncDatagramListener object, got .*$"):
            _ = AsyncDatagramServer(mock_invalid_listener, mock_datagram_protocol)

    async def test____dunder_init____invalid_protocol(
        self,
        mock_datagram_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncDatagramServer(mock_datagram_listener, mock_invalid_protocol)

    async def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        server: AsyncDatagramServer[Any, Any, Any] = AsyncDatagramServer(mock_datagram_listener, mock_datagram_protocol)

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed server .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del server

        mock_datagram_listener.aclose.assert_not_called()

    @pytest.mark.parametrize("listener_closed", [False, True])
    async def test____is_closing____default(
        self,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        listener_closed: bool,
    ) -> None:
        # Arrange
        mock_datagram_listener.is_closing.assert_not_called()
        mock_datagram_listener.is_closing.return_value = listener_closed

        # Act
        state = server.is_closing()

        # Assert
        mock_datagram_listener.is_closing.assert_called_once_with()
        assert state is listener_closed

    async def test____aclose____default(
        self,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_listener.aclose.assert_not_called()

        # Act
        await server.aclose()

        # Assert
        mock_datagram_listener.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____task_group(
        self,
        external_group: bool,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_task_group = mocker.NonCallableMagicMock(spec=TaskGroup)
        mock_task_group.__aenter__.return_value = mock_task_group
        mock_task_group.start_soon.return_value = None
        if external_group:
            mock_backend.create_task_group.side_effect = []
        else:
            mock_backend.create_task_group.side_effect = [mock_task_group]
        datagram_received_cb = mocker.stub()
        mock_datagram_listener.serve.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            if external_group:
                await server.serve(datagram_received_cb, mock_task_group)
            else:
                await server.serve(datagram_received_cb)

        # Assert
        if external_group:
            mock_backend.create_task_group.assert_not_called()
            mock_task_group.__aenter__.assert_not_awaited()
        else:
            mock_backend.create_task_group.assert_called_once_with()
            mock_task_group.__aenter__.assert_awaited_once()

    @pytest.mark.parametrize("invalid_timeout", [-1.0, math.nan])
    @pytest.mark.parametrize("invalid_timeout_after_first_yield", [False, True], ids=lambda p: f"first_yield=={p}")
    async def test____serve____invalid_timeout(
        self,
        invalid_timeout_after_first_yield: bool,
        invalid_timeout: float,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mock_backend: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        async def serve_side_effect(handler: Callable[[bytes, Any], Awaitable[None]], task_group: TaskGroup) -> NoReturn:
            packet = b"packet"

            async def handler_coro(packet: bytes, address: Any, /) -> None:
                return await handler(packet, address)

            if invalid_timeout_after_first_yield:
                task_group.start_soon(handler_coro, packet, mocker.sentinel.address)
            await handler(packet, mocker.sentinel.address)
            raise asyncio.CancelledError("serve_side_effect")

        mock_datagram_listener.serve.side_effect = serve_side_effect
        mock_backend.create_condition_var.side_effect = asyncio.Condition

        @stub_decorator(mocker)
        async def datagram_received_cb(_: Any) -> AsyncGenerator[float | None, Any]:
            if invalid_timeout_after_first_yield:
                yield 1.0
            with pytest.raises(ValueError, match=r"^Invalid delay: .+$"):
                yield invalid_timeout

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                await server.serve(datagram_received_cb, tg)

        assert not caplog.records

    async def test____serve____unhandled_exception____from_system(
        self,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        async def serve_side_effect(handler: Callable[[bytes, Any], Awaitable[None]], task_group: Any) -> NoReturn:
            # mock_datagram_protocol does not accept non-ASCII strings.
            packet = "\u00e9".encode("latin-1")
            await handler(packet, mocker.sentinel.address)
            raise asyncio.CancelledError("serve_side_effect")

        mock_datagram_listener.serve.side_effect = serve_side_effect

        @stub_decorator(mocker)
        async def datagram_received_cb(_: Any) -> AsyncGenerator[None, Any]:
            yield

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                await server.serve(datagram_received_cb, tg)

        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], DatagramProtocolParseError)
        assert caplog.records[0].getMessage().startswith("Unhandled exception:")

    async def test____serve____unhandled_exception____from_request_handler(
        self,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        async def serve_side_effect(handler: Callable[[bytes, Any], Awaitable[None]], task_group: Any) -> NoReturn:
            packet = b"packet"
            await handler(packet, mocker.sentinel.address)
            raise asyncio.CancelledError("serve_side_effect")

        mock_datagram_listener.serve.side_effect = serve_side_effect

        @stub_decorator(mocker)
        async def datagram_received_cb(_: Any) -> AsyncGenerator[None, Any]:
            yield
            raise ValueError("something bad happened")

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                await server.serve(datagram_received_cb, tg)

        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], ValueError)
        assert caplog.records[0].getMessage() == "Unhandled exception: something bad happened"

    async def test____extra_attributes____default(
        self,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_listener.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = server.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    async def test____send_packet_to____send_bytes_to_transport(
        self,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await server.send_packet_to(mocker.sentinel.packet, mocker.sentinel.destination)

        # Assert
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_datagram_listener.send_to.assert_awaited_once_with(b"packet", mocker.sentinel.destination)

    async def test____get_backend____returns_inner_listener_backend(
        self,
        server: AsyncDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_datagram_listener.backend()


class TestClientData:
    @pytest.fixture
    @staticmethod
    def mock_backend(mock_backend: MagicMock) -> MagicMock:
        mock_backend.create_condition_var.side_effect = asyncio.Condition
        mock_backend.create_lock.side_effect = asyncio.Lock
        return mock_backend

    @pytest.fixture
    @staticmethod
    def client_data(mock_backend: MagicMock) -> _ClientData:
        return _ClientData(mock_backend)

    @staticmethod
    def get_client_state(client_data: _ClientData) -> _ClientState | None:
        return client_data.state

    def test____dunder_init____default(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_data.state is None

    def test____client_state____regular_state_transition(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        assert self.get_client_state(client_data) is None
        client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING
        client_data.mark_running()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        client_data.mark_done()
        assert self.get_client_state(client_data) is None

    def test____client_state____irregular_state_transition(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        ## Case 1: None
        assert self.get_client_state(client_data) is None
        with pytest.raises(RuntimeError):
            client_data.mark_done()
        assert self.get_client_state(client_data) is None
        with pytest.raises(RuntimeError):
            client_data.mark_running()
        assert self.get_client_state(client_data) is None

        ## Case 2: PENDING
        client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING
        with pytest.raises(RuntimeError):
            client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING
        with pytest.raises(RuntimeError):
            client_data.mark_done()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING

        ## Case 3: RUNNING
        client_data.mark_running()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        with pytest.raises(RuntimeError):
            client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        with pytest.raises(RuntimeError):
            client_data.mark_running()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING

    @pytest.mark.asyncio
    @pytest.mark.parametrize("notify", [True, False], ids=lambda p: f"notify=={p}")
    async def test____datagram_queue____push_datagram(
        self,
        notify: bool,
        client_data: _ClientData,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        queue_condition = mocker.NonCallableMagicMock(
            spec=client_data._queue_condition,
            wraps=client_data._queue_condition,
            **{
                "__aenter__.side_effect": client_data._queue_condition.__aenter__,
                "__aexit__.side_effect": client_data._queue_condition.__aexit__,
            },
        )
        client_data._queue_condition = queue_condition

        # Act
        n = await client_data.push_datagram(b"datagram_1")
        assert n == 1
        if notify:
            client_data.mark_pending()
        n = await client_data.push_datagram(b"datagram_2")
        assert n == 2
        if notify:
            client_data.mark_running()
        n = await client_data.push_datagram(b"datagram_3")
        assert n == 3

        # Assert
        assert list(client_data._datagram_queue) == [b"datagram_1", b"datagram_2", b"datagram_3"]
        if notify:
            assert queue_condition.notify.call_count == 2
        else:
            queue_condition.notify.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("no_wait", [False, True], ids=lambda p: f"no_wait=={p}")
    async def test____datagram_queue____pop_datagram(
        self,
        no_wait: bool,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data._datagram_queue = deque([b"datagram_1", b"datagram_2", b"datagram_3"])

        # Act
        if no_wait:
            assert client_data.pop_datagram_no_wait() == b"datagram_1"
            assert client_data.pop_datagram_no_wait() == b"datagram_2"
            assert client_data.pop_datagram_no_wait() == b"datagram_3"
        else:
            assert (await client_data.pop_datagram()) == b"datagram_1"
            assert (await client_data.pop_datagram()) == b"datagram_2"
            assert (await client_data.pop_datagram()) == b"datagram_3"

        # Assert
        assert len(client_data._datagram_queue) == 0

    def test____datagram_queue____pop_datagram_no_wait____empty_list(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(IndexError):
            client_data.pop_datagram_no_wait()

    @pytest.mark.asyncio
    async def test____datagram_queue____pop_datagram____wait_until_notification(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data.mark_pending()
        client_data.mark_running()
        pop_datagram_task = asyncio.create_task(client_data.pop_datagram())
        await asyncio.sleep(0.01)
        assert not pop_datagram_task.done()

        # Act
        await client_data.push_datagram(b"datagram_1")

        # Assert
        assert (await pop_datagram_task) == b"datagram_1"
