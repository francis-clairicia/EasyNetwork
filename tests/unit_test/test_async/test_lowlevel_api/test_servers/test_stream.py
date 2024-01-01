from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator, Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._stream import StreamDataProducer
from easynetwork.lowlevel.api_async.servers.stream import AsyncStreamClient, AsyncStreamServer
from easynetwork.lowlevel.api_async.transports.abc import AsyncListener, AsyncStreamWriteTransport
from easynetwork.lowlevel.std_asyncio.tasks import TaskGroup

import pytest

from .....tools import temporary_backend

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncStreamClient:
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mocker: MockerFixture) -> MagicMock:
        mock_stream_transport = mocker.NonCallableMagicMock(spec=AsyncStreamWriteTransport)
        mock_stream_transport.is_closing.return_value = False

        def close_side_effect() -> None:
            mock_stream_transport.is_closing.return_value = True

        mock_stream_transport.aclose.side_effect = close_side_effect
        return mock_stream_transport

    @pytest.fixture
    @staticmethod
    def mock_stream_protocol(mock_stream_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        def generate_chunks_side_effect(packet: Any) -> Generator[bytes, None, None]:
            yield str(packet).removeprefix("sentinel.").encode("ascii") + b"\n"

        mock_stream_protocol.generate_chunks.side_effect = generate_chunks_side_effect
        mock_stream_protocol.build_packet_from_chunks.side_effect = AssertionError
        return mock_stream_protocol

    @pytest.fixture
    @staticmethod
    def client(mock_stream_transport: MagicMock, mock_stream_protocol: MagicMock) -> AsyncStreamClient[Any]:
        return AsyncStreamClient(mock_stream_transport, StreamDataProducer(mock_stream_protocol))

    @pytest.mark.parametrize("transport_closed", [False, True])
    async def test____is_closing____default(
        self,
        client: AsyncStreamClient[Any],
        mock_stream_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closing.assert_not_called()
        mock_stream_transport.is_closing.return_value = transport_closed

        # Act
        state = client.is_closing()

        # Assert
        mock_stream_transport.is_closing.assert_called_once_with()
        assert state is transport_closed

    async def test____aclose____default(
        self,
        client: AsyncStreamClient[Any],
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.aclose.assert_not_called()

        # Act
        await client.aclose()

        # Assert
        mock_stream_transport.aclose.assert_awaited_once_with()

    async def test____get_extra_info____default(
        self,
        client: AsyncStreamClient[Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = client.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    async def test____send_packet____send_bytes_to_transport(
        self,
        client: AsyncStreamClient[Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it: chunks.extend(it)

        # Act
        await client.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_awaited_once_with(mocker.ANY)
        assert chunks == [b"packet\n"]


@pytest.mark.asyncio
class TestAsyncStreamServer:
    @pytest.fixture
    @staticmethod
    def mock_listener(mocker: MockerFixture) -> MagicMock:
        mock_listener = mocker.NonCallableMagicMock(spec=AsyncListener)
        mock_listener.is_closing.return_value = False

        def close_side_effect() -> None:
            mock_listener.is_closing.return_value = True

        mock_listener.aclose.side_effect = close_side_effect
        return mock_listener

    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int:
        return getattr(request, "param", 256 * 1024)

    @pytest.fixture
    @staticmethod
    def server(
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mock_backend: MagicMock,
    ) -> Iterator[AsyncStreamServer[Any, Any]]:
        with temporary_backend(mock_backend):
            yield AsyncStreamServer(mock_listener, mock_stream_protocol, max_recv_size)

    async def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_listener = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncListener object, got .*$"):
            _ = AsyncStreamServer(mock_invalid_listener, mock_stream_protocol, max_recv_size)

    async def test____dunder_init____invalid_protocol(
        self,
        mock_listener: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = AsyncStreamServer(mock_listener, mock_invalid_protocol, max_recv_size)

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    async def test____dunder_init____max_recv_size____invalid_value(
        self,
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = AsyncStreamServer(mock_listener, mock_stream_protocol, max_recv_size)

    @pytest.mark.parametrize("listener_closed", [False, True])
    async def test____is_closing____default(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_listener: MagicMock,
        listener_closed: bool,
    ) -> None:
        # Arrange
        mock_listener.is_closing.assert_not_called()
        mock_listener.is_closing.return_value = listener_closed

        # Act
        state = server.is_closing()

        # Assert
        mock_listener.is_closing.assert_called_once_with()
        assert state is listener_closed

    async def test____aclose____default(self, server: AsyncStreamServer[Any, Any], mock_listener: MagicMock) -> None:
        # Arrange
        mock_listener.aclose.assert_not_called()

        # Act
        await server.aclose()

        # Assert
        mock_listener.aclose.assert_awaited_once_with()

    async def test____get_extra_info____default(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = server.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    @pytest.mark.parametrize("external_group", [TaskGroup(), None])
    async def test____serve____task_group(
        self,
        external_group: TaskGroup | None,
        server: AsyncStreamServer[Any, Any],
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.serve.side_effect = asyncio.CancelledError
        client_connected_cb = mocker.stub()

        # Act & Assert
        with pytest.raises(asyncio.CancelledError):
            await server.serve(client_connected_cb, external_group)
        mock_listener.serve.assert_awaited_once_with(mocker.ANY, external_group)

    async def test____serve____invalid_transport(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> None:
            mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)
            await handler(mock_invalid_transport)
            pytest.fail("handler() does not raise")

        mock_listener.serve.side_effect = serve_side_effect
        client_connected_cb = mocker.stub()

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(TypeError, match=r"^Expected an AsyncStreamTransport object, got .*$"):
                await server.serve(client_connected_cb, tg)
        client_connected_cb.assert_not_called()
