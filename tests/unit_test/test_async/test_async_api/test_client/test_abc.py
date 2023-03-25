# -*- coding: Utf-8 -*-

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, final

from easynetwork.async_api.client.abc import AbstractAsyncNetworkClient
from easynetwork.tools.socket import SocketAddress

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@final
class MockAsyncClient(AbstractAsyncNetworkClient[Any, Any]):
    def __init__(self, mocker: MockerFixture) -> None:
        super().__init__()
        self.mock_close = mocker.AsyncMock(return_value=None)
        self.mock_recv_packet = mocker.AsyncMock()

    def is_closing(self) -> bool:
        return False

    async def close(self) -> None:
        return await self.mock_close()

    def get_local_address(self) -> SocketAddress:
        raise NotImplementedError

    def get_remote_address(self) -> SocketAddress:
        raise NotImplementedError

    async def send_packet(self, packet: Any) -> None:
        raise NotImplementedError

    async def recv_packet(self) -> Any:
        return await self.mock_recv_packet()

    def fileno(self) -> int:
        raise NotImplementedError


@pytest.mark.asyncio
class TestAbstractAsyncNetworkClient:
    @pytest.fixture
    @staticmethod
    def client(mocker: MockerFixture) -> MockAsyncClient:
        return MockAsyncClient(mocker)

    async def test____context____close_client_at_end(self, client: MockAsyncClient) -> None:
        # Arrange

        # Act
        async with client:
            client.mock_close.assert_not_awaited()

        # Assert
        client.mock_close.assert_awaited_once_with()

    async def test____iter_received_packets____yields_available_packets_with_given_timeout(
        self,
        client: MockAsyncClient,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        received_packets_queue = deque([mocker.sentinel.packet_a, mocker.sentinel.packet_b, mocker.sentinel.packet_c])

        def side_effect() -> Any:
            try:
                return received_packets_queue.popleft()
            except IndexError:
                raise TimeoutError

        client.mock_recv_packet.side_effect = side_effect

        # Act
        packets = [p async for p in client.iter_received_packets()]

        # Assert
        assert client.mock_recv_packet.mock_calls == [mocker.call() for _ in range(4)]
        assert packets == [mocker.sentinel.packet_a, mocker.sentinel.packet_b, mocker.sentinel.packet_c]

    @pytest.mark.parametrize("error", [OSError])
    async def test____iter_received_packets____stop_if_an_error_occurs(
        self,
        client: MockAsyncClient,
        error: type[BaseException],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.mock_recv_packet.side_effect = [mocker.sentinel.packet_a, error]

        # Act
        packets = [p async for p in client.iter_received_packets()]

        # Assert
        assert client.mock_recv_packet.mock_calls == [mocker.call() for _ in range(2)]
        assert packets == [mocker.sentinel.packet_a]
