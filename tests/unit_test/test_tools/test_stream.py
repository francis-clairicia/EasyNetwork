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
    @pytest.fixture(params=["data", "buffer"])
    @staticmethod
    def mock_stream_protocol(
        request: pytest.FixtureRequest,
        mock_stream_protocol: MagicMock,
        mock_buffered_stream_protocol: MagicMock,
    ) -> MagicMock:
        match request.param:
            case "data":
                return mock_stream_protocol
            case "buffer":
                return mock_buffered_stream_protocol
            case _:
                pytest.fail(f"Invalid param: {request.param}")

    @pytest.fixture
    @staticmethod
    def producer(mock_stream_protocol: MagicMock) -> StreamDataProducer[Any]:
        return StreamDataProducer(mock_stream_protocol)

    def test____dunder_init____invalid_protocol(self, mock_serializer: MagicMock) -> None:
        # Arrange
        from easynetwork.protocol import DatagramProtocol

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = StreamDataProducer(DatagramProtocol(mock_serializer))  # type: ignore[arg-type]

    def test____generate____yield_generator_chunk(
        self,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes]:
            yield b"chunk 1"
            yield b"chunk 2"

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect

        # Act
        chunks: list[bytes] = list(producer.generate(mocker.sentinel.packet))

        # Assert
        mock_generate_chunks_func.assert_called_once_with(mocker.sentinel.packet)
        assert chunks == [b"chunk 1", b"chunk 2"]

    @pytest.mark.parametrize("before_yielding", [False, True], ids=lambda p: f"before_yielding=={p}")
    def test____generate____generator_raised(
        self,
        before_yielding: bool,
        producer: StreamDataProducer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_error = Exception("Error")

        def side_effect(_: Any) -> Generator[bytes]:
            if before_yielding:
                raise expected_error
            yield b"chunk"
            raise expected_error

        mock_generate_chunks_func: MagicMock = mock_stream_protocol.generate_chunks
        mock_generate_chunks_func.side_effect = side_effect
        generator = producer.generate(mocker.sentinel.packet_for_test_arrange)

        if not before_yielding:
            next(generator)

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.generate_chunks\(\) crashed$") as exc_info:
            next(generator)

        # Assert
        assert exc_info.value.__cause__ is expected_error


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

    def test____next____no_buffer(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks

        # Act
        with pytest.raises(StopIteration):
            consumer.next(None)

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

        # Act
        packet = consumer.next(b"Hello")

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert packet is mocker.sentinel.packet
        assert consumer.get_buffer().tobytes() == b"World"

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
        with pytest.raises(StopIteration):
            consumer.next(b"Hello")
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert consumer.get_buffer().tobytes() == b""

        mock_build_packet_from_chunks_func.reset_mock()
        packet = consumer.next(b"World")
        mock_build_packet_from_chunks_func.assert_not_called()
        assert packet is mocker.sentinel.packet
        assert consumer.get_buffer().tobytes() == b"Bye"

    @pytest.mark.parametrize("sent_buffer", [None, b"", b"Hello"], ids=repr)
    def test____next____reuse_previously_returned_buffer(
        self,
        sent_buffer: bytes | None,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def setup_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert data == b"Hello"
            return mocker.sentinel.packet, b"World"

        def test_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            if sent_buffer is None:
                assert data == b"World"
            else:
                assert data == b"World" + sent_buffer
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_chunks_func: MagicMock = mock_stream_protocol.build_packet_from_chunks
        mock_build_packet_from_chunks_func.side_effect = setup_side_effect
        assert consumer.next(b"Hello") is mocker.sentinel.packet
        assert consumer.get_buffer().tobytes() == b"World"
        mock_build_packet_from_chunks_func.reset_mock()
        mock_build_packet_from_chunks_func.side_effect = test_side_effect

        # Act
        packet = consumer.next(sent_buffer)

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert packet is mocker.sentinel.packet
        assert consumer.get_buffer().tobytes() == b"Bye"

    @pytest.mark.parametrize("buffer", [None, b""], ids=repr)
    def test____next____ignore_empty_buffer(
        self,
        buffer: bytes | None,
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
        with pytest.raises(StopIteration):
            consumer.next(b"Hello")
        assert consumer.get_buffer().tobytes() == b""
        rest_checkpoint.assert_not_called()

        # Act
        with pytest.raises(StopIteration):
            consumer.next(buffer)

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

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            consumer.next(b"Hello")
        exception = exc_info.value

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert consumer.get_buffer().tobytes() == b"World"
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

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_chunks\(\) did not yield$"):
            consumer.next(b"Hello")

        # Assert
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert consumer.get_buffer().tobytes() == b"Hello"

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

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_chunks\(\) crashed$") as exc_info:
            consumer.next(b"Hello")

        # Assert
        assert exc_info.value.__cause__ is expected_error

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
        with pytest.raises(StopIteration):
            consumer.next(b"Hello")
        generator_exit_checkpoint.assert_not_called()

        # Act
        consumer.clear()

        # Assert
        generator_exit_checkpoint.assert_called_once_with()
        assert consumer.get_buffer().tobytes() == b""


class TestBufferedStreamDataConsumer:
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
    def consumer(mock_buffered_stream_protocol: MagicMock, sizehint: int) -> BufferedStreamDataConsumer[Any]:
        return BufferedStreamDataConsumer(mock_buffered_stream_protocol, sizehint)

    @staticmethod
    def write_in_consumer(
        consumer: BufferedStreamDataConsumer[Any],
        data: bytes | bytearray | memoryview,
        start_idx: int = 0,
    ) -> int:
        nbytes = len(data)
        with consumer.get_write_buffer()[start_idx:] as buffer:
            buffer[:nbytes] = data
        return nbytes

    def test____dunder_init____invalid_protocol(self, mock_serializer: MagicMock, sizehint: int) -> None:
        # Arrange
        from easynetwork.protocol import DatagramProtocol

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a BufferedStreamProtocol object, got .*$"):
            _ = BufferedStreamDataConsumer(DatagramProtocol(mock_serializer), sizehint)  # type: ignore[arg-type]

    @pytest.mark.parametrize("sizehint", [-1, 0])
    def test____dunder_init____invalid_sizehint(self, mock_buffered_stream_protocol: MagicMock, sizehint: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=rf"^buffer_size_hint={sizehint}$"):
            _ = BufferedStreamDataConsumer(mock_buffered_stream_protocol, sizehint)

    def test____get_write_buffer____protocol_create_buffer_validation____readonly_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_buffered_stream_protocol.create_buffer.side_effect = [b"read-only buffer"]

        # Act & Assert
        with pytest.raises(ValueError, match=r"^protocol\.create_buffer\(\) returned a read-only buffer$"):
            _ = consumer.get_write_buffer()

        mock_buffered_stream_protocol.build_packet_from_buffer.assert_not_called()
        assert consumer.get_value() is None

    def test____get_write_buffer____protocol_create_buffer_validation____empty_byte_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_buffered_stream_protocol.create_buffer.side_effect = [bytearray()]

        # Act & Assert
        with pytest.raises(ValueError, match=r"^protocol\.create_buffer\(\) returned a null buffer$"):
            _ = consumer.get_write_buffer()

        mock_buffered_stream_protocol.build_packet_from_buffer.assert_not_called()
        assert consumer.get_value() is None

    def test____get_write_buffer____buffer_start_set_to_end(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield len(buffer)
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^The start position is set to the end of the buffer$"):
            consumer.get_write_buffer()

    def test____next____error_negative_nbytes(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield 0
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        consumer.get_write_buffer()

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^Invalid value given$"):
            consumer.next(-1)

    def test____next____get_buffer_not_called(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield 0
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        # consumer.get_write_buffer()

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^next\(\) has been called whilst get_write_buffer\(\) was never called$"):
            consumer.next(4)

    def test____next____nbytes_too_big(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield -10
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        assert len(consumer.get_write_buffer()) == 10

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^Invalid value given$"):
            consumer.next(12)

    def test____next____no_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_buffered_stream_protocol.create_buffer.assert_not_called()
        mock_buffered_stream_protocol.build_packet_from_buffer.assert_not_called()
        assert consumer.buffer_size == 0
        assert consumer.get_value() is None

        # Act
        with pytest.raises(StopIteration):
            consumer.next(None)

        # Assert
        mock_buffered_stream_protocol.create_buffer.assert_not_called()
        mock_buffered_stream_protocol.build_packet_from_buffer.assert_not_called()

    @pytest.mark.parametrize("remainder_type", ["buffer_view", "external"])
    def test____next____oneshot(
        self,
        remainder_type: Literal["buffer_view", "external"],
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            data = buffer[:nbytes]
            assert data.tobytes() == b"Hello world"
            match remainder_type:
                case "buffer_view":
                    return mocker.sentinel.packet, buffer[nbytes:nbytes]
                case "external":
                    return mocker.sentinel.packet, b""
                case _:
                    assert_never(remainder_type)

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        assert consumer.get_value() is None
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello world")
        assert consumer.buffer_size > 0
        assert consumer.get_value() == b""
        mock_build_packet_from_buffer_func.reset_mock()

        # Act
        packet = consumer.next(nb_updated_bytes)

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
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            data = buffer[:nbytes]
            assert data.tobytes() == b"Hello world"
            match remainder_type:
                case "buffer_view":
                    return mocker.sentinel.packet, buffer[6:nbytes]
                case "external":
                    return mocker.sentinel.packet, b"world"
                case _:
                    assert_never(remainder_type)

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        assert consumer.get_value() is None
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello world")
        assert consumer.buffer_size > 0
        assert consumer.get_value() == b""

        # Act
        packet = consumer.next(nb_updated_bytes)

        # Assert
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"world"

    def test____next____remainder_buffer_overlapping(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            for i in range(buffer.nbytes):
                buffer[i] = 0
            nbytes = yield zero_or_none
            assert bytes(buffer[:nbytes]) == b"Hello world"
            return mocker.sentinel.packet, buffer[2:nbytes]

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello world")

        # Act
        packet = consumer.next(nb_updated_bytes)

        # Assert
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"llo world"

    def test____next____several_attempts(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert bytes(buffer[:nbytes]) == b"Hello"
            nbytes = yield zero_or_none
            assert bytes(buffer[:nbytes]) == b"World"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello")
        mock_build_packet_from_buffer_func.assert_called_once_with(mocker.ANY)
        with pytest.raises(StopIteration):
            consumer.next(nb_updated_bytes)
        assert consumer.get_value() == b""

        mock_build_packet_from_buffer_func.reset_mock()
        nb_updated_bytes = self.write_in_consumer(consumer, b"")
        with pytest.raises(StopIteration):
            consumer.next(nb_updated_bytes)
        mock_build_packet_from_buffer_func.assert_not_called()
        assert consumer.get_value() == b""

        mock_build_packet_from_buffer_func.reset_mock()
        nb_updated_bytes = self.write_in_consumer(consumer, b"World")
        mock_build_packet_from_buffer_func.assert_not_called()
        packet = consumer.next(nb_updated_bytes)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"Bye"

    def test____next____move_buffer_start_after_updating_it(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert bytes(buffer[:nbytes]) == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act
        nb_updated_bytes = 0
        nb_updated_bytes += self.write_in_consumer(consumer, b"Hello", nb_updated_bytes)
        nb_updated_bytes += self.write_in_consumer(consumer, b"World", nb_updated_bytes)
        assert consumer.get_value() == b""
        mock_build_packet_from_buffer_func.assert_called_once_with(mocker.ANY)
        packet = consumer.next(nb_updated_bytes)

        # Assert
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"Bye"

    def test____next____move_buffer_start_in_case_of_remainder(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def setup_side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert bytes(buffer[:nbytes]) == b"Hello"
            return mocker.sentinel.packet_in_setup, b"World"

        def test_side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert bytes(buffer[:nbytes]) == b"WorldHello"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = setup_side_effect
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello")
        mock_build_packet_from_buffer_func.reset_mock()
        mock_build_packet_from_buffer_func.side_effect = test_side_effect
        packet = consumer.next(nb_updated_bytes)
        assert packet is mocker.sentinel.packet_in_setup
        assert consumer.get_value() == b"World"

        # Act
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello")
        packet = consumer.next(nb_updated_bytes)

        # Assert
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"Bye"

    def test____next____buffer_start_on_first_yield(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            buffer[:5] = b"Hello"
            nbytes = yield 5
            assert bytes(buffer[: 5 + nbytes]) == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        consumer.get_write_buffer()
        assert consumer.get_value() == b"Hello"
        nb_updated_bytes = self.write_in_consumer(consumer, b"World")
        assert consumer.get_value() == b"Hello"
        packet = consumer.next(nb_updated_bytes)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"HelloBye"

    def test____next____buffer_start_on_first_yield____several_writes(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            buffer[:5] = b"Hello"
            nbytes = yield 5
            assert bytes(buffer[: 5 + nbytes]) == b"HelloWorld!"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        consumer.get_write_buffer()
        assert consumer.get_value() == b"Hello"
        nb_updated_bytes = 0
        nb_updated_bytes += self.write_in_consumer(consumer, b"World", nb_updated_bytes)
        nb_updated_bytes += self.write_in_consumer(consumer, b"!", nb_updated_bytes)
        assert consumer.get_value() == b"Hello"
        packet = consumer.next(nb_updated_bytes)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"HelloBye"

    def test____next____buffer_start_on_subsequent_yields(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield 0
            assert bytes(buffer[:nbytes]) == b"Hello"
            nbytes += yield nbytes
            assert bytes(buffer[:nbytes]) == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello")
        with pytest.raises(StopIteration):
            consumer.next(nb_updated_bytes)
        nb_updated_bytes = self.write_in_consumer(consumer, b"World")
        packet = consumer.next(nb_updated_bytes)
        assert packet is mocker.sentinel.packet
        assert consumer.get_value() == b"Bye"

    def test____next____negative_buffer_start(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield -10
            assert nbytes == 5
            assert bytes(buffer[-10:-5]) == b"Hello"
            nbytes = yield -5
            assert nbytes == 5
            assert bytes(buffer[-5:]) == b"World"
            assert bytes(buffer[-10:]) == b"HelloWorld"
            return mocker.sentinel.packet, b"Bye"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello")
        with pytest.raises(StopIteration):
            consumer.next(nb_updated_bytes)
        nb_updated_bytes = self.write_in_consumer(consumer, b"World")
        packet = consumer.next(nb_updated_bytes)
        assert packet is mocker.sentinel.packet
        full_buffer_value = consumer.get_value(full=True)
        truncated_buffer_value = consumer.get_value(full=False)
        assert full_buffer_value is not None and truncated_buffer_value is not None
        assert bytes(full_buffer_value[-10:-7]) == b"Bye"
        assert truncated_buffer_value.endswith(b"Bye")

    def test____next____not_a_byte_buffer(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
        sizehint: int,
    ) -> None:
        # Arrange
        from array import array

        itemsize = struct.calcsize("@I")

        mock_buffered_stream_protocol.create_buffer.side_effect = lambda sizehint: array(
            "I", itertools.repeat(0, sizehint // itemsize)
        )

        def side_effect(buffer: array[int]) -> Generator[int, int, tuple[Any, bytes]]:
            nbytes = yield 0
            assert nbytes == itemsize
            nbytes = yield 1 * itemsize
            assert nbytes == itemsize
            return (buffer[0], buffer[1]), b""

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        buffer = consumer.get_write_buffer()
        assert buffer.format == "B"
        assert buffer.itemsize == 1
        assert buffer.nbytes == sizehint
        assert consumer.buffer_size == sizehint
        nb_updated_bytes = self.write_in_consumer(consumer, struct.pack("@I", 42))
        with pytest.raises(StopIteration):
            consumer.next(nb_updated_bytes)
        nb_updated_bytes = self.write_in_consumer(consumer, struct.pack("@I", 987))
        packet = consumer.next(nb_updated_bytes)
        assert isinstance(packet, tuple)
        assert packet == (42, 987)

    @pytest.mark.parametrize("remainder_type", ["buffer_view", "external"])
    def test____next____protocol_parse_error(
        self,
        remainder_type: Literal["buffer_view", "external"],
        consumer: BufferedStreamDataConsumer[Any],
        zero_or_none: int | None,
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int | None, int, tuple[Any, ReadableBuffer]]:
            nbytes = yield zero_or_none
            assert bytes(buffer[:nbytes]) == b"Hello world"
            match remainder_type:
                case "buffer_view":
                    raise StreamProtocolParseError(buffer[6:nbytes], IncrementalDeserializeError("Error occurred", b""))
                case "external":
                    raise StreamProtocolParseError(b"world", IncrementalDeserializeError("Error occurred", b""))
                case _:
                    assert_never(remainder_type)

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello world")

        # Act
        with pytest.raises(StreamProtocolParseError) as exc_info:
            consumer.next(nb_updated_bytes)
        exception = exc_info.value

        # Assert
        assert consumer.get_value() == b"world"
        assert bytes(exception.remaining_data) == b"world"

    def test____next____generator_did_not_yield(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            if False:
                yield  # type: ignore[unreachable]
            return 42, b"42"

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) did not yield$"):
            self.write_in_consumer(consumer, b"Hello")

        with pytest.raises(StopIteration):
            consumer.next(None)

        # Assert
        assert consumer.get_value() == b""

    @pytest.mark.parametrize("before_yielding", [False, True], ids=lambda p: f"before_yielding=={p}")
    def test____next____generator_raised(
        self,
        before_yielding: bool,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        expected_error = Exception("Error")

        def side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            if before_yielding:
                raise expected_error
            yield
            raise expected_error

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect

        # Act & Assert
        if before_yielding:
            with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
                self.write_in_consumer(consumer, b"Hello")

            assert consumer.get_value() is None

            with pytest.raises(StopIteration):
                consumer.next(None)

        else:
            nb_updated_bytes = self.write_in_consumer(consumer, b"Hello")

            with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_buffer\(\) crashed$") as exc_info:
                consumer.next(nb_updated_bytes)

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
        mock_buffered_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(buffer: memoryview) -> Generator[int, int, tuple[Any, bytes]]:
            yield 0
            pytest.fail("Should not arrive here")

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        self.write_in_consumer(consumer, b"Hello world")

        # Act
        consumer.clear()

        # Assert
        assert consumer.get_value() is None

    def test____clear____close_current_generator(
        self,
        consumer: BufferedStreamDataConsumer[Any],
        mock_buffered_stream_protocol: MagicMock,
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

        mock_build_packet_from_buffer_func: MagicMock = mock_buffered_stream_protocol.build_packet_from_buffer
        mock_build_packet_from_buffer_func.side_effect = side_effect
        nb_updated_bytes = self.write_in_consumer(consumer, b"Hello")
        with pytest.raises(StopIteration):
            consumer.next(nb_updated_bytes)
        self.write_in_consumer(consumer, b"World")
        generator_exit_checkpoint.assert_not_called()

        # Act
        consumer.clear()

        # Assert
        generator_exit_checkpoint.assert_called_once_with()
        assert consumer.get_value() is None
