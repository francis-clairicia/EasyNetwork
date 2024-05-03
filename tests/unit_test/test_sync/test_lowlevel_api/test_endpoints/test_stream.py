from __future__ import annotations

import contextlib
import math
import warnings
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import IncrementalDeserializeError, StreamProtocolParseError, UnsupportedOperation
from easynetwork.lowlevel.api_sync.endpoints.stream import StreamEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import (
    BufferedStreamReadTransport,
    StreamReadTransport,
    StreamTransport,
    StreamWriteTransport,
)
from easynetwork.warnings import ManualBufferAllocationWarning

import pytest

from ...._utils import make_recv_into_side_effect
from ....base import BaseTestWithStreamProtocol

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


pytest_mark_ignore_manual_buffer_allocation_warning = pytest.mark.filterwarnings(
    f"ignore::{ManualBufferAllocationWarning.__module__}.{ManualBufferAllocationWarning.__qualname__}",
)


class TestStreamEndpoint(BaseTestWithStreamProtocol):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_time_perfcounter(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("time.perf_counter", autospec=True, return_value=12345)

    @pytest.fixture(
        params=[
            pytest.param(StreamReadTransport, marks=pytest_mark_ignore_manual_buffer_allocation_warning),
            pytest.param(BufferedStreamReadTransport),
            pytest.param(StreamWriteTransport),
            pytest.param(StreamTransport, marks=pytest_mark_ignore_manual_buffer_allocation_warning),
        ]
    )
    @staticmethod
    def mock_stream_transport(request: pytest.FixtureRequest, mocker: MockerFixture) -> MagicMock:
        mock_stream_transport = mocker.NonCallableMagicMock(spec=request.param)
        mock_stream_transport.is_closed.return_value = False

        def close_side_effect() -> None:
            mock_stream_transport.is_closed.return_value = True

        mock_stream_transport.close.side_effect = close_side_effect
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
    ) -> Iterator[StreamEndpoint[Any, Any]]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ManualBufferAllocationWarning)
            endpoint: StreamEndpoint[Any, Any] = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
        with contextlib.closing(endpoint):
            yield endpoint

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(math.inf, id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def recv_timeout(request: Any) -> Any:
        return request.param

    @pytest.fixture
    @staticmethod
    def expected_recv_timeout(recv_timeout: float | None) -> float:
        if recv_timeout is None:
            return math.inf
        return recv_timeout

    @pytest.fixture(
        params=[
            pytest.param(None, id="blocking (None)"),
            pytest.param(math.inf, id="blocking (+inf)"),
            pytest.param(0, id="non_blocking"),
            pytest.param(123456789, id="with_timeout"),
        ]
    )
    @staticmethod
    def send_timeout(request: Any) -> Any:
        return request.param

    @pytest.fixture
    @staticmethod
    def expected_send_timeout(send_timeout: float | None) -> float:
        if send_timeout is None:
            return math.inf
        return send_timeout

    def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamTransport object, got .*$"):
            _ = StreamEndpoint(mock_invalid_transport, mock_stream_protocol, max_recv_size)

    def test____dunder_init____invalid_protocol(
        self,
        mock_stream_transport: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = StreamEndpoint(mock_stream_transport, mock_invalid_protocol, max_recv_size)

    @pytest.mark.parametrize("max_recv_size", [1, 2**16], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____max_recv_size____valid_value(
        self,
        request: pytest.FixtureRequest,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act
        endpoint: StreamEndpoint[Any, Any] = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
        request.addfinalizer(endpoint.close)

        # Assert
        if isinstance(mock_stream_transport, StreamReadTransport):
            assert endpoint.max_recv_size == max_recv_size
        else:
            assert endpoint.max_recv_size == 0

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____max_recv_size____invalid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    @pytest.mark.parametrize("manual_buffer_allocation", ["unknown", ""], ids=lambda p: f"manual_buffer_allocation=={p!r}")
    def test____dunder_init____manual_buffer_allocation____invalid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        manual_buffer_allocation: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r'^"manual_buffer_allocation" must be "try", "no" or "force"$'):
            _ = StreamEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation=manual_buffer_allocation,
            )

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        endpoint: StreamEndpoint[Any, Any] = StreamEndpoint(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size,
            manual_buffer_allocation="no",
        )

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed endpoint .+$"):
            del endpoint

        mock_stream_transport.close.assert_called()

    @pytest.mark.parametrize("transport_closed", [False, True])
    def test____is_closed____default(
        self,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closed.assert_not_called()
        mock_stream_transport.is_closed.return_value = transport_closed

        # Act
        state = endpoint.is_closed()

        # Assert
        mock_stream_transport.is_closed.assert_called_once_with()
        assert state is transport_closed

    def test____close____default(self, endpoint: StreamEndpoint[Any, Any], mock_stream_transport: MagicMock) -> None:
        # Arrange
        mock_stream_transport.close.assert_not_called()

        # Act
        endpoint.close()

        # Assert
        mock_stream_transport.close.assert_called_once_with()

    def test____extra_attributes____default(
        self,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = endpoint.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    def test____send_packet____send_bytes_to_transport(
        self,
        send_timeout: float | None,
        expected_send_timeout: float,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        if hasattr(mock_stream_transport, "send_all_from_iterable"):
            mock_stream_transport.send_all_from_iterable.side_effect = lambda it, timeout: chunks.extend(it)

        # Act
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support sending data$")
            if mock_stream_transport.__class__ not in (StreamWriteTransport, StreamTransport)
            else contextlib.nullcontext()
        ):
            endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        if mock_stream_transport.__class__ in (StreamWriteTransport, StreamTransport):
            mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
            mock_stream_transport.send_all_from_iterable.assert_called_once_with(mocker.ANY, expected_send_timeout)
            mock_stream_transport.send_all.assert_not_called()
            mock_stream_transport.send.assert_not_called()
            assert chunks == [b"packet\n"]
        else:
            mock_stream_protocol.generate_chunks.assert_not_called()
            assert chunks == []

    @pytest.mark.parametrize("mock_stream_transport", [StreamWriteTransport], indirect=True)
    def test____send_packet____protocol_crashed(
        self,
        endpoint: StreamEndpoint[Any, Any],
        send_timeout: float | None,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it, timeout: chunks.extend(it)
        expected_error = Exception("Error")

        def side_effect(packet: Any) -> Generator[bytes, None, None]:
            raise expected_error
            yield  # type: ignore[unreachable]

        mock_stream_protocol.generate_chunks.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$") as exc_info:
            endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        assert chunks == []

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    def test____send_eof____default(
        self,
        transport_closed: bool,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closed.return_value = transport_closed

        # Act
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support sending EOF$")
            if mock_stream_transport.__class__ is not StreamTransport
            else contextlib.nullcontext()
        ):
            endpoint.send_eof()

        # Assert
        if mock_stream_transport.__class__ is StreamTransport:
            mock_stream_transport.send_eof.assert_called_once_with()
            with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
                endpoint.send_packet(mocker.sentinel.packet)
            mock_stream_protocol.generate_chunks.assert_not_called()
            mock_stream_transport.send_all_from_iterable.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    @pytest.mark.parametrize("mock_stream_transport", [StreamTransport], indirect=True)
    def test____send_eof____idempotent(
        self,
        transport_closed: bool,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closed.return_value = transport_closed
        endpoint.send_eof()

        # Act
        endpoint.send_eof()

        # Assert
        mock_stream_transport.send_eof.assert_called_once_with()
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            endpoint.send_packet(mocker.sentinel.packet)

    def test____recv_packet____blocking_or_not____receive_bytes_from_transport(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
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
            if mock_stream_transport.__class__ not in (StreamReadTransport, BufferedStreamReadTransport, StreamTransport)
            else contextlib.nullcontext()
        ):
            packet = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        if mock_stream_transport.__class__ is BufferedStreamReadTransport:
            if stream_protocol_mode == "buffer":
                mock_stream_transport.recv_into.assert_called_once_with(mocker.ANY, expected_recv_timeout)
                mock_stream_transport.recv.assert_not_called()
            else:
                mock_stream_transport.recv.assert_called_once_with(max_recv_size, expected_recv_timeout)
                mock_stream_transport.recv_into.assert_not_called()
        elif mock_stream_transport.__class__ in (StreamReadTransport, StreamTransport):
            mock_stream_transport.recv.assert_called_once_with(max_recv_size, expected_recv_timeout)
            assert packet is mocker.sentinel.packet
        else:
            assert packet is mocker.sentinel.packet_not_received

    @pytest.mark.parametrize("recv_timeout", [None, math.inf, 123456789], indirect=True)  # Do not test with timeout==0
    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    def test____recv_packet____blocking____partial_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert mock_stream_transport.recv.call_args_list == [mocker.call(max_recv_size, expected_recv_timeout) for _ in range(2)]
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [None, math.inf, 123456789], indirect=True)  # Do not test with timeout==0
    @pytest.mark.parametrize("mock_stream_transport", [BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking____partial_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"pac", b"ket\n"])

        # Act
        packet: Any = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert mock_stream_transport.recv_into.call_args_list == [
            mocker.call(mocker.ANY, expected_recv_timeout) for _ in range(2)
        ]
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [0], indirect=True)  # Only test with timeout==0
    @pytest.mark.parametrize(
        "max_recv_size",
        [
            pytest.param(3, id="chunk_matching_bufsize"),
            pytest.param(1024, id="chunk_not_matching_bufsize"),
        ],
        indirect=True,
    )
    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    def test____recv_packet____non_blocking____partial_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"pac", b"ket", b"\n"]

        # Act & Assert
        if max_recv_size == 3:
            packet: Any = endpoint.recv_packet(timeout=recv_timeout)

            assert mock_stream_transport.recv.call_args_list == [
                mocker.call(max_recv_size, expected_recv_timeout) for _ in range(3)
            ]
            assert packet is mocker.sentinel.packet
        else:
            with pytest.raises(TimeoutError):
                endpoint.recv_packet(timeout=recv_timeout)

            mock_stream_transport.recv.assert_called_once_with(max_recv_size, expected_recv_timeout)

    @pytest.mark.parametrize("recv_timeout", [0], indirect=True)  # Only test with timeout==0
    @pytest.mark.parametrize(
        "max_recv_size",
        [
            pytest.param(3, id="chunk_matching_bufsize"),
            pytest.param(1024, id="chunk_not_matching_bufsize"),
        ],
        indirect=True,
    )
    @pytest.mark.parametrize("mock_stream_transport", [BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____non_blocking____partial_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"pac", b"ket", b"\n"])

        # Act & Assert
        if max_recv_size == 3:
            packet: Any = endpoint.recv_packet(timeout=recv_timeout)

            assert mock_stream_transport.recv_into.call_args_list == [
                mocker.call(mocker.ANY, expected_recv_timeout) for _ in range(3)
            ]
            assert packet is mocker.sentinel.packet
        else:
            with pytest.raises(TimeoutError):
                endpoint.recv_packet(timeout=recv_timeout)

            mock_stream_transport.recv_into.assert_called_once_with(mocker.ANY, expected_recv_timeout)

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    def test____recv_packet____blocking_or_not____extra_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = endpoint.recv_packet(timeout=recv_timeout)
        packet_2: Any = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv.assert_called_once()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.parametrize("mock_stream_transport", [BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking_or_not____extra_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\npacket_2\n"])

        # Act
        packet_1: Any = endpoint.recv_packet(timeout=recv_timeout)
        packet_2: Any = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv_into.assert_called_once()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    def test____recv_packet____blocking_or_not____eof_error(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv.assert_called_once()

    @pytest.mark.parametrize("mock_stream_transport", [BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking_or_not____eof_error(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv_into.assert_called_once()

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    def test____recv_packet____blocking_or_not____protocol_parse_error(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
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
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("mock_stream_transport", [BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking_or_not____protocol_parse_error(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
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
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    def test____recv_packet____blocking_or_not____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]
        expected_error = Exception("Error")

        if before_transport_reading:
            endpoint.recv_packet()

        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_stream_protocol.build_packet_from_chunks.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_chunks\(\) crashed$") as exc_info:
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.__cause__ is expected_error

    @pytest.mark.parametrize("mock_stream_transport", [BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    def test____recv_packet____buffered____blocking_or_not____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\n", b"packet_2\n"])
        expected_error = Exception("Error")

        if before_transport_reading:
            endpoint.recv_packet()

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_buffered_stream_receiver.build_packet_from_buffer.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.__cause__ is expected_error

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    def test____special_case____recv_packet____blocking_or_not____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        mock_stream_transport.recv.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv.assert_not_called()

    @pytest.mark.parametrize("mock_stream_transport", [BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____special_case____recv_packet____buffered____blocking_or_not____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        mock_stream_transport.recv_into.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv_into.assert_not_called()

    # NOTE: The cases where recv_packet() uses transport.recv() or transport.recv_into() when manual_buffer_allocation == "try"
    #       are implicitly tested above, because this is the default behavior.

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport, BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____manual_buffer_allocation____try____but_stream_protocol_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with warnings.catch_warnings():
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            endpoint = StreamEndpoint[Any, Any](
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="try",
            )

        endpoint.close()

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____manual_buffer_allocation____try____but_stream_transport_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.warns(
            ManualBufferAllocationWarning,
            match=r'^The transport implementation .+ does not implement BufferedStreamReadTransport interface\. Consider explicitly setting the "manual_buffer_allocation" strategy to "no"\.$',
        ):
            endpoint = StreamEndpoint[Any, Any](
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="try",
            )

        endpoint.close()

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport, BufferedStreamReadTransport], indirect=True)
    def test____manual_buffer_allocation____disabled(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        # Act
        endpoint: StreamEndpoint[Any, Any]
        with warnings.catch_warnings():
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            endpoint = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="no")
        packet = endpoint.recv_packet()
        endpoint.close()

        # Assert
        mock_stream_transport.recv.assert_called_once_with(max_recv_size, math.inf)
        if hasattr(mock_stream_transport, "recv_into"):
            mock_stream_transport.recv_into.assert_not_called()
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport, BufferedStreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____manual_buffer_allocation____force____but_stream_protocol_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with (
            pytest.raises(UnsupportedOperation, match=r"^This protocol does not support the buffer API$") as exc_info,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            _ = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="force")

        assert exc_info.value.__notes__ == [
            'Consider setting the "manual_buffer_allocation" strategy to "no"',
        ]

    @pytest.mark.parametrize("mock_stream_transport", [StreamReadTransport], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____manual_buffer_allocation____force____but_stream_transport_does_not_support_it(
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
                match=r"^The transport implementation .+ does not implement BufferedStreamReadTransport interface$",
            ) as exc_info,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            _ = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size, manual_buffer_allocation="force")

        assert exc_info.value.__notes__ == [
            'Consider setting the "manual_buffer_allocation" strategy to "no"',
        ]
