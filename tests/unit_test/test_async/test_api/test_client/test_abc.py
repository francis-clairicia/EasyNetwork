# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, final

from easynetwork.api_async.client.abc import AbstractAsyncNetworkClient
from easynetwork.tools.socket import SocketAddress

import pytest

if TYPE_CHECKING:
    from easynetwork.api_async.backend.abc import AbstractAsyncBackend

    from pytest_mock import MockerFixture


@final
class MockAsyncClient(AbstractAsyncNetworkClient[Any, Any]):
    def __init__(self, mocker: MockerFixture) -> None:
        super().__init__()
        self.mock_wait_connected = mocker.AsyncMock(return_value=None)
        self.mock_close = mocker.AsyncMock(return_value=None)
        self.mock_recv_packet = mocker.AsyncMock()

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

    def fileno(self) -> int:
        raise NotImplementedError

    def get_backend(self) -> AbstractAsyncBackend:
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
            client.mock_wait_connected.assert_awaited_once_with()
            client.mock_close.assert_not_awaited()

        # Assert
        client.mock_wait_connected.assert_awaited_once_with()
        client.mock_close.assert_awaited_once_with()

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
