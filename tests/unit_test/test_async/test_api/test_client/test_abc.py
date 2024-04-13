from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, final

from easynetwork.clients.abc import AbstractAsyncNetworkClient
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.socket import SocketAddress

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
class MockAsyncClient(AbstractAsyncNetworkClient[Any, Any]):
    def __init__(self, mock_backend: MagicMock, mocker: MockerFixture) -> None:
        super().__init__()
        self.mock_wait_connected = mocker.AsyncMock(return_value=None)
        self.mock_close = mocker.AsyncMock(return_value=None)
        self.mock_recv_packet = mocker.AsyncMock()
        self.mock_backend = mock_backend

    def is_connected(self) -> bool:
        return True

    async def wait_connected(self) -> None:
        return await self.mock_wait_connected()

    def is_closing(self) -> bool:
        return False

    async def aclose(self) -> None:
        return await self.mock_close()

    def get_local_address(self) -> SocketAddress:
        raise NotImplementedError

    def get_remote_address(self) -> SocketAddress:
        raise NotImplementedError

    async def send_packet(self, packet: Any) -> None:
        raise NotImplementedError

    async def recv_packet(self) -> Any:
        return await self.mock_recv_packet()

    def backend(self) -> AsyncBackend:
        return self.mock_backend


@pytest.mark.asyncio
class TestAbstractAsyncNetworkClient:
    @pytest.fixture
    @staticmethod
    def client(mock_backend: MagicMock, mocker: MockerFixture) -> MockAsyncClient:
        return MockAsyncClient(mock_backend, mocker)

    async def test____context____close_client_at_end(self, client: MockAsyncClient) -> None:
        # Arrange

        # Act
        async with client:
            client.mock_wait_connected.assert_awaited_once_with()
            client.mock_close.assert_not_awaited()

        # Assert
        client.mock_wait_connected.assert_awaited_once_with()
        client.mock_close.assert_awaited_once_with()

    @pytest.mark.parametrize("timeout", [0, 123456.789, None])
    @pytest.mark.parametrize("error", [OSError])
    async def test____iter_received_packets____stop_if_an_error_occurs(
        self,
        timeout: float | None,
        client: MockAsyncClient,
        error: type[BaseException],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.mock_recv_packet.side_effect = [mocker.sentinel.packet_a, error]

        # Act
        packets = [p async for p in client.iter_received_packets(timeout=timeout)]

        # Assert
        assert client.mock_recv_packet.call_args_list == [mocker.call() for _ in range(2)]
        assert packets == [mocker.sentinel.packet_a]

    async def test____iter_received_packets____timeout_decrement(
        self,
        client: MockAsyncClient,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.mock_recv_packet.return_value = mocker.sentinel.packet
        async_iterator = client.iter_received_packets(timeout=10)
        now = 798546132
        mocker.patch(
            "time.perf_counter",
            side_effect=[
                now,
                now + 6,
                now + 7,
                now + 12,
                now + 12,
                now + 12,
            ],
        )

        # Act
        await anext(async_iterator)
        await anext(async_iterator)
        await anext(async_iterator)

        # Assert
        assert client.mock_recv_packet.call_args_list == [mocker.call() for _ in range(3)]
        assert mock_backend.timeout.call_args_list == [
            mocker.call(10),
            mocker.call(4),
            mocker.call(0),
        ]

    async def test____iter_received_packets____infinite_timeout(
        self,
        client: MockAsyncClient,
        mock_backend: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client.mock_recv_packet.return_value = mocker.sentinel.packet
        async_iterator = client.iter_received_packets(timeout=None)
        now = 798546132
        mocker.patch(
            "time.perf_counter",
            side_effect=[
                now,
                now + 6,
                now + 7,
                now + 12,
                now + 12,
                now + 12,
            ],
        )

        # Act
        await anext(async_iterator)
        await anext(async_iterator)
        await anext(async_iterator)

        # Assert
        assert client.mock_recv_packet.call_args_list == [mocker.call() for _ in range(3)]
        assert mock_backend.timeout.call_args_list == [
            mocker.call(math.inf),
            mocker.call(math.inf),
            mocker.call(math.inf),
        ]
