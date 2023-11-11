from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel._stream import StreamDataConsumer
from easynetwork.lowlevel.api_async.endpoints.stream import AsyncStreamEndpoint
from easynetwork.lowlevel.api_async.transports.abc import (
    AsyncStreamReadTransport,
    AsyncStreamTransport,
    AsyncStreamWriteTransport,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncStreamEndpoint:
    @pytest.fixture
    @staticmethod
    def consumer_feed(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(StreamDataConsumer, "feed", autospec=True, side_effect=StreamDataConsumer.feed)

    @pytest.fixture(params=[AsyncStreamReadTransport, AsyncStreamWriteTransport, AsyncStreamTransport])
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
    def mock_stream_protocol(mock_stream_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        def generate_chunks_side_effect(packet: Any) -> Generator[bytes, None, None]:
            yield str(packet).removeprefix("sentinel.").encode("ascii") + b"\n"

        def build_packet_from_chunks_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            buffer = b""
            while True:
                buffer += yield
                if b"\n" not in buffer:
                    continue
                data, buffer = buffer.split(b"\n", 1)
                return getattr(mocker.sentinel, data.decode(encoding="ascii")), buffer

        mock_stream_protocol.generate_chunks.side_effect = generate_chunks_side_effect
        mock_stream_protocol.build_packet_from_chunks.side_effect = build_packet_from_chunks_side_effect
        return mock_stream_protocol

    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int:
        return getattr(request, "param", 256 * 1024)

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> AsyncStreamEndpoint[Any, Any]:
        return AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

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
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_invalid_protocol, max_recv_size)

    @pytest.mark.parametrize("max_recv_size", [1, 2**64], ids=lambda p: f"max_recv_size=={p}")
    async def test____dunder_init____max_recv_size____valid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act
        endpoint: AsyncStreamEndpoint[Any, Any] = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

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
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    @pytest.mark.parametrize("transport_closed", [False, True])
    async def test____is_closing____default(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closing.assert_not_called()
        mock_stream_transport.is_closing.return_value = transport_closed

        # Act
        state = endpoint.is_closing()

        # Assert
        mock_stream_transport.is_closing.assert_called_once_with()
        assert state is transport_closed

    async def test____aclose____default(self, endpoint: AsyncStreamEndpoint[Any, Any], mock_stream_transport: MagicMock) -> None:
        # Arrange
        mock_stream_transport.aclose.assert_not_called()

        # Act
        await endpoint.aclose()

        # Assert
        mock_stream_transport.aclose.assert_awaited_once_with()

    async def test____get_extra_info____default(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = endpoint.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    async def test____send_packet____send_bytes_to_transport(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        with contextlib.suppress(AttributeError):
            mock_stream_transport.send_all_from_iterable.side_effect = lambda it: chunks.extend(it)

        # Act
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support sending data$")
            if mock_stream_transport.__class__ not in (AsyncStreamWriteTransport, AsyncStreamTransport)
            else contextlib.nullcontext()
        ):
            await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        if mock_stream_transport.__class__ in (AsyncStreamWriteTransport, AsyncStreamTransport):
            mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
            mock_stream_transport.send_all_from_iterable.assert_awaited_once_with(mocker.ANY)
            assert chunks == [b"packet\n"]
        else:
            mock_stream_protocol.generate_chunks.assert_not_called()
            assert chunks == []

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
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support sending EOF$")
            if mock_stream_transport.__class__ is not AsyncStreamTransport
            else contextlib.nullcontext()
        ):
            await endpoint.send_eof()

        # Assert
        if mock_stream_transport.__class__ is AsyncStreamTransport:
            mock_stream_transport.send_eof.assert_awaited_once_with()
            with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
                await endpoint.send_packet(mocker.sentinel.packet)
            mock_stream_protocol.generate_chunks.assert_not_called()
            mock_stream_transport.send_all_from_iterable.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamTransport], indirect=True)
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

    async def test____recv_packet____receive_bytes_from_transport(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        with contextlib.suppress(AttributeError):
            mock_stream_transport.recv.side_effect = [b"packet\n"]

        # Act
        packet: Any = mocker.sentinel.packet_not_received
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support receiving data$")
            if mock_stream_transport.__class__ not in (AsyncStreamReadTransport, AsyncStreamTransport)
            else contextlib.nullcontext()
        ):
            packet = await endpoint.recv_packet()

        # Assert
        if mock_stream_transport.__class__ in (AsyncStreamReadTransport, AsyncStreamTransport):
            mock_stream_transport.recv.assert_awaited_once_with(max_recv_size)
            consumer_feed.assert_called_once_with(mocker.ANY, b"packet\n")
            assert packet is mocker.sentinel.packet
        else:
            consumer_feed.assert_not_called()
            assert packet is mocker.sentinel.packet_not_received

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____recv_packet____partial_data(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = await endpoint.recv_packet()

        # Assert
        assert mock_stream_transport.recv.await_args_list == [mocker.call(max_recv_size) for _ in range(2)]
        assert consumer_feed.call_args_list == [
            mocker.call(mocker.ANY, b"pac"),
            mocker.call(mocker.ANY, b"ket\n"),
        ]
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____recv_packet____extra_data(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = await endpoint.recv_packet()
        packet_2: Any = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_awaited_once()
        consumer_feed.assert_called_once_with(mocker.ANY, b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____recv_packet____eof_error____default(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]

        # Act
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_awaited_once()
        consumer_feed.assert_not_called()

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____special_case____recv_packet____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = await endpoint.recv_packet()

        mock_stream_transport.recv.reset_mock()

        # Act
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_not_called()
