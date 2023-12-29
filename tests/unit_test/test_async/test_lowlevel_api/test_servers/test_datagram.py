from __future__ import annotations

import asyncio
import contextlib
import operator
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import BusyResourceError
from easynetwork.lowlevel.api_async.servers.datagram import AsyncDatagramServer, _ClientManager, _ClientState, _TemporaryValue
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
        self, server: AsyncDatagramServer[Any, Any, Any], mock_datagram_listener: MagicMock
    ) -> None:
        # Arrange
        mock_datagram_listener.aclose.assert_not_called()

        # Act
        await server.aclose()

        # Assert
        mock_datagram_listener.aclose.assert_awaited_once_with()

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


class TestClientManager:
    @pytest.fixture
    @staticmethod
    def mock_backend(mock_backend: MagicMock) -> MagicMock:
        mock_backend.create_condition_var.side_effect = asyncio.Condition
        return mock_backend

    @pytest.fixture
    @staticmethod
    def client_manager(mock_backend: MagicMock) -> _ClientManager[Any]:
        return _ClientManager(mock_backend)

    def test____set_client_state____regular_state_transition(
        self,
        client_manager: _ClientManager[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        address = mocker.sentinel.address

        # Act & Assert
        assert client_manager.client_state(address) is None
        with client_manager.set_client_state(address, _ClientState.TASK_RUNNING):
            assert client_manager.client_state(address) is _ClientState.TASK_RUNNING

            with client_manager.set_client_state(address, _ClientState.TASK_WAITING):
                assert client_manager.client_state(address) is _ClientState.TASK_WAITING

            assert client_manager.client_state(address) is _ClientState.TASK_RUNNING

        assert client_manager.client_state(address) is None

    @pytest.mark.parametrize(
        ["state_setup", "state"],
        [
            pytest.param([], _ClientState.TASK_RUNNING, id=_ClientState.TASK_RUNNING.name),
            pytest.param([_ClientState.TASK_RUNNING], _ClientState.TASK_WAITING, id=_ClientState.TASK_WAITING.name),
        ],
    )
    def test____set_client_state____irregular_state_transition____same_state_set_twice(
        self,
        state_setup: list[_ClientState],
        state: _ClientState,
        client_manager: _ClientManager[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        address = mocker.sentinel.address

        def set_client_state_before(state_setup_stack: contextlib.ExitStack) -> None:
            for state in state_setup:
                state_setup_stack.enter_context(client_manager.set_client_state(address, state))

        # Act & Assert
        with contextlib.ExitStack() as state_setup_stack:
            set_client_state_before(state_setup_stack)
            state_setup_stack.enter_context(client_manager.set_client_state(address, state))

            with pytest.raises(RuntimeError):
                with client_manager.set_client_state(address, state):
                    pytest.fail("Should not arrive here")

    @pytest.mark.asyncio
    async def test____lock____per_client_synchronization_condition(
        self,
        client_manager: _ClientManager[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        address = mocker.sentinel.address

        # Act & Assert
        async with client_manager.lock(address) as condition:
            assert condition.locked()
        assert not condition.locked()

        async with client_manager.lock(address) as other_condition:
            assert other_condition is not condition

    def test____datagram_queue____per_client_queue(
        self,
        client_manager: _ClientManager[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        address = mocker.sentinel.address

        # Act & Assert
        with client_manager.datagram_queue(address) as datagram_queue:
            datagram_queue.append(b"data")
            assert len(datagram_queue) == 1

        with client_manager.datagram_queue(address) as retrieved_datagram_queue:
            assert retrieved_datagram_queue is datagram_queue  # datagram_queue was not empty in the previous context
            assert retrieved_datagram_queue.popleft() == b"data"
            assert len(retrieved_datagram_queue) == 0

        with client_manager.datagram_queue(address) as other_datagram_queue:
            assert other_datagram_queue is not datagram_queue  # datagram_queue was empty and therefore deleted

    def test____datagram_queue____check_not_empty(
        self,
        client_manager: _ClientManager[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        address = mocker.sentinel.address

        # Act & Assert
        with client_manager.datagram_queue(address) as datagram_queue:
            datagram_queue.append(b"data")
            client_manager.check_datagram_queue_not_empty(datagram_queue)

            datagram_queue.clear()
            with pytest.raises(RuntimeError):
                client_manager.check_datagram_queue_not_empty(datagram_queue)

    def test____send_guard____per_client_resource_guard(
        self,
        client_manager: _ClientManager[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        with client_manager.send_guard(mocker.sentinel.address), client_manager.send_guard(mocker.sentinel.other_address):
            with pytest.raises(BusyResourceError):
                with client_manager.send_guard(mocker.sentinel.address):
                    pytest.fail("Should not arrive here")

            with pytest.raises(BusyResourceError):
                with client_manager.send_guard(mocker.sentinel.other_address):
                    pytest.fail("Should not arrive here")


class TestTemporaryValue:
    @pytest.fixture
    @staticmethod
    def value_factory(mocker: MockerFixture) -> MagicMock:
        value_factory = mocker.MagicMock(spec=lambda: None)
        value_factory.return_value = mocker.sentinel.value
        return value_factory

    def test____get____keep_key_in_context(self, value_factory: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        tmp: _TemporaryValue[Any, Any] = _TemporaryValue(value_factory)
        key = mocker.sentinel.key

        # Act & Assert
        with tmp.get(key) as value:
            value_factory.assert_called_once_with()
            assert key in tmp
            assert value is mocker.sentinel.value
        assert key not in tmp

    def test____get____nested_contexts(self, value_factory: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        tmp: _TemporaryValue[Any, Any] = _TemporaryValue(value_factory)
        key = mocker.sentinel.key

        # Act & Assert
        with tmp.get(key) as value:
            value_factory.assert_called_once_with()
            value_factory.reset_mock()
            for _ in range(3):  # Test exit and re-enter inside outer context
                with tmp.get(key) as inner_value:
                    value_factory.assert_not_called()
                    assert value is inner_value
                assert key in tmp
        assert key not in tmp

    def test____get____conditional_deletion(self, value_factory: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        value_factory.side_effect = list
        tmp: _TemporaryValue[Any, list[Any]] = _TemporaryValue(value_factory, must_delete_value=operator.not_)
        key = mocker.sentinel.key

        # Act & Assert
        with tmp.get(key) as tmp_list:
            value_factory.assert_called_once_with()
            value_factory.reset_mock()
            tmp_list.append(mocker.sentinel.element)

        assert key in tmp  # tmp_list is not empty

        with tmp.get(key) as same_tmp_list:
            assert same_tmp_list is tmp_list
            value_factory.assert_not_called()

            tmp_list.clear()

        assert key not in tmp  # tmp_list is empty
