from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.endpoints.stream import AsyncStreamEndpoint
from easynetwork.lowlevel.api_async.transports.abc import AsyncStreamTransport

import pytest
import pytest_asyncio

from ....._utils import make_async_recv_into_side_effect as make_recv_into_side_effect
from ....mock_tools import make_transport_mock
from .base import BaseAsyncEndpointReceiveTests, BaseAsyncEndpointSendTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestAsyncStreamEndpoint(BaseAsyncEndpointSendTests, BaseAsyncEndpointReceiveTests):
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(
        asyncio_backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=AsyncStreamTransport, backend=asyncio_backend)

    @pytest_asyncio.fixture
    @staticmethod
    async def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> AsyncIterator[AsyncStreamEndpoint[Any, Any]]:
        endpoint: AsyncStreamEndpoint[Any, Any]
        endpoint = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
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
        with pytest.raises(TypeError, match=r"^Expected an AsyncStreamTransport object, got .*$"):
            _ = AsyncStreamEndpoint(mock_invalid_transport, mock_stream_protocol, max_recv_size)

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
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_invalid_protocol, max_recv_size)

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
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    async def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        endpoint: AsyncStreamEndpoint[Any, Any] = AsyncStreamEndpoint(
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

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    async def test____send_eof____default(
        self,
        transport_closed: bool,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closing.return_value = transport_closed

        # Act
        await endpoint.send_eof()

        # Assert
        mock_stream_transport.send_eof.assert_awaited_once_with()
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            await endpoint.send_packet(mocker.sentinel.packet)
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_transport.send_all_from_iterable.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    async def test____send_eof____idempotent(
        self,
        transport_closed: bool,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closing.return_value = transport_closed
        await endpoint.send_eof()

        # Act
        await endpoint.send_eof()

        # Assert
        mock_stream_transport.send_eof.assert_awaited_once_with()
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            await endpoint.send_packet(mocker.sentinel.packet)

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____special_case____send_packet____eof_error____still_try_socket_send(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it: chunks.extend(it)
        mock_stream_transport.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError):
            _ = await endpoint.recv_packet()

        mock_stream_transport.recv.reset_mock()

        # Act
        await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_awaited_once_with(mocker.ANY)
        mock_stream_transport.send_all.assert_not_called()
        assert chunks == [b"packet\n"]

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____special_case____send_packet____eof_error____recv_buffered____still_try_socket_send(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it: chunks.extend(it)
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])
        with pytest.raises(ConnectionAbortedError):
            _ = await endpoint.recv_packet()

        mock_stream_transport.recv_into.reset_mock()

        # Act
        await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_awaited_once_with(mocker.ANY)
        mock_stream_transport.send_all.assert_not_called()
        assert chunks == [b"packet\n"]
