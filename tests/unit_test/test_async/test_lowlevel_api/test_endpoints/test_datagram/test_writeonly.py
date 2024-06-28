from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.endpoints.datagram import AsyncDatagramSenderEndpoint
from easynetwork.lowlevel.api_async.transports.abc import AsyncDatagramWriteTransport

import pytest
import pytest_asyncio

from ....mock_tools import make_transport_mock
from .base import BaseAsyncEndpointSenderTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestAsyncDatagramSenderEndpoint(BaseAsyncEndpointSenderTests):
    @pytest.fixture
    @staticmethod
    def mock_datagram_transport(
        asyncio_backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=AsyncDatagramWriteTransport, backend=asyncio_backend)

    @pytest_asyncio.fixture
    @staticmethod
    async def endpoint(
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> AsyncIterator[AsyncDatagramSenderEndpoint[Any]]:
        endpoint: AsyncDatagramSenderEndpoint[Any]
        endpoint = AsyncDatagramSenderEndpoint(mock_datagram_transport, mock_datagram_protocol)
        async with endpoint:
            yield endpoint

    async def test____dunder_init____invalid_transport(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncDatagramWriteTransport object, got .*$"):
            _ = AsyncDatagramSenderEndpoint(mock_invalid_transport, mock_datagram_protocol)

    async def test____dunder_init____invalid_protocol(
        self,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncDatagramSenderEndpoint(mock_datagram_transport, mock_invalid_protocol)

    async def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        endpoint: AsyncDatagramSenderEndpoint[Any] = AsyncDatagramSenderEndpoint(
            mock_datagram_transport,
            mock_datagram_protocol,
        )

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed endpoint .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del endpoint

        mock_datagram_transport.aclose.assert_not_called()
