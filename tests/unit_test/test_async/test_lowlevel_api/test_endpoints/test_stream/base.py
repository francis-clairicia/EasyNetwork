from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest

from ....._utils import make_async_recv_into_side_effect as make_recv_into_side_effect
from .....base import BaseTestWithStreamProtocol
from .._interfaces import HaveBackend, SupportsClosing, SupportsReceiving, SupportsSending

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class BaseAsyncEndpointTests(BaseTestWithStreamProtocol):
    @pytest.mark.parametrize("transport_closed", [False, True])
    async def test____is_closing____default(
        self,
        endpoint: SupportsClosing,
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

    async def test____aclose____default(
        self,
        endpoint: SupportsClosing,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.aclose.assert_not_called()

        # Act
        await endpoint.aclose()

        # Assert
        mock_stream_transport.aclose.assert_awaited_once_with()

    async def test____extra_attributes____default(
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

    async def test____get_backend____returns_inner_transport_backend(
        self,
        endpoint: HaveBackend,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert endpoint.backend() is mock_stream_transport.backend()


class BaseAsyncEndpointSendTests(BaseAsyncEndpointTests):
    async def test____send_packet____send_bytes_to_transport(
        self,
        endpoint: SupportsSending,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it: chunks.extend(it)

        # Act
        await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_awaited_once_with(mocker.ANY)
        mock_stream_transport.send_all.assert_not_called()
        assert chunks == [b"packet\n"]

    async def test____send_packet____protocol_crashed(
        self,
        endpoint: SupportsSending,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it: chunks.extend(it)
        expected_error = Exception("Error")

        def side_effect(packet: Any) -> Generator[bytes]:
            raise expected_error
            yield  # type: ignore[unreachable]

        mock_stream_protocol.generate_chunks.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$") as exc_info:
            await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        assert chunks == []


class BaseAsyncEndpointReceiveTests(BaseAsyncEndpointTests):
    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int:
        return getattr(request, "param", 256 * 1024)

    async def test____recv_packet____receive_bytes_from_transport(
        self,
        endpoint: SupportsReceiving,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])

        # Act
        packet = await endpoint.recv_packet()

        # Assert
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.assert_awaited_once_with(mocker.ANY)
            mock_stream_transport.recv.assert_not_called()
        else:
            mock_stream_transport.recv.assert_awaited_once_with(max_recv_size)
            mock_stream_transport.recv_into.assert_not_called()
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____recv_packet____partial_data(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____partial_data(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____recv_packet____extra_data(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____extra_data(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____recv_packet____eof_error(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_awaited_once()

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____eof_error(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv_into.assert_awaited_once()

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____recv_packet____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____recv_packet____buffered____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
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
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    async def test____recv_packet____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: SupportsReceiving,
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

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    async def test____recv_packet____buffered____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\n", b"packet_2\n"])
        expected_error = Exception("Error")

        if before_transport_reading:
            await endpoint.recv_packet()

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            yield
            raise expected_error

        mock_stream_protocol.build_packet_from_buffer.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value.__cause__ is expected_error

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    async def test____special_case____recv_packet____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()

        mock_stream_transport.recv.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv.assert_not_called()

    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    async def test____special_case____recv_packet____buffered____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()

        mock_stream_transport.recv_into.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()

        # Assert
        mock_stream_transport.recv_into.assert_not_called()
