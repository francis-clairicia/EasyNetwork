from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_async.endpoints.stream import AsyncStreamReceiverEndpoint
from easynetwork.lowlevel.api_async.transports.abc import AsyncBufferedStreamReadTransport, AsyncStreamReadTransport
from easynetwork.lowlevel.std_asyncio.backend import AsyncIOBackend

import pytest
import pytest_asyncio

from ....mock_tools import make_transport_mock
from .base import BaseAsyncEndpointReceiveTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

    from ......pytest_plugins.async_finalizer import AsyncFinalizer


class TestAsyncStreamReceiverEndpoint(BaseAsyncEndpointReceiveTests):
    @pytest.fixture(params=["recv_data", "recv_buffer"])
    @staticmethod
    def mock_stream_transport(
        asyncio_backend: AsyncIOBackend,
        request: pytest.FixtureRequest,
        mocker: MockerFixture,
    ) -> MagicMock:
        match request.param:
            case "recv_data":
                return make_transport_mock(mocker=mocker, spec=AsyncStreamReadTransport, backend=asyncio_backend)
            case "recv_buffer":
                return make_transport_mock(mocker=mocker, spec=AsyncBufferedStreamReadTransport, backend=asyncio_backend)
            case _:
                pytest.fail("Invalid stream transport parameter")

    @pytest_asyncio.fixture
    @staticmethod
    async def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> AsyncIterator[AsyncStreamReceiverEndpoint[Any]]:
        endpoint: AsyncStreamReceiverEndpoint[Any]
        try:
            endpoint = AsyncStreamReceiverEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
        except UnsupportedOperation:
            pytest.skip("Skip unsupported combination")
        async with endpoint:
            yield endpoint

    async def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncStreamReadTransport object, got .*$"):
            _ = AsyncStreamReceiverEndpoint(mock_invalid_transport, mock_stream_protocol, max_recv_size)

    async def test____dunder_init____invalid_protocol(
        self,
        mock_stream_transport: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = AsyncStreamReceiverEndpoint(mock_stream_transport, mock_invalid_protocol, max_recv_size)

    @pytest.mark.parametrize("mock_stream_transport", ["recv_buffer"], indirect=True)
    @pytest.mark.parametrize("max_recv_size", [1, 2**16], ids=lambda p: f"max_recv_size=={p}")
    async def test____dunder_init____max_recv_size____valid_value(
        self,
        async_finalizer: AsyncFinalizer,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act
        endpoint: AsyncStreamReceiverEndpoint[Any] = AsyncStreamReceiverEndpoint(
            mock_stream_transport, mock_stream_protocol, max_recv_size
        )
        async_finalizer.add_finalizer(endpoint.aclose)

        # Assert
        assert endpoint.max_recv_size == max_recv_size

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    async def test____dunder_init____max_recv_size____invalid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = AsyncStreamReceiverEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    @pytest.mark.parametrize("mock_stream_transport", ["recv_buffer"], indirect=True)
    async def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        endpoint: AsyncStreamReceiverEndpoint[Any] = AsyncStreamReceiverEndpoint(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size,
        )

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed endpoint .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del endpoint

        mock_stream_transport.aclose.assert_not_called()

    @pytest.mark.parametrize("mock_stream_transport", ["recv_data"], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____manual_buffer_allocation____but_stream_transport_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(
            UnsupportedOperation,
            match=r"^The transport implementation .+ does not implement AsyncBufferedStreamReadTransport interface$",
        ):
            _ = AsyncStreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
            )
