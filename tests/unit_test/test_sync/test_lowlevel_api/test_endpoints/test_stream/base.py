from __future__ import annotations

import math
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest

from ....._utils import make_recv_into_side_effect
from .....base import BaseTestWithStreamProtocol
from .._interfaces import SupportsClosing, SupportsReceiving, SupportsSending

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BaseEndpointTests(BaseTestWithStreamProtocol):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_time_perfcounter(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("time.perf_counter", autospec=True, return_value=12345)

    @pytest.mark.parametrize("transport_closed", [False, True])
    def test____is_closed____default(
        self,
        endpoint: SupportsClosing,
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

    def test____close____default(
        self,
        endpoint: SupportsClosing,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.close.assert_not_called()

        # Act
        endpoint.close()

        # Assert
        mock_stream_transport.close.assert_called_once_with()

    def test____extra_attributes____default(
        self,
        endpoint: TypedAttributeProvider,
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = endpoint.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info


class BaseEndpointSendTests(BaseEndpointTests):
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

    def test____send_packet____send_bytes_to_transport(
        self,
        send_timeout: float | None,
        expected_send_timeout: float,
        endpoint: SupportsSending,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it, timeout: chunks.extend(it)

        # Act
        endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_called_once_with(mocker.ANY, expected_send_timeout)
        mock_stream_transport.send_all.assert_not_called()
        mock_stream_transport.send.assert_not_called()
        assert chunks == [b"packet\n"]

    def test____send_packet____protocol_crashed(
        self,
        endpoint: SupportsSending,
        send_timeout: float | None,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it, timeout: chunks.extend(it)
        expected_error = Exception("Error")

        def side_effect(packet: Any) -> Generator[bytes]:
            raise expected_error
            yield  # type: ignore[unreachable]

        mock_stream_protocol.generate_chunks.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$") as exc_info:
            endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        assert chunks == []


class BaseEndpointReceiveTests(BaseEndpointTests):
    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int:
        return getattr(request, "param", 256 * 1024)

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

    def test____recv_packet____blocking_or_not____receive_bytes_from_transport(
        self,
        endpoint: SupportsReceiving,
        recv_timeout: float | None,
        expected_recv_timeout: float,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])

        # Act
        packet = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.assert_called_once_with(mocker.ANY, expected_recv_timeout)
            mock_stream_transport.recv.assert_not_called()
        else:
            mock_stream_transport.recv.assert_called_once_with(max_recv_size, expected_recv_timeout)
            mock_stream_transport.recv_into.assert_not_called()

        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [None, math.inf, 123456789], indirect=True)  # Do not test with timeout==0
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____recv_packet____blocking____partial_data(
        self,
        endpoint: SupportsReceiving,
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
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking____partial_data(
        self,
        endpoint: SupportsReceiving,
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
    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____recv_packet____non_blocking____partial_data(
        self,
        endpoint: SupportsReceiving,
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
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____non_blocking____partial_data(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____recv_packet____blocking_or_not____extra_data(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking_or_not____extra_data(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____recv_packet____blocking_or_not____eof_error(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking_or_not____eof_error(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____recv_packet____blocking_or_not____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____recv_packet____buffered____blocking_or_not____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Error", b""))

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_stream_protocol.build_packet_from_buffer.side_effect = side_effect

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    def test____recv_packet____blocking_or_not____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    def test____recv_packet____buffered____blocking_or_not____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: SupportsReceiving,
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\n", b"packet_2\n"])
        expected_error = Exception("Error")

        if before_transport_reading:
            endpoint.recv_packet()

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_stream_protocol.build_packet_from_buffer.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert exc_info.value.__cause__ is expected_error

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____special_case____recv_packet____blocking_or_not____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____special_case____recv_packet____buffered____blocking_or_not____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: SupportsReceiving,
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
