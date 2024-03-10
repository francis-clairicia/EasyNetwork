from __future__ import annotations

import contextlib
import warnings
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import IncrementalDeserializeError, StreamProtocolParseError, UnsupportedOperation
from easynetwork.lowlevel.api_async.endpoints.stream import AsyncStreamEndpoint
from easynetwork.lowlevel.api_async.transports.abc import (
    AsyncBufferedStreamReadTransport,
    AsyncStreamReadTransport,
    AsyncStreamTransport,
    AsyncStreamWriteTransport,
)
from easynetwork.warnings import ManualBufferAllocationWarning

import pytest

from ...._utils import make_async_recv_into_side_effect as make_recv_into_side_effect
from ....base import BaseTestWithStreamProtocol

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

pytest_mark_ignore_manual_buffer_allocation_warning = pytest.mark.filterwarnings(
    f"ignore::{ManualBufferAllocationWarning.__module__}.{ManualBufferAllocationWarning.__qualname__}",
)


@pytest.mark.asyncio
class TestAsyncStreamEndpoint(BaseTestWithStreamProtocol):
    @pytest.fixture(
        params=[AsyncStreamReadTransport, AsyncBufferedStreamReadTransport, AsyncStreamWriteTransport, AsyncStreamTransport]
    )
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
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> AsyncStreamEndpoint[Any, Any]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ManualBufferAllocationWarning)
            return AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    @pytest_mark_ignore_manual_buffer_allocation_warning
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

    @pytest_mark_ignore_manual_buffer_allocation_warning
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

    @pytest_mark_ignore_manual_buffer_allocation_warning
    @pytest.mark.parametrize("max_recv_size", [1, 2**16], ids=lambda p: f"max_recv_size=={p}")
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
        if isinstance(mock_stream_transport, AsyncStreamReadTransport):
            assert endpoint.max_recv_size == max_recv_size
        else:
            assert endpoint.max_recv_size == 0

    @pytest_mark_ignore_manual_buffer_allocation_warning
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

    @pytest.mark.parametrize("manual_buffer_allocation", ["unknown", ""], ids=lambda p: f"manual_buffer_allocation=={p!r}")
    async def test____dunder_init____manual_buffer_allocation____invalid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        manual_buffer_allocation: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r'^"manual_buffer_allocation" must be "try", "no" or "force"$'):
            _ = AsyncStreamEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation=manual_buffer_allocation,
            )

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

    async def test____extra_attributes____default(
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
        if hasattr(mock_stream_transport, "send_all_from_iterable"):
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
            mock_stream_transport.send_all.assert_not_called()
            assert chunks == [b"packet\n"]
        else:
            mock_stream_protocol.generate_chunks.assert_not_called()
            assert chunks == []

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamWriteTransport], indirect=True)
    async def test____send_packet____protocol_crashed(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it: chunks.extend(it)
        expected_error = Exception("Error")

        def side_effect(packet: Any) -> Generator[bytes, None, None]:
            raise expected_error
            yield  # type: ignore[unreachable]

        mock_stream_protocol.generate_chunks.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$") as exc_info:
            await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.__cause__ is expected_error
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
        stream_protocol_mode: Literal["data", "buffer"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if hasattr(mock_stream_transport, "recv"):
            mock_stream_transport.recv.side_effect = [b"packet\n"]
        if hasattr(mock_stream_transport, "recv_into"):
            mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])

        # Act
        packet: Any = mocker.sentinel.packet_not_received
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support receiving data$")
            if mock_stream_transport.__class__
            not in (AsyncStreamReadTransport, AsyncBufferedStreamReadTransport, AsyncStreamTransport)
            else contextlib.nullcontext()
        ):
            packet = await endpoint.recv_packet()

        # Assert
        if mock_stream_transport.__class__ is AsyncBufferedStreamReadTransport:
            if stream_protocol_mode == "buffer":
                mock_stream_transport.recv_into.assert_awaited_once_with(mocker.ANY)
                mock_stream_transport.recv.assert_not_called()
            else:
                mock_stream_transport.recv.assert_awaited_once_with(max_recv_size)
                mock_stream_transport.recv_into.assert_not_called()
        elif mock_stream_transport.__class__ in (AsyncStreamReadTransport, AsyncStreamTransport):
            mock_stream_transport.recv.assert_awaited_once_with(max_recv_size)
            assert packet is mocker.sentinel.packet
        else:
            assert packet is mocker.sentinel.packet_not_received

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____recv_packet____partial_data(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = await endpoint.recv_packet()

        # Assert
        assert mock_stream_transport.recv.await_args_list == [mocker.call(max_recv_size) for _ in range(2)]
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("mock_stream_transport", [AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____partial_data(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"pac", b"ket\n"])

        # Act
        packet: Any = await endpoint.recv_packet()

        # Assert
        assert mock_stream_transport.recv_into.await_args_list == [mocker.call(mocker.ANY) for _ in range(2)]
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____recv_packet____extra_data(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = await endpoint.recv_packet()
        packet_2: Any = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_awaited_once()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.parametrize("mock_stream_transport", [AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____extra_data(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\npacket_2\n"])

        # Act
        packet_1: Any = await endpoint.recv_packet()
        packet_2: Any = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv_into.assert_awaited_once()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____recv_packet____eof_error(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]

        # Act
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_awaited_once()

    @pytest.mark.parametrize("mock_stream_transport", [AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____eof_error(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])

        # Act
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv_into.assert_awaited_once()

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    async def test____recv_packet____protocol_parse_error(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Error", b""))

        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_stream_protocol.build_packet_from_chunks.side_effect = side_effect

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("mock_stream_transport", [AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____protocol_parse_error(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Error", b""))

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_buffered_stream_receiver.build_packet_from_buffer.side_effect = side_effect

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    async def test____recv_packet____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]
        expected_error = Exception("Error")

        if before_transport_reading:
            await endpoint.recv_packet()

        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_stream_protocol.build_packet_from_chunks.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_chunks\(\) crashed$") as exc_info:
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value.__cause__ is expected_error

    @pytest.mark.parametrize("mock_stream_transport", [AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    async def test____recv_packet____buffered____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\n", b"packet_2\n"])
        expected_error = Exception("Error")

        if before_transport_reading:
            await endpoint.recv_packet()

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_buffered_stream_receiver.build_packet_from_buffer.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value.__cause__ is expected_error

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

    @pytest.mark.parametrize("mock_stream_transport", [AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____special_case____recv_packet____buffered____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: AsyncStreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = await endpoint.recv_packet()

        mock_stream_transport.recv_into.reset_mock()

        # Act
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv_into.assert_not_called()

    # NOTE: The cases where recv_packet() uses transport.recv() or transport.recv_into() when manual_buffer_allocation == "try"
    #       are implicitly tested above, because this is the default behavior.

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport, AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____manual_buffer_allocation____try____but_stream_protocol_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with warnings.catch_warnings():
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="try")

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____manual_buffer_allocation____try____but_stream_transport_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.warns(
            ManualBufferAllocationWarning,
            match=r"^The transport implementation .+ does not implement AsyncBufferedStreamReadTransport interface$",
        ):
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="try")

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport, AsyncBufferedStreamReadTransport], indirect=True)
    async def test____manual_buffer_allocation____disabled(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        # Act
        endpoint: AsyncStreamEndpoint[Any, Any]
        with warnings.catch_warnings():
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            endpoint = AsyncStreamEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="no",
            )
        packet = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_awaited_once_with(max_recv_size)
        if hasattr(mock_stream_transport, "recv_into"):
            mock_stream_transport.recv_into.assert_not_called()
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport, AsyncBufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____manual_buffer_allocation____force____but_stream_protocol_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with (
            pytest.raises(UnsupportedOperation, match=r"^This protocol does not support the buffer API$"),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="force")

    @pytest.mark.parametrize("mock_stream_transport", [AsyncStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____manual_buffer_allocation____force____but_stream_transport_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with (
            pytest.raises(
                UnsupportedOperation,
                match=r"^The transport implementation .+ does not implement AsyncBufferedStreamReadTransport interface$",
            ),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            _ = AsyncStreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="force")
