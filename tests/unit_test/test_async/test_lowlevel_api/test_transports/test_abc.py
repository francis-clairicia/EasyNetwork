from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.transports.abc import AsyncStreamTransport

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncStreamTransport:
    async def test____send_all_from_iterable____concatenates_chunks_and_call_send_all(
        self,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_socket_adapter.send_all.return_value = None
        chunks: list[bytes | bytearray | memoryview] = [b"a", bytearray(b"b"), memoryview(b"c")]

        # Act
        await AsyncStreamTransport.send_all_from_iterable(mock_stream_socket_adapter, chunks)

        # Assert
        assert mock_stream_socket_adapter.send_all.await_args_list == list(map(mocker.call, chunks))

    async def test____send_all_from_iterable____single_yield____no_copy(
        self,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunk = mocker.sentinel.chunk
        mock_stream_socket_adapter.send_all.return_value = None

        # Act
        await AsyncStreamTransport.send_all_from_iterable(mock_stream_socket_adapter, iter([chunk]))

        # Assert
        mock_stream_socket_adapter.send_all.assert_awaited_once_with(chunk)
