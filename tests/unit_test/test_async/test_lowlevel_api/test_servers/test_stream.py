# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import warnings
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, NoReturn

from easynetwork.lowlevel._stream import StreamDataProducer
from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend._asyncio.tasks import TaskGroup
from easynetwork.lowlevel.api_async.servers.stream import AsyncStreamServer, ConnectedStreamClient
from easynetwork.lowlevel.api_async.transports.abc import AsyncListener, AsyncStreamTransport, AsyncStreamWriteTransport
from easynetwork.warnings import ManualBufferAllocationWarning

import pytest
import pytest_asyncio

from ...._utils import make_async_recv_into_side_effect as make_recv_into_side_effect, stub_decorator
from ....base import BaseTestWithStreamProtocol
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestConnectedStreamClient(BaseTestWithStreamProtocol):
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(asyncio_backend: AsyncIOBackend, mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=AsyncStreamWriteTransport, backend=asyncio_backend)

    @pytest.fixture
    @staticmethod
    def stream_protocol_mode() -> str:
        return "data"

    @pytest.fixture
    @staticmethod
    def client(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> ConnectedStreamClient[Any]:
        return ConnectedStreamClient(
            _transport=mock_stream_transport,
            _producer=StreamDataProducer(mock_stream_protocol),
        )

    @pytest.mark.parametrize("transport_closed", [False, True])
    async def test____is_closing____default(
        self,
        client: ConnectedStreamClient[Any],
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
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.aclose.assert_not_called()

        # Act
        await client.aclose()

        # Assert
        mock_stream_transport.aclose.assert_awaited_once_with()

    async def test____extra_attributes____default(
        self,
        client: ConnectedStreamClient[Any],
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
        client: ConnectedStreamClient[Any],
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
    def mock_listener(mock_backend: MagicMock, mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=AsyncListener, backend=mock_backend)

    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mock_backend: MagicMock, mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=AsyncStreamTransport, backend=mock_backend)

    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int:
        return getattr(request, "param", 256 * 1024)

    @pytest_asyncio.fixture
    @staticmethod
    async def server(
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> AsyncIterator[AsyncStreamServer[Any, Any]]:
        server: AsyncStreamServer[Any, Any] = AsyncStreamServer(
            mock_listener,
            mock_stream_protocol,
            max_recv_size,
        )

        async with contextlib.aclosing(server):
            yield server

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
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
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

    async def test____dunder_del____ResourceWarning(
        self,
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        server: AsyncStreamServer[Any, Any] = AsyncStreamServer(mock_listener, mock_stream_protocol, max_recv_size)

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed server .+ pointing to .+ \(and cannot be closed synchronously\)$",
        ):
            del server

        mock_listener.aclose.assert_not_called()

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
            pytest.fail("handler() did not raise")

        mock_listener.serve.side_effect = serve_side_effect

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            yield

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(TypeError, match=r"^Expected an AsyncStreamTransport object, got .*$"):
                await server.serve(client_connected_cb, tg)
        client_connected_cb.assert_not_called()

    @pytest.mark.parametrize("give_filter", [False, True], ids=lambda p: f"give_filter=={p}")
    async def test____serve____disconnect_error_filter____mask_connection_error_on_receive(
        self,
        give_filter: bool,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        mock_listener.serve.side_effect = serve_side_effect
        mock_stream_transport.recv.side_effect = ConnectionResetError
        mock_stream_transport.recv_into.side_effect = ConnectionResetError

        exception_caught = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            try:
                yield
            except ConnectionResetError:
                exception_caught(False)
            except GeneratorExit:
                exception_caught(True)
                raise
            else:
                exception_caught(None)

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                if give_filter:
                    await server.serve(
                        client_connected_cb,
                        tg,
                        disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
                    )
                else:
                    await server.serve(client_connected_cb, tg)

        exception_caught.assert_called_once_with(True if give_filter else False)

    async def test____serve____disconnect_error_filter____reraise_non_filtered_errors(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        mock_listener.serve.side_effect = serve_side_effect
        mock_stream_transport.recv.side_effect = OSError
        mock_stream_transport.recv_into.side_effect = OSError

        exception_caught = mocker.stub()

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            try:
                yield
            except OSError:
                exception_caught(False)
            except GeneratorExit:
                exception_caught(True)
                raise

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                await server.serve(
                    client_connected_cb,
                    tg,
                    disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
                )

        exception_caught.assert_called_once_with(False)

    @pytest.mark.parametrize("invalid_timeout", [-1.0, math.nan])
    async def test____serve____invalid_timeout(
        self,
        invalid_timeout: float,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        mock_listener.serve.side_effect = serve_side_effect
        mock_stream_transport.recv.side_effect = OSError
        mock_stream_transport.recv_into.side_effect = OSError

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[float, Any]:
            with pytest.raises(ValueError, match=r"^Invalid delay: .+$"):
                yield invalid_timeout

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                await server.serve(client_connected_cb, tg)

        assert not caplog.records

    async def test____serve____unhandled_exception____from_system(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        mock_listener.serve.side_effect = serve_side_effect
        mock_stream_transport.recv.side_effect = OSError("recv() error")
        mock_stream_transport.recv_into.side_effect = OSError("recv() error")

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            yield

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                await server.serve(client_connected_cb, tg)

        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], OSError)
        assert caplog.records[0].getMessage() == "Unhandled exception: recv() error"

    async def test____serve____unhandled_exception____from_request_handler(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        async def serve_side_effect(handler: Callable[[Any], Awaitable[None]], task_group: Any) -> NoReturn:
            await handler(mock_stream_transport)
            raise asyncio.CancelledError("serve_side_effect")

        mock_listener.serve.side_effect = serve_side_effect
        mock_stream_transport.recv.side_effect = [b"packet\n"]
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])

        @stub_decorator(mocker)
        async def client_connected_cb(_: Any) -> AsyncGenerator[None, Any]:
            yield
            raise ValueError("something bad happened")

        # Act & Assert
        async with TaskGroup() as tg:
            with pytest.raises(asyncio.CancelledError, match=r"^serve_side_effect$"):
                await server.serve(client_connected_cb, tg)

        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], ValueError)
        assert caplog.records[0].getMessage() == "Unhandled exception: something bad happened"

    async def test____get_backend____returns_inner_listener_backend(
        self,
        server: AsyncStreamServer[Any, Any],
        mock_listener: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert server.backend() is mock_listener.backend()

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
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

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
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
        mock_stream_transport.recv_into.assert_not_called()
        packet_received.assert_called_once_with(mocker.sentinel.packet)
