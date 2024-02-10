from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend.abc import TaskGroup
from easynetwork.lowlevel.api_async.servers.datagram import AsyncDatagramServer, _ClientData, _ClientState
from easynetwork.lowlevel.api_async.transports.abc import AsyncDatagramListener

import pytest
import pytest_asyncio

from .....tools import temporary_backend

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncDatagramServer:
    @pytest.fixture
    @staticmethod
    def mock_datagram_listener(mocker: MockerFixture) -> MagicMock:
        mock_datagram_listener = mocker.NonCallableMagicMock(spec=AsyncDatagramListener)
        mock_datagram_listener.is_closing.return_value = False

        def close_side_effect() -> None:
            mock_datagram_listener.is_closing.return_value = True

        mock_datagram_listener.aclose.side_effect = close_side_effect
        return mock_datagram_listener

    @pytest.fixture
    @staticmethod
    def mock_datagram_protocol(mock_datagram_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        def make_datagram_side_effect(packet: Any) -> bytes:
            return str(packet).encode("ascii").removeprefix(b"sentinel.")

        # def build_packet_from_datagram_side_effect(data: bytes) -> Any:
        #     return getattr(mocker.sentinel, data.decode("ascii"))

        mock_datagram_protocol.make_datagram.side_effect = make_datagram_side_effect
        # mock_datagram_protocol.build_packet_from_datagram.side_effect = build_packet_from_datagram_side_effect
        return mock_datagram_protocol

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_backend: MagicMock,
    ) -> AsyncIterator[AsyncDatagramServer[Any, Any, Any]]:
        with temporary_backend(mock_backend):
            yield AsyncDatagramServer(mock_datagram_listener, mock_datagram_protocol)

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
        datagram_received_cb = mocker.async_stub()
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

    async def test____get_extra_info____default(
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

    @staticmethod
    def get_client_queue(client_data: _ClientData) -> deque[bytes] | None:
        return client_data._datagram_queue

    def test____dunder_init____default(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        assert isinstance(client_data.task_lock, asyncio.Lock)
        assert client_data.state is None
        assert client_data._datagram_queue is None
        assert client_data._queue_condition is None

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
    async def test____datagram_queue____push_datagram(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        assert self.get_client_queue(client_data) is None

        # Act
        await client_data.push_datagram(b"datagram_1")
        await client_data.push_datagram(b"datagram_2")
        await client_data.push_datagram(b"datagram_3")

        # Assert
        assert client_data._datagram_queue is not None
        assert client_data._queue_condition is None
        assert list(client_data._datagram_queue) == [b"datagram_1", b"datagram_2", b"datagram_3"]

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
        if no_wait:
            assert client_data._queue_condition is None
        else:
            assert client_data._queue_condition is not None

    @pytest.mark.parametrize("queue", [deque(), None], ids=lambda p: f"queue=={p!r}")
    def test____datagram_queue____pop_datagram_no_wait____empty_list(
        self,
        queue: deque[bytes] | None,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data._datagram_queue = queue

        # Act & Assert
        with pytest.raises(IndexError):
            client_data.pop_datagram_no_wait()

    @pytest.mark.asyncio
    async def test____datagram_queue____pop_datagram____wait_until_notification(
        self,
        event_loop: asyncio.AbstractEventLoop,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        pop_datagram_task = event_loop.create_task(client_data.pop_datagram())
        await asyncio.sleep(0.01)
        assert not pop_datagram_task.done()

        # Act
        await client_data.push_datagram(b"datagram_1")

        # Assert
        assert (await pop_datagram_task) == b"datagram_1"
