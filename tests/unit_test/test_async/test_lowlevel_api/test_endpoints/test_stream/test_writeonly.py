from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.endpoints.stream import AsyncStreamSenderEndpoint
from easynetwork.lowlevel.api_async.transports.abc import AsyncStreamWriteTransport
from easynetwork.lowlevel.std_asyncio.backend import AsyncIOBackend

import pytest
import pytest_asyncio

from ....mock_tools import make_transport_mock
from .base import BaseAsyncEndpointSendTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestAsyncStreamSenderEndpoint(BaseAsyncEndpointSendTests):
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(
        asyncio_backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=AsyncStreamWriteTransport, backend=asyncio_backend)

    @pytest_asyncio.fixture
    @staticmethod
    async def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> AsyncIterator[AsyncStreamSenderEndpoint[Any]]:
        endpoint: AsyncStreamSenderEndpoint[Any] = AsyncStreamSenderEndpoint(mock_stream_transport, mock_stream_protocol)
        async with endpoint:
            yield endpoint

    async def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncStreamWriteTransport object, got .*$"):
            _ = AsyncStreamSenderEndpoint(mock_invalid_transport, mock_stream_protocol)

    async def test____dunder_init____invalid_protocol(
        self,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = AsyncStreamSenderEndpoint(mock_stream_transport, mock_invalid_protocol)

    async def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        endpoint: AsyncStreamSenderEndpoint[Any] = AsyncStreamSenderEndpoint(mock_stream_transport, mock_stream_protocol)

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed endpoint .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del endpoint

        mock_stream_transport.aclose.assert_not_called()
