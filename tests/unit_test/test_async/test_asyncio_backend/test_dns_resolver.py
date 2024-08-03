from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._asyncio.dns_resolver import AsyncIODNSResolver

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_sock_connect(event_loop: asyncio.AbstractEventLoop, mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(event_loop, "sock_connect", new_callable=mocker.AsyncMock, return_value=None)


@pytest.mark.asyncio
async def test____AsyncIODNSResolver____connect_socket(mock_tcp_socket: MagicMock, mock_sock_connect: AsyncMock) -> None:
    # Arrange
    dns_resolver = AsyncIODNSResolver()

    # Act
    await dns_resolver.connect_socket(mock_tcp_socket, ("127.0.0.1", 12345))

    # Assert
    mock_sock_connect.assert_awaited_once_with(mock_tcp_socket, ("127.0.0.1", 12345))
