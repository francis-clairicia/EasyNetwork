from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.transports.abc import AsyncStreamTransport

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncStreamTransport:
    @pytest.fixture
    @staticmethod
    def mock_transport(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=AsyncStreamTransport)

    async def test____send_all_from_iterable____concatenates_chunks_and_call_send_all(
        self,
        mock_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_transport.send_all.return_value = None
        chunks: list[bytes | bytearray | memoryview] = [b"a", bytearray(b"b"), memoryview(b"c")]

        # Act
        await AsyncStreamTransport.send_all_from_iterable(mock_transport, chunks)

        # Assert
        mock_transport.send_all.assert_awaited_once_with(b"abc")

    async def test____send_all_from_iterable____single_yield____no_copy(
        self,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunk = mocker.sentinel.chunk
        mock_transport.send_all.return_value = None

        # Act
        await AsyncStreamTransport.send_all_from_iterable(mock_transport, iter([chunk]))

        # Assert
        mock_transport.send_all.assert_awaited_once_with(chunk)
