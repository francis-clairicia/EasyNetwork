# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generator

from easynetwork.tools.stream import StreamDataConsumer, StreamDataProducer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamDataProducer:
    @pytest.fixture
    @staticmethod
    def producer(mock_stream_protocol: MagicMock) -> StreamDataProducer[Any]:
        return StreamDataProducer(mock_stream_protocol)

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
        producer.queue(mocker.sentinel.packet)

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
        producer.queue(mocker.sentinel.packet)

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
        producer.queue(mocker.sentinel.packet)

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
        producer.queue(mocker.sentinel.packet_for_test_arrange, mocker.sentinel.second_packet)
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
        producer.queue(mocker.sentinel.packet_for_test_arrange)
        next(producer)
        mock_generate_chunks_func.reset_mock()  # Needed to call assert_not_called() later

        # Act
        with pytest.raises(StopIteration):
            _ = next(producer)

        # Assert
        mock_generate_chunks_func.assert_not_called()

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
        producer.queue(mocker.sentinel.packet)

        # Act & Assert
        assert producer.pending_packets()
        next(producer)
        assert producer.pending_packets()
        next(producer)
        assert producer.pending_packets()  # Generator still alive
        with pytest.raises(StopIteration):
            next(producer)
        assert not producer.pending_packets()

    def test____queue____no_args(self, producer: StreamDataProducer[Any]) -> None:
        # Arrange

        # Act
        producer.queue()

        # Assert
        ## There is no exceptions ? Nice !


class TestStreamDataConsumer:
    @pytest.fixture
    @staticmethod
    def consumer(mock_stream_protocol: MagicMock) -> StreamDataConsumer[Any]:
        return StreamDataConsumer(mock_stream_protocol)

    def test____dunder_iter____return_self(self, consumer: StreamDataConsumer[Any]) -> None:
        # Arrange

        # Act
        iterator = iter(consumer)

        # Assert
        assert iterator is consumer

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
        assert consumer.get_unconsumed_data() == b"Hello"
        with pytest.raises(StopIteration):
            next(consumer)
        mock_build_packet_from_chunks_func.assert_called_once_with()
        assert not consumer.get_buffer()
        assert consumer.get_unconsumed_data() == b"Hello"

        mock_build_packet_from_chunks_func.reset_mock()
        consumer.feed(b"World")
        assert consumer.get_unconsumed_data() == b"HelloWorld"
        packet = next(consumer)
        mock_build_packet_from_chunks_func.assert_not_called()
        assert packet is mocker.sentinel.packet
        assert consumer.get_buffer() == b"Bye"
        assert consumer.get_unconsumed_data() == b"Bye"

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

    def test____next____protocol_parse_error(
        self,
        consumer: StreamDataConsumer[Any],
        mock_stream_protocol: MagicMock,
    ) -> None:
        # Arrange
        from easynetwork.protocol import StreamProtocolParseError

        def side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            data = yield
            assert data == b"Hello"
            raise StreamProtocolParseError(b"World", "deserialization", "Error occured")

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
        assert exception.remaining_data == b""

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
