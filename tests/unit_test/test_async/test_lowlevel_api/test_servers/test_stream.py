# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import contextlib
import warnings
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from typing import TYPE_CHECKING, Any, Literal, NoReturn

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel._stream import StreamDataProducer
from easynetwork.lowlevel.api_async.servers.stream import AsyncStreamClient, AsyncStreamServer
from easynetwork.lowlevel.api_async.transports.abc import (
    AsyncBufferedStreamReadTransport,
    AsyncListener,
    AsyncStreamTransport,
    AsyncStreamWriteTransport,
)
from easynetwork.lowlevel.std_asyncio.tasks import TaskGroup
from easynetwork.warnings import ManualBufferAllocationWarning

import pytest

from .....tools import temporary_backend
from ...._utils import make_async_recv_into_side_effect as make_recv_into_side_effect, stub_decorator
from ....base import BaseTestWithStreamProtocol

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class _AsyncBufferedStreamTransport(AsyncStreamTransport, AsyncBufferedStreamReadTransport):
    __slots__ = ()


@pytest.mark.asyncio
class TestAsyncStreamClient(BaseTestWithStreamProtocol):
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
    def stream_protocol_mode() -> str:
        return "data"

    @pytest.fixture
    @staticmethod
    def client_exit_stack() -> contextlib.AsyncExitStack:
        return contextlib.AsyncExitStack()

    @pytest.fixture
    @staticmethod
    def client(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        client_exit_stack: contextlib.AsyncExitStack,
    ) -> AsyncStreamClient[Any]:
        return AsyncStreamClient(mock_stream_transport, StreamDataProducer(mock_stream_protocol), client_exit_stack)

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
        client_exit_stack: contextlib.AsyncExitStack,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.aclose.assert_not_called()
        close_stub = mocker.async_stub()
        client_exit_stack.push_async_callback(close_stub)

        # Act
        await client.aclose()

        # Assert
        mock_stream_transport.aclose.assert_awaited_once_with()
        close_stub.assert_awaited_once_with()

    async def test____extra_attributes____default(
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
class TestAsyncStreamServer(BaseTestWithStreamProtocol):
    @pytest.fixture
    @staticmethod
    def mock_listener(mocker: MockerFixture) -> MagicMock:
        mock_listener = mocker.NonCallableMagicMock(spec=AsyncListener)
        mock_listener.is_closing.return_value = False

        def close_side_effect() -> None:
            mock_listener.is_closing.return_value = True

        mock_listener.aclose.side_effect = close_side_effect
        return mock_listener

    @pytest.fixture(params=[AsyncStreamTransport, _AsyncBufferedStreamTransport])
    @staticmethod
    def mock_stream_transport(request: pytest.FixtureRequest, mocker: MockerFixture) -> MagicMock:
        mock_stream_transport = mocker.NonCallableMagicMock(spec=request.param)
        mock_stream_transport.is_closing.return_value = False

        def close_side_effect() -> None:
            mock_stream_transport.is_closing.return_value = True

        mock_stream_transport.aclose.side_effect = close_side_effect
        return mock_stream_transport

    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int:
        return getattr(request, "param", 256 * 1024)

    @pytest.fixture
    @staticmethod
    def manual_buffer_allocation(request: Any) -> str:
        return getattr(request, "param", "try")

    @pytest.fixture
    @staticmethod
    def server(
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        manual_buffer_allocation: Literal["try", "no", "force"],
        mock_backend: MagicMock,
    ) -> Iterator[AsyncStreamServer[Any, Any]]:
        with temporary_backend(mock_backend):
            yield AsyncStreamServer(
                mock_listener,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation=manual_buffer_allocation,
            )

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

    @pytest.mark.parametrize("manual_buffer_allocation", ["unknown", ""], ids=lambda p: f"manual_buffer_allocation=={p!r}")
    async def test____dunder_init____manual_buffer_allocation____invalid_value(
        self,
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        manual_buffer_allocation: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r'^"manual_buffer_allocation" must be "try", "no" or "force"$'):
            _ = AsyncStreamServer(
                mock_listener,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation=manual_buffer_allocation,
            )

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

    async def test____extra_attributes____default(
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
        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)
            await handler(mock_invalid_transport)
            pytest.fail("handler() does not raise")

        mock_listener.serve.side_effect = serve_side_effect

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            yield

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(TypeError, match=r"^Expected an AsyncStreamTransport object, got .*$"):
                await server.serve(client_connected_cb, tg)
        client_connected_cb.assert_not_called()

    @pytest.mark.parametrize("mock_stream_transport", [_AsyncBufferedStreamTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    @pytest.mark.parametrize("manual_buffer_allocation", ["try", "force"], indirect=True)
    async def test____manual_buffer_allocation____is_available(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        packet_received = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            packet = yield
            packet_received(packet)

        mock_listener.serve.side_effect = serve_side_effect

        # Act
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"), warnings.catch_warnings():
                warnings.simplefilter("error", ManualBufferAllocationWarning)
                await server.serve(client_connected_cb, tg)

        # Assert
        mock_stream_transport.recv_into.assert_awaited_once()
        mock_stream_transport.recv.assert_not_called()
        packet_received.assert_called_once_with(mocker.sentinel.packet)

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamTransport, _AsyncBufferedStreamTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    @pytest.mark.parametrize("manual_buffer_allocation", ["try"], indirect=True)
    async def test____manual_buffer_allocation____try____but_stream_protocol_does_not_support_it(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        packet_received = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            packet = yield
            packet_received(packet)

        mock_listener.serve.side_effect = serve_side_effect

        # Act
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"), warnings.catch_warnings():
                warnings.simplefilter("error", ManualBufferAllocationWarning)
                await server.serve(client_connected_cb, tg)

        # Assert
        mock_stream_transport.recv.assert_awaited_once()
        if hasattr(mock_stream_transport, "recv_into"):
            mock_stream_transport.recv_into.assert_not_called()
        packet_received.assert_called_once_with(mocker.sentinel.packet)

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    @pytest.mark.parametrize("manual_buffer_allocation", ["try"], indirect=True)
    async def test____manual_buffer_allocation____try____but_stream_transport_does_not_support_it(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        packet_received = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            packet = yield
            packet_received(packet)

        mock_listener.serve.side_effect = serve_side_effect

        # Act
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"), pytest.warns(ManualBufferAllocationWarning):
                await server.serve(client_connected_cb, tg)

        # Assert
        mock_stream_transport.recv.assert_awaited_once()
        packet_received.assert_called_once_with(mocker.sentinel.packet)

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamTransport, _AsyncBufferedStreamTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["data", "buffer"], indirect=True)
    @pytest.mark.parametrize("manual_buffer_allocation", ["no"], indirect=True)
    async def test____manual_buffer_allocation____disabled(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        packet_received = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            packet = yield
            packet_received(packet)

        mock_listener.serve.side_effect = serve_side_effect

        # Act
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"), warnings.catch_warnings():
                warnings.simplefilter("error", ManualBufferAllocationWarning)
                await server.serve(client_connected_cb, tg)

        # Assert
        mock_stream_transport.recv.assert_awaited_once()
        if hasattr(mock_stream_transport, "recv_into"):
            mock_stream_transport.recv_into.assert_not_called()
        packet_received.assert_called_once_with(mocker.sentinel.packet)

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamTransport, _AsyncBufferedStreamTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    @pytest.mark.parametrize("manual_buffer_allocation", ["force"], indirect=True)
    async def test____manual_buffer_allocation____force____but_stream_protocol_does_not_support_it(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        packet_received = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            packet = yield
            packet_received(packet)

        mock_listener.serve.side_effect = serve_side_effect

        # Act
        async with TaskGroup() as tg:
            with (
                pytest.raises(UnsupportedOperation, match=r"^This protocol does not support the buffer API$"),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("error", ManualBufferAllocationWarning)
                await server.serve(client_connected_cb, tg)

        # Assert
        client_connected_cb.assert_not_called()
        mock_stream_transport.recv.assert_not_called()
        if hasattr(mock_stream_transport, "recv_into"):
            mock_stream_transport.recv_into.assert_not_called()
        packet_received.assert_not_called()

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    @pytest.mark.parametrize("manual_buffer_allocation", ["force"], indirect=True)
    async def test____manual_buffer_allocation____force____but_stream_transport_does_not_support_it(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        packet_received = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            packet = yield
            packet_received(packet)

        mock_listener.serve.side_effect = serve_side_effect

        # Act
        async with TaskGroup() as tg:
            with (
                pytest.raises(
                    UnsupportedOperation,
                    match=r"^The transport implementation .+ does not implement AsyncBufferedStreamReadTransport interface$",
                ),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("error", ManualBufferAllocationWarning)
                await server.serve(client_connected_cb, tg)

        # Assert
        client_connected_cb.assert_not_called()
        mock_stream_transport.recv.assert_not_called()
        packet_received.assert_not_called()

    # @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport, AsyncBufferedStreamReadTransport], indirect=True)
    # @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    # async def test____manual_buffer_allocation____force____but_stream_protocol_does_not_support_it(
    #     self,
    #     mock_stream_transport: MagicMock,
    #     mock_stream_protocol: MagicMock,
    #     max_recv_size: int,
    # ) -> None:
    #     # Arrange

    #     # Act & Assert
    #     with (
    #         pytest.raises(UnsupportedOperation, match=r"^This protocol does not support the buffer API$"),
    #         warnings.catch_warnings(),
    #     ):
    #         warnings.simplefilter("error")
    #         _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="force")

    # @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    # @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    # async def test____manual_buffer_allocation____force____but_stream_transport_does_not_support_it(
    #     self,
    #     mock_stream_transport: MagicMock,
    #     mock_stream_protocol: MagicMock,
    #     max_recv_size: int,
    # ) -> None:
    #     # Arrange

    #     # Act & Assert
    #     with (
    # ,
    #         warnings.catch_warnings(),
    #     ):
    #         warnings.simplefilter("error")
    #         _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="force")
