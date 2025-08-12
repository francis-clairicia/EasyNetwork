from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

import pytest

from ....._utils import (
    make_async_recv_into_side_effect as make_recv_into_side_effect,
    make_async_recv_with_ancillary_into_side_effect as make_recv_with_ancillary_into_side_effect,
)
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

    async def test____send_packet_with_ancillary____send_bytes_to_transport(
        self,
        endpoint: SupportsSending,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_with_ancillary.side_effect = lambda it, ancdata: chunks.extend(it)

        # Act
        await endpoint.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_with_ancillary.assert_awaited_once_with(mocker.ANY, mocker.sentinel.ancdata)
        mock_stream_transport.send_all_from_iterable.assert_not_called()
        mock_stream_transport.send_all.assert_not_called()
        assert chunks == [b"packet\n"]

    async def test____send_packet_with_ancillary____protocol_crashed(
        self,
        endpoint: SupportsSending,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_with_ancillary.side_effect = lambda it, ancdata: chunks.extend(it)
        expected_error = Exception("Error")

        def side_effect(packet: Any) -> Generator[bytes]:
            raise expected_error
            yield  # type: ignore[unreachable]

        mock_stream_protocol.generate_chunks.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$") as exc_info:
            await endpoint.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        assert chunks == []


class BaseAsyncEndpointReceiveTests(BaseAsyncEndpointTests):
    @pytest.fixture
    @staticmethod
    def max_recv_size(request: Any) -> int:
        return getattr(request, "param", 256 * 1024)

    @pytest.fixture
    @staticmethod
    def ancillary_data_received(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=lambda ancdata, /: None, return_value=None)

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

    async def test____recv_packet____partial_data(
        self,
        endpoint: SupportsReceiving,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"pac", b"ket\n"])
        else:
            mock_stream_transport.recv.side_effect = [b"pac", b"ket\n"]

        # Act
        packet: Any = await endpoint.recv_packet()

        # Assert
        if stream_protocol_mode == "buffer":
            assert mock_stream_transport.recv_into.await_args_list == [mocker.call(mocker.ANY) for _ in range(2)]
        else:
            assert mock_stream_transport.recv.await_args_list == [mocker.call(max_recv_size) for _ in range(2)]
        assert packet is mocker.sentinel.packet

    async def test____recv_packet____extra_data(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\npacket_2\n"])
        else:
            mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]

        # Act
        packet_1: Any = await endpoint.recv_packet()
        packet_2: Any = await endpoint.recv_packet()

        # Assert
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.assert_awaited_once()
        else:
            mock_stream_transport.recv.assert_awaited_once()
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    async def test____recv_packet____eof_error(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])
        else:
            mock_stream_transport.recv.side_effect = [b""]

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()

        # Assert
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.assert_awaited_once()
        else:
            mock_stream_transport.recv.assert_awaited_once()

    async def test____recv_packet____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet\n"])
        else:
            mock_stream_transport.recv.side_effect = [b"packet\n"]
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Error", b""))

        if stream_protocol_mode == "buffer":

            def build_packet_from_buffer_side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
                yield
                raise expected_error

            mock_stream_protocol.build_packet_from_buffer.side_effect = build_packet_from_buffer_side_effect

        else:

            def build_packet_from_chunks_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
                yield
                raise expected_error

            mock_stream_protocol.build_packet_from_chunks.side_effect = build_packet_from_chunks_side_effect

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    async def test____recv_packet____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b"packet_1\n", b"packet_2\n"])
        else:
            mock_stream_transport.recv.side_effect = [b"packet_1\npacket_2\n"]
        expected_error = Exception("Error")

        if before_transport_reading:
            await endpoint.recv_packet()

        if stream_protocol_mode == "buffer":

            def build_packet_from_buffer_side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
                if not before_transport_reading:
                    yield
                raise expected_error

            mock_stream_protocol.build_packet_from_buffer.side_effect = build_packet_from_buffer_side_effect

            expected_runtime_error = r"^protocol\.build_packet_from_buffer\(\) crashed$"
        else:

            def build_packet_from_chunks_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
                if not before_transport_reading:
                    yield
                raise expected_error

            mock_stream_protocol.build_packet_from_chunks.side_effect = build_packet_from_chunks_side_effect

            expected_runtime_error = r"^protocol\.build_packet_from_chunks\(\) crashed$"

        # Act
        with pytest.raises(RuntimeError, match=expected_runtime_error) as exc_info:
            _ = await endpoint.recv_packet()

        # Assert
        assert exc_info.value.__cause__ is expected_error

    async def test____recv_packet_with_ancillary____receive_bytes_from_transport(
        self,
        endpoint: SupportsReceiving,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        ancillary_data_received: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv_with_ancillary.side_effect = [(b"packet\n", mocker.sentinel.ancdata)]
        mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect(
            [(b"packet\n", mocker.sentinel.ancdata)]
        )

        # Act
        packet = await endpoint.recv_packet_with_ancillary(
            ancillary_bufsize=1024,
            ancillary_data_received=ancillary_data_received,
        )

        # Assert
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.assert_awaited_once_with(mocker.ANY, 1024)
            mock_stream_transport.recv_with_ancillary.assert_not_called()
        else:
            mock_stream_transport.recv_with_ancillary.assert_awaited_once_with(max_recv_size, 1024)
            mock_stream_transport.recv_with_ancillary_into.assert_not_called()

        assert packet is mocker.sentinel.packet
        ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)

    async def test____recv_packet_with_ancillary____partial_data(
        self,
        endpoint: SupportsReceiving,
        max_recv_size: int,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        ancillary_data_received: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect(
                [(b"pac", mocker.sentinel.ancdata), (b"ket\n", None)]
            )
        else:
            mock_stream_transport.recv_with_ancillary.side_effect = [(b"pac", mocker.sentinel.ancdata), (b"ket\n", None)]

        # Act & Assert
        with pytest.raises(EOFError, match=r"^Received partial packet data$"):
            await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.assert_awaited_once_with(mocker.ANY, 1024)
        else:
            mock_stream_transport.recv_with_ancillary.assert_awaited_once_with(max_recv_size, 1024)
        ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)

    async def test____recv_packet_with_ancillary____extra_data(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        ancillary_data_received: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect(
                [(b"packet_1\npacket_2\n", mocker.sentinel.ancdata)]
            )
        else:
            mock_stream_transport.recv_with_ancillary.side_effect = [(b"packet_1\npacket_2\n", mocker.sentinel.ancdata)]

        # Act
        packet_1: Any = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)
        packet_2: Any = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        # Assert
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.assert_awaited_once()
        else:
            mock_stream_transport.recv_with_ancillary.assert_awaited_once()
        ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)
        assert packet_1 is mocker.sentinel.packet_1
        assert packet_2 is mocker.sentinel.packet_2

    async def test____recv_packet_with_ancillary____eof_error(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        ancillary_data_received: MagicMock,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect([(b"", None)])
        else:
            mock_stream_transport.recv_with_ancillary.side_effect = [(b"", None)]

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        # Assert
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.assert_awaited_once()
        else:
            mock_stream_transport.recv_with_ancillary.assert_awaited_once()
        ancillary_data_received.assert_not_called()

    async def test____recv_packet_with_ancillary____protocol_parse_error(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        ancillary_data_received: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect(
                [(b"packet\n", mocker.sentinel.ancdata)]
            )
        else:
            mock_stream_transport.recv_with_ancillary.side_effect = [(b"packet\n", mocker.sentinel.ancdata)]
        expected_error = StreamProtocolParseError(b"", IncrementalDeserializeError("Error", b""))

        if stream_protocol_mode == "buffer":

            def build_packet_from_buffer_side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
                yield
                raise expected_error

            mock_stream_protocol.build_packet_from_buffer.side_effect = build_packet_from_buffer_side_effect

        else:

            def build_packet_from_chunks_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
                yield
                raise expected_error

            mock_stream_protocol.build_packet_from_chunks.side_effect = build_packet_from_chunks_side_effect

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            _ = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        # Assert
        assert exc_info.value is expected_error
        ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)

    @pytest.mark.parametrize("before_transport_reading", [False, True], ids=lambda p: f"before_transport_reading=={p}")
    async def test____recv_packet_with_ancillary____protocol_crashed(
        self,
        before_transport_reading: bool,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        ancillary_data_received: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect(
                [(b"packet_1\n", mocker.sentinel.ancdata), (b"packet_2\n", mocker.sentinel.ancdata)]
            )
        else:
            mock_stream_transport.recv_with_ancillary.side_effect = [(b"packet_1\npacket_2\n", mocker.sentinel.ancdata)]
        expected_error = Exception("Error")

        if before_transport_reading:
            await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)
            ancillary_data_received.reset_mock()

        if stream_protocol_mode == "buffer":

            def build_packet_from_buffer_side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
                if not before_transport_reading:
                    yield
                raise expected_error

            mock_stream_protocol.build_packet_from_buffer.side_effect = build_packet_from_buffer_side_effect

            expected_runtime_error = r"^protocol\.build_packet_from_buffer\(\) crashed$"
        else:

            def build_packet_from_chunks_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
                if not before_transport_reading:
                    yield
                raise expected_error

            mock_stream_protocol.build_packet_from_chunks.side_effect = build_packet_from_chunks_side_effect

            expected_runtime_error = r"^protocol\.build_packet_from_chunks\(\) crashed$"

        # Act
        with pytest.raises(RuntimeError, match=expected_runtime_error) as exc_info:
            _ = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        if before_transport_reading:
            ancillary_data_received.assert_not_called()
        else:
            ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)

    async def test____recv_packet_with_ancillary____ancillary_data_received_callback_crashed(
        self,
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        stream_protocol_mode: Literal["data", "buffer"],
        ancillary_data_received: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if stream_protocol_mode == "buffer":
            mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect(
                [(b"packet\n", mocker.sentinel.ancdata)]
            )
        else:
            mock_stream_transport.recv_with_ancillary.side_effect = [(b"packet\n", mocker.sentinel.ancdata)]
        ancillary_data_received.side_effect = expected_error = Exception("Error")

        if stream_protocol_mode == "buffer":

            def build_packet_from_buffer_side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
                yield
                pytest.fail("nbytes sent")

            mock_stream_protocol.build_packet_from_buffer.side_effect = build_packet_from_buffer_side_effect
        else:

            def build_packet_from_chunks_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
                yield
                pytest.fail("bytes sent")

            mock_stream_protocol.build_packet_from_chunks.side_effect = build_packet_from_chunks_side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^ancillary_data_received\(\) crashed$") as exc_info:
            _ = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        # Assert
        assert exc_info.value.__cause__ is expected_error

    @pytest.mark.parametrize("recv_method_name", ["recv_packet", "recv_packet_with_ancillary"])
    async def test____special_case____recv_packet____eof_error____do_not_try_socket_recv_on_next_call(
        self,
        recv_method_name: Literal["recv_packet", "recv_packet_with_ancillary"],
        endpoint: SupportsReceiving,
        mock_stream_transport: MagicMock,
        ancillary_data_received: MagicMock,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b""]
        mock_stream_transport.recv_into.side_effect = make_recv_into_side_effect([b""])
        mock_stream_transport.recv_with_ancillary.side_effect = [(b"", None)]
        mock_stream_transport.recv_with_ancillary_into.side_effect = make_recv_with_ancillary_into_side_effect([(b"", None)])
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            match recv_method_name:
                case "recv_packet":
                    _ = await endpoint.recv_packet()
                case "recv_packet_with_ancillary":
                    _ = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        mock_stream_transport.recv.reset_mock()
        mock_stream_transport.recv_into.reset_mock()
        mock_stream_transport.recv_with_ancillary.reset_mock()
        mock_stream_transport.recv_with_ancillary_into.reset_mock()

        # Act
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet()
        with pytest.raises(ConnectionAbortedError, match=r" \(end-of-stream\)$"):
            _ = await endpoint.recv_packet_with_ancillary(1024, ancillary_data_received)

        # Assert
        mock_stream_transport.recv.assert_not_called()
        mock_stream_transport.recv_with_ancillary.assert_not_called()
        ancillary_data_received.assert_not_called()
