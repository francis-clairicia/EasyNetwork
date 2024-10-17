from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.transports.abc import AsyncStreamTransport

import pytest

from ...._utils import make_async_recv_into_side_effect as make_recv_into_side_effect

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncStreamTransport:
    async def test____recv____default(
        self,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect(b"value")

        # Act
        data = await AsyncStreamTransport.recv(mock_stream_transport, 128)

        # Assert
        assert type(data) is bytes
        assert data == b"value"
        mock_stream_transport.recv_into.assert_awaited_once_with(mocker.ANY)

    async def test____recv____null_bufsize(
        self,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect(b"never")

        # Act & Assert
        data = await AsyncStreamTransport.recv(mock_stream_transport, 0)

        # Assert
        assert type(data) is bytes
        assert len(data) == 0
        mock_stream_transport.recv_into.assert_not_called()

    async def test____recv____invalid_bufsize_value(
        self,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect(b"never")

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'bufsize' must be a positive or null integer$"):
            await AsyncStreamTransport.recv(mock_stream_transport, -1)

        # Assert
        mock_stream_transport.recv_into.assert_not_called()

    async def test____recv____invalid_recv_into_return_value(
        self,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = [-1]

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^transport\.recv_into\(\) returned a negative value$"):
            await AsyncStreamTransport.recv(mock_stream_transport, 128)

        # Assert
        mock_stream_transport.recv_into.assert_awaited_once_with(mocker.ANY)

    async def test____send_all_from_iterable____concatenates_chunks_and_call_send_all(
        self,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.send_all.return_value = None
        chunks: list[bytes | bytearray | memoryview] = [b"a", bytearray(b"b"), memoryview(b"c")]

        # Act
        await AsyncStreamTransport.send_all_from_iterable(mock_stream_transport, chunks)

        # Assert
        assert mock_stream_transport.send_all.await_args_list == [mocker.call(b"abc")]
