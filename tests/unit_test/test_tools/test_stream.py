from __future__ import annotations

import itertools
import struct
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Literal, assert_never

from easynetwork.exceptions import IncrementalDeserializeError, StreamProtocolParseError
from easynetwork.lowlevel._stream import BufferedStreamDataConsumer, StreamDataConsumer, StreamDataProducer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture


class TestStreamDataProducer:
    @pytest.fixture
    @staticmethod
    def producer(mock_stream_protocol: MagicMock) -> StreamDataProducer[Any]:
        return StreamDataProducer(mock_stream_protocol)

    def test____dunder_init____invalid_protocol(self, mock_serializer: MagicMock) -> None:
        # Arrange
        from easynetwork.protocol import DatagramProtocol

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = StreamDataProducer(DatagramProtocol(mock_serializer))  # type: ignore[arg-type]

    def test____dunder_iter____return_self(self, producer: StreamDataProducer[Any]) -> None:
        # Arrange

        # Act
        iterator = iter(producer)

        # Assert
        assert iterator is producer

    def test____next____no_packets(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks

        # Act
        with pytest.raises(StopIteration):
            _ = next(producer)

        # Assert
        mock_generate_chunks_func.assert_not_called()

    def test____next____return_one_generator_chunk(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes, None, None]:
            yield b"chunk"
            yield b"never yielded"

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet)

        # Act
        chunk: bytes = next(producer)

        # Assert
        mock_generate_chunks_func.assert_called_once_with(mocker.sentinel.packet)
        assert chunk == b"chunk"

    def test____next____reuse_generator(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes, None, None]:
            yield b"chunk"
            yield b"2nd chunk"

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet)

        # Act
        chunk: bytes = next(producer)
        second_chunk: bytes = next(producer)

        # Assert
        mock_generate_chunks_func.assert_called_once_with(mocker.sentinel.packet)
        assert chunk == b"chunk"
        assert second_chunk == b"2nd chunk"

    def test____next____ignore_empty_yielded_bytes(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes, None, None]:
            yield b""
            yield b"2nd chunk"

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet)

        # Act
        chunk: bytes = next(producer)

        # Assert
        mock_generate_chunks_func.assert_called_once_with(mocker.sentinel.packet)
        assert chunk == b"2nd chunk"

    def test____next____go_to_next_queued_packet_if_actual_generator_is_exhausted(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes, None, None]:
            yield b"chunk"

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet_for_test_arrange, mocker.sentinel.second_packet)
        next(producer)
        mock_generate_chunks_func.reset_mock()  # Needed to call assert_called_once() later

        # Act
        chunk: bytes = next(producer)

        # Assert
        mock_generate_chunks_func.assert_called_once_with(mocker.sentinel.second_packet)
        assert chunk == b"chunk"

    def test____next____actual_generator_is_exhausted_and_there_is_no_queued_packet(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes, None, None]:
            yield b"chunk"

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet_for_test_arrange)
        next(producer)
        mock_generate_chunks_func.reset_mock()  # Needed to call assert_not_called() later

        # Act
        with pytest.raises(StopIteration):
            _ = next(producer)

        # Assert
        mock_generate_chunks_func.assert_not_called()

    def test____next____convert_bytearrays(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes, None, None]:
            yield bytearray(b"chunk")

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet_for_test_arrange)

        # Act
        chunk = next(producer)

        # Assert
        assert isinstance(chunk, bytes)
        assert chunk == b"chunk"

    @pytest.mark.parametrize("before_yielding", [False, True], ids=lambda p: f"before_yielding=={p}")
    def test____next____generator_raised(
        self,
        before_yielding: bool,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_error = Exception("Error")

        def side_effect(_: Any) -> Generator[bytes, None, None]:
            if before_yielding:
                raise expected_error
            yield b"chunk"
            raise expected_error

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet_for_test_arrange)

        if not before_yielding:
            next(producer)

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$") as exc_info:
            next(producer)

        # Assert
        assert exc_info.value.__cause__ is expected_error

    def test____pending_packets____empty_producer(self, producer: StreamDataProducer[Any]) -> None:
        # Arrange

        # Act & Assert
        assert not producer.pending_packets()

    def test____pending_packets____queued_packet(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes, None, None]:
            yield b"chunk"
            yield b"2nd chunk"

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet)

        # Act & Assert
        assert producer.pending_packets()
        next(producer)
        assert producer.pending_packets()
        next(producer)
        assert producer.pending_packets()  # Generator still alive
        with pytest.raises(StopIteration):
            next(producer)
        assert not producer.pending_packets()

    def test____enqueue____no_args(self, producer: StreamDataProducer[Any]) -> None:
        # Arrange

        # Act
        producer.enqueue()

        # Assert
        ## There is no exceptions ? Nice !

    def test____clear____remove_queued_packets(
        self,
        producer: StreamDataProducer[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        producer.enqueue(mocker.sentinel.packet)
        assert producer.pending_packets()

        # Act
        producer.clear()

        # Assert
        assert not producer.pending_packets()
        with pytest.raises(StopIteration):
            next(producer)

    def test____clear____close_current_generator(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        generator_exit_checkpoint = mocker.stub()

        def side_effect(_: Any) -> Generator[bytes, None, None]:
            with pytest.raises(GeneratorExit) as exc_info:  # Exception raised in generator when calling generator.close()
                yield b"chunk"
            raise exc_info.value  # re-raise exception

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        producer.enqueue(mocker.sentinel.packet)
        assert next(producer) == b"chunk"
        assert producer.pending_packets()
        generator_exit_checkpoint.assert_not_called()

        # Act
        producer.clear()

        # Assert
        generator_exit_checkpoint.assert_not_called()
        assert not producer.pending_packets()
        with pytest.raises(StopIteration):
            next(producer)


class TestStreamDataConsumer:
    @pytest.fixture
    @staticmethod
    def consumer(mock_stream_protocol: MagicMock) -> StreamDataConsumer[Any]:
        return StreamDataConsumer(mock_stream_protocol)

    def test____dunder_init____invalid_protocol(self, mock_serializer: MagicMock) -> None:
        # Arrange
        from easynetwork.protocol import DatagramProtocol

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = StreamDataConsumer(DatagramProtocol(mock_serializer))  # type: ignore[arg-type]

    def test____dunder_iter____return_self(self, consumer: StreamDataConsumer[Any]) -> None:
        # Arrange

        # Act
        iterator = iter(consumer)

        # Assert
        assert iterator is consumer

    def test____feed____convert_bytearrays(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert isinstance(data, bytes)
            assert data == b"Hello"
            return mocker.sentinel.packet, bytearray(b"World")

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect
        consumer.feed(bytearray(b"Hello"))

        # Act
        packet = next(consumer)

        # Assert
        assert packet is mocker.sentinel.packet

    def test____next____no_buffer(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        consumer.feed(b"")  # 0 + 0 == 0

        # Act
        with pytest.raises(StopIteration):
            next(consumer)

        # Assert
        mock_build_packet_from_chunks_func.assert_not_called()

    def test____next____oneshot(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert data == b"Hello"
            return mocker.sentinel.packet, b"World"

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect
        consumer.feed(b"Hello")
        assert consumer.get_buffer() == b"Hello"

        # Act
        packet = next(consumer)

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert packet is mocker.sentinel.packet
        assert consumer.get_buffer() == b"World"

    def test____next____several_attempts(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert data == b"Hello"
            data = yield
            assert data == b"World"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect

        # Act & Assert
        consumer.feed(b"Hello")
        with pytest.raises(StopIteration):
            next(consumer)
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert consumer.get_buffer() == b""

        mock_build_packet_from_chunks_func.reset_mock()
        consumer.feed(b"World")
        packet = next(consumer)
        mock_build_packet_from_chunks_func.assert_not_called()
        assert packet is mocker.sentinel.packet
        assert consumer.get_buffer() == b"Bye"

    def test____next____concatenate_feed_buffer(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert data == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect

        # Act
        consumer.feed(b"Hello")
        consumer.feed(b"World")
        assert consumer.get_buffer() == b"HelloWorld"
        packet = next(consumer)

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert packet is mocker.sentinel.packet
        assert consumer.get_buffer() == b"Bye"

    def test____next____ignore_empty_buffer(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        rest_checkpoint = mocker.stub()

        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert data == b"Hello"
            rest = yield
            rest_checkpoint(rest)
            return mocker.sentinel.packet, b"World"

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect
        consumer.feed(b"Hello")
        with pytest.raises(StopIteration):
            next(consumer)
        assert consumer.get_buffer() == b""
        consumer.feed(b"")
        rest_checkpoint.assert_not_called()

        # Act
        with pytest.raises(StopIteration):
            next(consumer)

        # Assert
        rest_checkpoint.assert_not_called()

    def test____next____protocol_parse_error(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert data == b"Hello"
            raise StreamProtocolParseError(b"World", IncrementalDeserializeError("Error occurred", b""))

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect
        consumer.feed(b"Hello")
        assert consumer.get_buffer() == b"Hello"

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            next(consumer)
        exception = exc_info.value

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert consumer.get_buffer() == b"World"
        assert bytes(exception.remaining_data) == b"World"

    def test____next____generator_did_not_yield(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            if False:
                yield  # type: ignore[unreachable]
            return 42, b"42"

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect
        consumer.feed(b"Hello")
        assert consumer.get_buffer() == b"Hello"

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_chunks\(\) did not yield$"):
            next(consumer)

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert consumer.get_buffer() == b"Hello"

    @pytest.mark.parametrize("before_yielding", [False, True], ids=lambda p: f"before_yielding=={p}")
    def test____next____generator_raised(
        self,
        before_yielding: bool,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        expected_error = Exception("Error")

        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            if before_yielding:
                raise expected_error
            yield
            raise expected_error

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect
        consumer.feed(b"Hello")
        assert consumer.get_buffer() == b"Hello"

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_chunks\(\) crashed$") as exc_info:
            next(consumer)

        # Assert
        assert exc_info.value.__cause__ is expected_error

    def test____clear____flush_pending_buffer(self, consumer: StreamDataConsumer[Any]) -> None:
        # Arrange
        consumer.feed(b"Hello")
        assert consumer.get_buffer() == b"Hello"

        # Act
        consumer.clear()

        # Assert
        assert consumer.get_buffer() == b""

    def test____clear____close_current_generator(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        generator_exit_checkpoint = mocker.stub()

        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            assert (yield) == b"Hello"
            with pytest.raises(GeneratorExit) as exc_info:
                yield
            generator_exit_checkpoint()
            raise exc_info.value

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = side_effect
        consumer.feed(b"Hello")
        with pytest.raises(StopIteration):
            next(consumer)
        consumer.feed(b"World")
        assert consumer.get_buffer() == b"World"
        generator_exit_checkpoint.assert_not_called()

        # Act
        consumer.clear()

        # Assert
        generator_exit_checkpoint.assert_called_once_with()
        assert consumer.get_buffer() == b""


class TestBufferedStreamDataConsumer:
    @pytest.fixture
    @staticmethod
    def mock_stream_protocol(mock_stream_protocol: MagicMock, mock_buffered_stream_receiver: MagicMock) -> MagicMock:
        mock_stream_protocol.buffered_receiver.side_effect = None
        mock_stream_protocol.buffered_receiver.return_value = mock_buffered_stream_receiver
        return mock_stream_protocol

    @pytest.fixture
    @staticmethod
    def sizehint() -> int:
        return 1024

    @pytest.fixture(params=[None, 0], ids=lambda p: f"zero_or_none=={p}")
    @staticmethod
    def zero_or_none(request: pytest.FixtureRequest) -> int | None:
        return request.param

    @pytest.fixture
    @staticmethod
    def consumer(mock_stream_protocol: MagicMock, sizehint: int) -> BufferedStreamDataConsumer[Any]:
        return BufferedStreamDataConsumer(mock_stream_protocol, sizehint)

    @staticmethod
    def write_in_consumer(consumer: BufferedStreamDataConsumer[Any], data: bytes | bytearray | memoryview) -> None:
        nbytes = len(data)
        with memoryview(consumer.get_write_buffer()) as buffer:
            buffer[:nbytes] = data
        consumer.buffer_updated(nbytes)

    def test____dunder_init____invalid_protocol(self, mock_serializer: MagicMock, sizehint: int) -> None:
        # Arrange
        from easynetwork.protocol import DatagramProtocol

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = BufferedStreamDataConsumer(DatagramProtocol(mock_serializer), sizehint)  # type: ignore[arg-type]

    @pytest.mark.parametrize("sizehint", [-1, 0])
    def test____dunder_init____invalid_sizehint(self, mock_stream_protocol: MagicMock, sizehint: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=rf"^buffer_size_hint={sizehint}$"):
            _ = BufferedStreamDataConsumer(mock_stream_protocol, sizehint)

    def test____dunder_iter____return_self(self, consumer: BufferedStreamDataConsumer[Any]) -> None:
        # Arrange

        # Act
        iterator = iter(consumer)

        # Assert
        assert iterator is consumer

    def test____get_write_buffer____protocol_create_buffer_validation____readonly_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        mock_buffered_stream_receiver.create_buffer.side_effect = [b"read-only buffer"]

        # Act & Assert
        with pytest.raises(ValueError, match=r"^protocol\.create_buffer\(\) returned a read-only buffer$"):
            _ = consumer.get_write_buffer()

        mock_buffered_stream_receiver.build_packet_from_buffer.assert_not_called()
        assert consumer.get_value() is None

    def test____get_write_buffer____protocol_create_buffer_validation____empty_byte_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        mock_buffered_stream_receiver.create_buffer.side_effect = [bytearray()]

        # Act & Assert
        with pytest.raises(ValueError, match=r"^protocol\.create_buffer\(\) returned a null buffer$"):
            _ = consumer.get_write_buffer()

        mock_buffered_stream_receiver.build_packet_from_buffer.assert_not_called()
        assert consumer.get_value() is None

    def test____get_write_buffer____do_not_recompute_buffer_view(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield 0
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        assert consumer.get_write_buffer() is consumer.get_write_buffer()

    def test____get_write_buffer____buffer_start_set_to_end(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield len(buffer)
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^The start position is set to the end of the buffer$"):
            consumer.get_write_buffer()

    def test____buffer_updated____error_negative_nbytes(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield 0
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        consumer.get_write_buffer()

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Negative value given$"):
            consumer.buffer_updated(-1)

    def test____buffer_updated____get_buffer_not_called(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield 0
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        # consumer.get_write_buffer()

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^buffer_updated\(\) has been called whilst get_buffer\(\) was never called$"):
            consumer.buffer_updated(4)

    def test____buffer_updated____nbytes_too_big(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield -10
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        assert len(memoryview(consumer.get_write_buffer())) == 10

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^nbytes > buffer_view\.nbytes$"):
            consumer.buffer_updated(12)

    def test____next____no_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        mock_buffered_stream_receiver.create_buffer.assert_not_called()
        mock_buffered_stream_receiver.build_packet_from_buffer.assert_not_called()
        assert consumer.buffer_size == 0
        assert consumer.get_value() is None

        # Act
        with pytest.raises(StopIteration):
            next(consumer)

        # Assert
        mock_buffered_stream_receiver.create_buffer.assert_not_called()
        mock_buffered_stream_receiver.build_packet_from_buffer.assert_not_called()

    @pytest.mark.parametrize("remainder_type", ["buffer_view", "external"])
    def test____next____oneshot(
        self,
        remainder_type: Literal["buffer_view", "external"],
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            data = buffer[:nbytes]
            assert data == b"Hello world"
            match remainder_type:
                case "buffer_view":
                    return mocker.sentinel.packet, buffer[nbytes:nbytes]
                case "external":
                    return mocker.sentinel.packet, b""
                case _:
                    assert_never(remainder_type)

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        assert consumer.get_value() is None
        self.write_in_consumer(consumer, b"Hello world")
        assert consumer.buffer_size > 0
        assert consumer.get_value() == b"Hello world"
        mock_build_packet_from_buffer_func.reset_mock()

        # Act
        packet = next(consumer)

        # Assert
        assert packet is mocker.sentinel.packet
        mock_build_packet_from_buffer_func.assert_not_called()
        assert consumer.get_value() == b""

    @pytest.mark.parametrize("remainder_type", ["buffer_view", "external"])
    def test____next____with_remainder(
        self,
        remainder_type: Literal["buffer_view", "external"],
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            data = buffer[:nbytes]
            assert data == b"Hello world"
            match remainder_type:
                case "buffer_view":
                    return mocker.sentinel.packet, buffer[6:nbytes]
                case "external":
                    return mocker.sentinel.packet, b"world"
                case _:
                    assert_never(remainder_type)

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        assert consumer.get_value() is None
        self.write_in_consumer(consumer, b"Hello world")
        assert consumer.buffer_size > 0
        assert consumer.get_value() == b"Hello world"

        # Act
        packet = next(consumer)

        # Assert
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"world"

    def test____next____remainder_buffer_overlapping(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert buffer[:nbytes] == b"Hello world"
            return mocker.sentinel.packet, buffer[2:nbytes]

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        self.write_in_consumer(consumer, b"Hello world")

        # Act
        packet = next(consumer)

        # Assert
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"llo world"

    def test____next____several_attempts(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert buffer[:nbytes] == b"Hello"
            nbytes = yield zero_or_none
            assert buffer[:nbytes] == b"World"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        self.write_in_consumer(consumer, b"Hello")
        mock_build_packet_from_buffer_func.assert_called_once_with(mocker.ANY)
        with pytest.raises(StopIteration):
            next(consumer)
        assert consumer.get_value() == b""

        mock_build_packet_from_buffer_func.reset_mock()
        self.write_in_consumer(consumer, b"")
        with pytest.raises(StopIteration):
            next(consumer)
        mock_build_packet_from_buffer_func.assert_not_called()
        assert consumer.get_value() == b""

        mock_build_packet_from_buffer_func.reset_mock()
        self.write_in_consumer(consumer, b"World")
        mock_build_packet_from_buffer_func.assert_not_called()
        packet = next(consumer)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"Bye"

    def test____next____move_buffer_start_after_updating_it(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert buffer[:nbytes] == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act
        self.write_in_consumer(consumer, b"Hello")
        self.write_in_consumer(consumer, b"World")
        assert consumer.get_value() == b"HelloWorld"
        mock_build_packet_from_buffer_func.assert_called_once_with(mocker.ANY)
        packet = next(consumer)

        # Assert
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"Bye"

    def test____next____buffer_start_on_first_yield(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            buffer[:5] = b"Hello"
            nbytes = yield 5
            assert buffer[: 5 + nbytes] == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        consumer.get_write_buffer()
        assert consumer.get_value() == b"Hello"
        self.write_in_consumer(consumer, b"World")
        assert consumer.get_value() == b"HelloWorld"
        packet = next(consumer)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"HelloBye"

    def test____next____buffer_start_on_first_yield____several_writes(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            buffer[:5] = b"Hello"
            nbytes = yield 5
            assert buffer[: 5 + nbytes] == b"HelloWorld!"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        consumer.get_write_buffer()
        assert consumer.get_value() == b"Hello"
        self.write_in_consumer(consumer, b"World")
        self.write_in_consumer(consumer, b"!")
        assert consumer.get_value() == b"HelloWorld!"
        packet = next(consumer)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"HelloBye"

    def test____next____buffer_start_on_subsequent_yields(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield 0
            assert buffer[:nbytes] == b"Hello"
            nbytes += yield nbytes
            assert buffer[:nbytes] == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        self.write_in_consumer(consumer, b"Hello")
        with pytest.raises(StopIteration):
            next(consumer)
        self.write_in_consumer(consumer, b"World")
        packet = next(consumer)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"Bye"

    def test____next____negative_buffer_start(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield -10
            assert nbytes == 5
            assert buffer[-10:-5] == b"Hello"
            nbytes = yield -5
            assert nbytes == 5
            assert buffer[-5:] == b"World"
            assert buffer[-10:] == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        self.write_in_consumer(consumer, b"Hello")
        with pytest.raises(StopIteration):
            next(consumer)
        self.write_in_consumer(consumer, b"World")
        packet = next(consumer)
        assert packet is mocker.sentinel.packet
        full_buffer_value = consumer.get_value(full=True)
        truncated_buffer_value = consumer.get_value(full=False)
        assert full_buffer_value is not None and truncated_buffer_value is not None
        assert full_buffer_value[-10:-7] == b"Bye"
        assert truncated_buffer_value.endswith(b"Bye")

    def test____next____not_a_byte_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
        sizehint: int,
    ) -> None:
        # Arrange
        from array import array

        itemsize = struct.calcsize("@I")

        mock_buffered_stream_receiver.create_buffer.side_effect = lambda sizehint: array(
            "I", itertools.repeat(0, sizehint // itemsize)
        )

        def side_effect(buffer: array[int]) -> Generator[int, int, tuple[Any, bytes]]:
            nbytes = yield 0
            assert nbytes == itemsize
            nbytes = yield 1 * itemsize
            assert nbytes == itemsize
            return (buffer[0], buffer[1]), b""

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        buffer = consumer.get_write_buffer()
        assert memoryview(buffer).format == "B"
        assert memoryview(buffer).itemsize == 1
        assert memoryview(buffer).nbytes == sizehint
        assert consumer.buffer_size == sizehint
        self.write_in_consumer(consumer, struct.pack("@I", 42))
        with pytest.raises(StopIteration):
            next(consumer)
        self.write_in_consumer(consumer, struct.pack("@I", 987))
        packet = next(consumer)
        assert isinstance(packet, tuple)
        assert packet == (42, 987)

    @pytest.mark.parametrize("remainder_type", ["buffer_view", "external"])
    def test____next____protocol_parse_error(
        self,
        remainder_type: Literal["buffer_view", "external"],
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert buffer[:nbytes] == b"Hello world"
            match remainder_type:
                case "buffer_view":
                    raise StreamProtocolParseError(buffer[6:nbytes], IncrementalDeserializeError("Error occurred", b""))
                case "external":
                    raise StreamProtocolParseError(b"world", IncrementalDeserializeError("Error occurred", b""))
                case _:
                    assert_never(remainder_type)

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        self.write_in_consumer(consumer, b"Hello world")

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            next(consumer)
        exception = exc_info.value

        # Assert
        assert consumer.get_value() == b"world"
        assert bytes(exception.remaining_data) == b"world"

    def test____next____generator_did_not_yield(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            if False:
                yield  # type: ignore[unreachable]
            return 42, b"42"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) did not yield$"):
            self.write_in_consumer(consumer, b"Hello")

        with pytest.raises(StopIteration):
            next(consumer)

        # Assert
        assert consumer.get_value() == b""

    @pytest.mark.parametrize("before_yielding", [False, True], ids=lambda p: f"before_yielding=={p}")
    def test____next____generator_raised(
        self,
        before_yielding: bool,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        expected_error = Exception("Error")

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            if before_yielding:
                raise expected_error
            yield
            raise expected_error

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        if before_yielding:
            with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
                self.write_in_consumer(consumer, b"Hello")

            assert consumer.get_value() is None

            with pytest.raises(StopIteration):
                next(consumer)

        else:
            self.write_in_consumer(consumer, b"Hello")

            with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
                next(consumer)

            assert consumer.get_value() is None

        # Assert
        assert exc_info.value.__cause__ is expected_error

    def test____clear____never_used_consumer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
    ) -> None:
        # Arrange

        # Act
        consumer.clear()

        # Assert
        assert consumer.get_value() is None

    def test____clear____flush_pending_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield 0
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        self.write_in_consumer(consumer, b"Hello world")
        assert consumer.get_value() == b"Hello world"

        # Act
        consumer.clear()

        # Assert
        assert consumer.get_value() is None

    def test____clear____close_current_generator(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_receiver: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        generator_exit_checkpoint = mocker.stub()

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            yield
            with pytest.raises(GeneratorExit) as exc_info:
                yield
            generator_exit_checkpoint()
            raise exc_info.value

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_receiver.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        self.write_in_consumer(consumer, b"Hello")
        with pytest.raises(StopIteration):
            next(consumer)
        self.write_in_consumer(consumer, b"World")
        assert consumer.get_value() == b"World"
        generator_exit_checkpoint.assert_not_called()

        # Act
        consumer.clear()

        # Assert
        generator_exit_checkpoint.assert_called_once_with()
        assert consumer.get_value() is None
