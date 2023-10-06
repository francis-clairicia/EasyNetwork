from __future__ import annotations

import math
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from easynetwork.api_sync.lowlevel.endpoints.stream import StreamEndpoint
from easynetwork.api_sync.lowlevel.transports.abc import StreamTransport
from easynetwork.tools._stream import StreamDataConsumer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamEndpoint:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_time_perfcounter(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("time.perf_counter", autospec=True, return_value=12345)

    @pytest.fixture
    @staticmethod
    def consumer_feed(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(StreamDataConsumer, "feed", autospec=True, side_effect=StreamDataConsumer.feed)

    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mocker: MockerFixture) -> MagicMock:
        mock_stream_transport = mocker.NonCallableMagicMock(spec=StreamTransport)
        mock_stream_transport.is_closed.return_value = False

        def close_side_effect() -> None:
            mock_stream_transport.is_closed.return_value = True

        mock_stream_transport.close.side_effect = close_side_effect
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
    ) -> StreamEndpoint[Any, Any]:
        return StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

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

    @pytest.mark.parametrize("max_recv_size", [1, 2**64], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____max_recv_size____valid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act
        transport: StreamEndpoint[Any, Any] = StreamEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

        # Assert
        assert transport.max_recv_size == max_recv_size

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

    @pytest.mark.parametrize("transport_closed", [False, True])
    def test___is_closed____default(
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

    def test___close____default(self, endpoint: StreamEndpoint[Any, Any], mock_stream_transport: MagicMock) -> None:
        # Arrange
        mock_stream_transport.close.assert_not_called()

        # Act
        endpoint.close()

        # Assert
        mock_stream_transport.close.assert_called_once_with()

    def test____get_extra_info____default(
        self,
        endpoint: StreamEndpoint[Any, Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.get_extra_info.return_value = mocker.sentinel.extra_info

        # Act
        value = endpoint.get_extra_info(mocker.sentinel.name, default=mocker.sentinel.default)

        # Assert
        mock_stream_transport.get_extra_info.assert_called_once_with(mocker.sentinel.name, default=mocker.sentinel.default)
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
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it, timeout: chunks.extend(it)

        # Act
        endpoint.send_packet(mocker.sentinel.packet, timeout=send_timeout)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_called_once_with(mocker.ANY, expected_send_timeout)
        assert chunks == [b"packet\n"]

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
        endpoint.send_eof()

        # Assert
        if transport_closed:
            mock_stream_transport.send_eof.assert_not_called()
        else:
            mock_stream_transport.send_eof.assert_called_once_with()
        with pytest.raises(RuntimeError, match=r"^send_eof\(\) has been called earlier$"):
            endpoint.send_packet(mocker.sentinel.packet)
        mock_stream_protocol.generate_chunks.assert_not_called()
        mock_stream_transport.send_all_from_iterable.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
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
        if transport_closed:
            mock_stream_transport.send_eof.assert_not_called()
        else:
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
        consumer_feed: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        # Act
        packet: Any = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv.assert_called_once_with(max_recv_size, expected_recv_timeout)
        consumer_feed.assert_called_once_with(mocker.ANY, b"packet\n")
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("recv_timeout", [None, math.inf, 123456789], indirect=True)  # Do not test with timeout==0
    def test____recv_packet____blocking____partial_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        assert mock_stream_transport.recv.call_args_list == [mocker.call(max_recv_size, expected_recv_timeout) for _ in range(2)]
        assert consumer_feed.call_args_list == [
            mocker.call(mocker.ANY, b"pac"),
            mocker.call(mocker.ANY, b"ket\n"),
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
    def test____recv_packet_____non_blocking____partial_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        expected_recv_timeout: float,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
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
            assert consumer_feed.call_args_list == [
                mocker.call(mocker.ANY, b"pac"),
                mocker.call(mocker.ANY, b"ket"),
                mocker.call(mocker.ANY, b"\n"),
            ]
            assert packet is mocker.sentinel.packet
        else:
            with pytest.raises(TimeoutError):
                endpoint.recv_packet(timeout=recv_timeout)

            mock_stream_transport.recv.assert_called_once_with(max_recv_size, expected_recv_timeout)
            consumer_feed.assert_called_once_with(mocker.ANY, b"pac")

    def test____recv_packet____blocking_or_not____extra_data(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = endpoint.recv_packet(timeout=recv_timeout)
        packet_2: Any = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv.assert_called_once()
        consumer_feed.assert_called_once_with(mocker.ANY, b"packet_1\npacket_2\n")
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    def test____recv_packet____blocking_or_not____eof_error____default(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]

        # Act
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv.assert_called_once()
        consumer_feed.assert_not_called()

    def test____special_case____recv_packet____blocking_or_not____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: StreamEndpoint[Any, Any],
        recv_timeout: float | None,
        mock_stream_transport: MagicMock,
        consumer_feed: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        mock_stream_transport.recv.reset_mock()

        # Act
        with pytest.raises(EOFError, match=r"^end-of-stream$"):
            _ = endpoint.recv_packet(timeout=recv_timeout)

        # Assert
        mock_stream_transport.recv.assert_not_called()
