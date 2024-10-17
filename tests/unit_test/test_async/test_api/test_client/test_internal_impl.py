from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.clients._base import _AsyncTransportConnector
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncTransportConnector:
    async def test____get____cancellation_race_condition(
        self,
        asyncio_backend: AsyncBackend,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        connector = _AsyncTransportConnector(
            # The side effect is synchronous and therefore does not yield
            endpoint_factory=mocker.AsyncMock(side_effect=[mock_stream_transport]),
            scope=asyncio_backend.open_cancel_scope(),
        )

        # Act
        connector.scope.cancel()
        endpoint = await connector.get()

        # Assert
        assert endpoint is None
        mock_stream_transport.aclose.assert_awaited_once()
