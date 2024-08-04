from __future__ import annotations

import contextlib
import random
from collections.abc import Generator
from typing import IO, TYPE_CHECKING, Any, Literal, final

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError, LimitOverrunError
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer
from easynetwork.serializers.base_stream import (
    AutoSeparatedPacketSerializer,
    FileBasedPacketSerializer,
    FixedSizePacketSerializer,
)

import pytest

from ...tools import send_return, write_data_and_extra_in_buffer, write_in_buffer

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture


@final
class _IncrementalPacketSerializerForTest(AbstractIncrementalPacketSerializer[Any, Any]):
    def incremental_serialize(self, packet: Any) -> Generator[bytes]:
        raise NotImplementedError

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[Any, bytes]]:
        raise NotImplementedError


class TestAbstractIncrementalPacketSerializer:
    @pytest.fixture
    @staticmethod
    def mock_incremental_serialize_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_IncrementalPacketSerializerForTest, "incremental_serialize")

    @pytest.fixture
    @staticmethod
    def mock_incremental_deserialize_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_IncrementalPacketSerializerForTest, "incremental_deserialize")

    def test____serialize____concatenate_chunks(
        self,
        mock_incremental_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any) -> Generator[bytes]:
            yield b"a"
            yield b"b"
            yield b"c"

        serializer = _IncrementalPacketSerializerForTest()
        mock_incremental_serialize_func.side_effect = side_effect

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_incremental_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert isinstance(data, bytes)
        assert data == b"abc"

    def test____deserialize____expect_packet_with_one_chunk(
        self,
        mock_incremental_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _IncrementalPacketSerializerForTest()
        mock_consumer_generator: MagicMock = mock_incremental_deserialize_func.return_value
        mock_consumer_generator.__next__.return_value = None
        mock_consumer_generator.send.side_effect = [StopIteration((mocker.sentinel.packet, b""))]

        # Act
        packet = serializer.deserialize(mocker.sentinel.data)

        # Assert
        mock_incremental_deserialize_func.assert_called_once_with()
        mock_consumer_generator.__next__.assert_called_once_with()
        mock_consumer_generator.send.assert_called_once_with(mocker.sentinel.data)
        assert packet is mocker.sentinel.packet

    def test____deserialize____raise_error_if_data_is_missing(
        self,
        mock_incremental_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _IncrementalPacketSerializerForTest()
        mock_consumer_generator: MagicMock = mock_incremental_deserialize_func.return_value
        mock_consumer_generator.__next__.return_value = None
        mock_consumer_generator.send.side_effect = [None, StopIteration((mocker.sentinel.packet, b""))]

        # Act
        with pytest.raises(DeserializeError, match=r"^Missing data to create packet$"):
            _ = serializer.deserialize(mocker.sentinel.data)

        # Assert
        mock_incremental_deserialize_func.assert_called_once_with()
        mock_consumer_generator.__next__.assert_called_once_with()
        mock_consumer_generator.send.assert_called_once_with(mocker.sentinel.data)
        mock_consumer_generator.close.assert_called_once_with()  # Free-up resources by closing the generator

    def test____deserialize____raise_error_if_extra_data_is_present(
        self,
        mock_incremental_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _IncrementalPacketSerializerForTest()
        mock_consumer_generator: MagicMock = mock_incremental_deserialize_func.return_value
        mock_consumer_generator.__next__.return_value = None
        mock_consumer_generator.send.side_effect = StopIteration((mocker.sentinel.packet, b"extra"))

        # Act
        with pytest.raises(DeserializeError, match=r"^Extra data caught$") as exc_info:
            _ = serializer.deserialize(mocker.sentinel.data)

        # Assert
        mock_incremental_deserialize_func.assert_called_once_with()
        mock_consumer_generator.__next__.assert_called_once_with()
        mock_consumer_generator.send.assert_called_once_with(mocker.sentinel.data)
        assert exc_info.value.error_info == {"packet": mocker.sentinel.packet, "extra": b"extra"}

    def test____deserialize____consumer_did_not_yield(
        self,
        mock_incremental_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _IncrementalPacketSerializerForTest()
        mock_consumer_generator: MagicMock = mock_incremental_deserialize_func.return_value
        mock_consumer_generator.__next__.side_effect = StopIteration

        # Act
        with pytest.raises(RuntimeError, match=r"^self.incremental_deserialize\(\) generator did not yield$"):
            _ = serializer.deserialize(mocker.sentinel.data)

        # Assert
        mock_incremental_deserialize_func.assert_called_once_with()
        mock_consumer_generator.__next__.assert_called_once_with()
        mock_consumer_generator.send.assert_not_called()


class _AutoSeparatedPacketSerializerForTest(AutoSeparatedPacketSerializer[Any, Any]):
    def serialize(self, packet: Any) -> bytes:
        raise NotImplementedError

    def deserialize(self, data: bytes) -> Any:
        raise NotImplementedError


class TestAutoSeparatedPacketSerializer:
    @pytest.fixture
    @staticmethod
    def mock_serialize_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_AutoSeparatedPacketSerializerForTest, "serialize")

    @pytest.fixture
    @staticmethod
    def mock_deserialize_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_AutoSeparatedPacketSerializerForTest, "deserialize")

    @pytest.fixture(params=[False, True], ids=lambda p: f"check_separator=={p}")
    @staticmethod
    def check_separator(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param")

    @pytest.fixture(params=["data", "buffer"])
    @staticmethod
    def incremental_deserialize_mode(request: pytest.FixtureRequest) -> str:
        assert request.param in ("data", "buffer")
        return request.param

    @pytest.mark.parametrize("separator", [b"\n", b".", b"\r\n", b"--"], ids=lambda p: f"separator=={p}")
    def test____properties____right_values(self, separator: bytes, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer = _AutoSeparatedPacketSerializerForTest(separator=separator, debug=debug_mode, limit=123456789)

        # Assert
        assert serializer.separator == separator
        assert serializer.debug is debug_mode
        assert serializer.buffer_limit == 123456789

    def test____dunder_init____empty_separator_bytes(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Empty separator$"):
            _ = _AutoSeparatedPacketSerializerForTest(b"")

    @pytest.mark.parametrize("limit", [0, -42], ids=lambda p: f"limit=={p}")
    def test____dunder_init____invalid_limit(self, limit: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^limit must be a positive integer$"):
            _ = _AutoSeparatedPacketSerializerForTest(b"\n", limit=limit)

    def test____incremental_serialize____empty_bytes(
        self,
        check_separator: bool,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(
            separator=b"\r\n",
            incremental_serialize_check_separator=check_separator,
        )
        mock_serialize_func.return_value = b""

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == []

    def test____incremental_serialize____append_separator(
        self,
        check_separator: bool,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(
            separator=b"\r\n",
            incremental_serialize_check_separator=check_separator,
        )
        mock_serialize_func.return_value = b"data"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\n"]

    def test____incremental_serialize____keep_already_present_separator(
        self,
        check_separator: bool,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(
            separator=b"\r\n",
            incremental_serialize_check_separator=check_separator,
        )
        mock_serialize_func.return_value = b"data\r\n"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\n"]

    def test____incremental_serialize____remove_useless_trailing_separators(
        self,
        check_separator: bool,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(
            separator=b"\r\n",
            incremental_serialize_check_separator=check_separator,
        )
        mock_serialize_func.return_value = b"data\r\n\r\n\r\n\r\n"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\n" if check_separator else b"data\r\n\r\n\r\n\r\n"]

    def test____incremental_serialize____does_not_remove_partial_separator_at_end(
        self,
        check_separator: bool,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(
            separator=b"\r\n",
            incremental_serialize_check_separator=check_separator,
        )
        mock_serialize_func.return_value = b"data\r\r\n"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\r\n" if check_separator else b"data\r\r\n"]

    def test____incremental_serialize____error_if_separator_is_within_output(
        self,
        check_separator: bool,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(
            separator=b"\r\n",
            incremental_serialize_check_separator=check_separator,
        )
        mock_serialize_func.return_value = b"data\r\nother"

        # Act & Assert
        with (
            pytest.raises(
                ValueError,
                match=r"^b'[\\]r[\\]n' separator found in serialized packet sentinel\.packet which was not at the end$",
            )
            if check_separator
            else contextlib.nullcontext()
        ):
            list(serializer.incremental_serialize(mocker.sentinel.packet))

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    def test____incremental_deserialize____one_shot_chunk(
        self,
        expected_remaining_data: bytes,
        mock_deserialize_func: MagicMock,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_deserialize_func.return_value = mocker.sentinel.packet
        data_to_test: bytes = b"data\r\n"

        # Act
        sent_data = data_to_test + expected_remaining_data
        remaining_data: ReadableBuffer
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                packet, remaining_data = send_return(data_consumer, sent_data)
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                start_pos = next(buffered_consumer)
                packet, remaining_data = send_return(buffered_consumer, write_in_buffer(buffer, sent_data, start_pos=start_pos))
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        mock_deserialize_func.assert_called_once_with(b"data")
        assert bytes(remaining_data) == expected_remaining_data
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    def test____incremental_deserialize____several_chunks(
        self,
        expected_remaining_data: bytes,
        mock_deserialize_func: MagicMock,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_deserialize_func.return_value = mocker.sentinel.packet

        # Act
        remaining_data: ReadableBuffer
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                data_consumer.send(b"data\r")
                packet, remaining_data = send_return(data_consumer, b"\n" + expected_remaining_data)
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                start_pos = next(buffered_consumer)
                start_pos = buffered_consumer.send(write_in_buffer(buffer, b"data\r", start_pos=start_pos))
                packet, remaining_data = send_return(
                    buffered_consumer,
                    write_in_buffer(
                        buffer,
                        b"\n" + expected_remaining_data,
                        start_pos=start_pos,
                    ),
                )
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        mock_deserialize_func.assert_called_once_with(b"data")
        assert bytes(remaining_data) == expected_remaining_data
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    def test____incremental_deserialize____translate_deserialize_errors(
        self,
        expected_remaining_data: bytes,
        mock_deserialize_func: MagicMock,
        incremental_deserialize_mode: Literal["data", "buffer"],
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n", debug=debug_mode)
        mock_deserialize_func.side_effect = DeserializeError("Bad news", error_info=mocker.sentinel.error_info)

        # Act
        sent_data = b"data\r\n" + expected_remaining_data
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    send_return(data_consumer, sent_data)
                exception = exc_info.value
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                start_pos = next(buffered_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    send_return(buffered_consumer, write_in_buffer(buffer, sent_data, start_pos=start_pos))
                exception = exc_info.value
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        mock_deserialize_func.assert_called_once_with(b"data")
        assert exception.__cause__ is mock_deserialize_func.side_effect
        assert bytes(exception.remaining_data) == expected_remaining_data
        assert exception.error_info is mocker.sentinel.error_info

    @pytest.mark.parametrize("separator_found", [False, True], ids=lambda p: f"separator_found=={p}")
    def test____incremental_deserialize____reached_limit(
        self,
        separator_found: bool,
        mock_deserialize_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n", limit=1, debug=debug_mode)
        mock_deserialize_func.return_value = mocker.sentinel.packet
        data_to_test: bytes = b"data"
        if separator_found:
            data_to_test += b"\r\n"

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(data_to_test)

        # Assert
        mock_deserialize_func.assert_not_called()
        if separator_found:
            assert str(exc_info.value) == "Separator is found, but chunk is longer than limit"
        else:
            assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
        assert bytes(exc_info.value.remaining_data) == b""
        assert exc_info.value.error_info is None

    @pytest.mark.parametrize("separator_found", [False, True], ids=lambda p: f"separator_found=={p}")
    def test____incremental_deserialize____reached_limit____separator_partially_received(
        self,
        separator_found: bool,
        mock_deserialize_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n", limit=1, debug=debug_mode)
        mock_deserialize_func.return_value = mocker.sentinel.packet
        data_to_test: bytes = b"data\r"
        if separator_found:
            data_to_test += b"\n"

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(data_to_test)

        # Assert
        mock_deserialize_func.assert_not_called()
        if separator_found:
            assert str(exc_info.value) == "Separator is found, but chunk is longer than limit"
            assert bytes(exc_info.value.remaining_data) == b""
        else:
            assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
            assert bytes(exc_info.value.remaining_data) == b"\r"
        assert exc_info.value.error_info is None

    def test____buffered_incremental_deserialize____reached_limit(
        self,
        mock_deserialize_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n", limit=1024, debug=debug_mode)
        mock_deserialize_func.return_value = mocker.sentinel.packet
        data_to_test: bytes = b"X" * 1023

        # Act
        buffer = serializer.create_deserializer_buffer(1024)
        consumer = serializer.buffered_incremental_deserialize(buffer)
        start_pos = next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(write_in_buffer(buffer, data_to_test, start_pos=start_pos))

        # Assert
        mock_deserialize_func.assert_not_called()
        assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
        assert bytes(exc_info.value.remaining_data) == b""
        assert exc_info.value.error_info is None

    def test____buffered_incremental_deserialize____reached_limit____separator_partially_received(
        self,
        mock_deserialize_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n", limit=1024, debug=debug_mode)
        mock_deserialize_func.return_value = mocker.sentinel.packet
        data_to_test: bytes = b"X" * 1023 + b"\r"

        # Act
        buffer = serializer.create_deserializer_buffer(1024)
        consumer = serializer.buffered_incremental_deserialize(buffer)
        start_pos = next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(write_in_buffer(buffer, data_to_test, start_pos=start_pos))

        # Assert
        mock_deserialize_func.assert_not_called()
        assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
        assert bytes(exc_info.value.remaining_data) == b"\r"
        assert exc_info.value.error_info is None


class _FixedSizePacketSerializerForTest(FixedSizePacketSerializer[Any, Any]):
    def serialize(self, packet: Any) -> bytes:
        raise NotImplementedError

    def deserialize(self, data: bytes) -> Any:
        raise NotImplementedError


class TestFixedSizePacketSerializer:
    @pytest.fixture(params=[1, 10, 65536], ids=lambda p: f"packet_size=={p}")
    @staticmethod
    def packet_size(request: Any) -> int:
        return request.param

    @pytest.fixture
    @staticmethod
    def mock_serialize_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_FixedSizePacketSerializerForTest, "serialize")

    @pytest.fixture
    @staticmethod
    def mock_deserialize_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_FixedSizePacketSerializerForTest, "deserialize")

    def test____properties____right_values(self, packet_size: int, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer = _FixedSizePacketSerializerForTest(packet_size, debug=debug_mode)

        # Assert
        assert serializer.packet_size == packet_size
        assert serializer.debug is debug_mode

    @pytest.mark.parametrize(
        "packet_size",
        [
            pytest.param(0, id="null value"),
            pytest.param(-1, id="negative value"),
        ],
        indirect=True,
    )
    def test____dunder_init____invalid_packet_size(self, packet_size: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^size must be a positive integer$"):
            _ = _FixedSizePacketSerializerForTest(packet_size)

    def test____incremental_serialize____yields_given_data(
        self,
        packet_size: int,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
        packet_data: bytes = random.randbytes(packet_size)
        mock_serialize_func.return_value = packet_data

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [packet_data]

    @pytest.mark.parametrize("offset", [1, -1], ids=lambda i: f"(size{i:+})")
    def test____incremental_serialize____check_output_size(
        self,
        offset: int,
        packet_size: int,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
        packet_data: bytes = random.randbytes(packet_size + offset)
        mock_serialize_func.return_value = packet_data

        # Act & Assert
        with pytest.raises(ValueError, match=r"^serialized data size does not meet expectation$"):
            list(serializer.incremental_serialize(mocker.sentinel.packet))

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
        ],
    )
    def test____incremental_deserialize____one_shot_chunk(
        self,
        expected_remaining_data: bytes,
        packet_size: int,
        mock_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
        packet_data: bytes = random.randbytes(packet_size)
        mock_deserialize_func.return_value = mocker.sentinel.packet

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        packet, remaining_data = send_return(consumer, packet_data + expected_remaining_data)

        # Assert
        mock_deserialize_func.assert_called_once_with(packet_data)
        assert packet is mocker.sentinel.packet
        assert remaining_data == expected_remaining_data

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
        ],
    )
    def test____incremental_deserialize____several_chunks(
        self,
        expected_remaining_data: bytes,
        packet_size: int,
        mock_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
        packet_data: bytes = random.randbytes(packet_size)
        mock_deserialize_func.return_value = mocker.sentinel.packet

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        consumer.send(packet_data[:-1])
        packet, remaining_data = send_return(consumer, packet_data[-1:] + expected_remaining_data)

        # Assert
        mock_deserialize_func.assert_called_once_with(packet_data)
        assert packet is mocker.sentinel.packet
        assert remaining_data == expected_remaining_data

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
        ],
    )
    def test____incremental_deserialize____translate_deserialize_errors(
        self,
        expected_remaining_data: bytes,
        packet_size: int,
        mock_deserialize_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size, debug=debug_mode)
        packet_data: bytes = random.randbytes(packet_size)
        mock_deserialize_func.side_effect = DeserializeError("Bad news", error_info=mocker.sentinel.error_info)

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            consumer.send(packet_data + expected_remaining_data)
        exception = exc_info.value

        # Assert
        mock_deserialize_func.assert_called_once_with(packet_data)
        assert exception.__cause__ is mock_deserialize_func.side_effect
        assert bytes(exception.remaining_data) == expected_remaining_data
        assert exception.error_info is mocker.sentinel.error_info

    @pytest.mark.parametrize("sizehint_offset", [1024, 0, -1], ids=lambda i: f"(size{i:+})")
    def test____create_deserializer_buffer____returns_bytearray_buffer(
        self,
        sizehint_offset: int,
        packet_size: int,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
        sizehint = packet_size + sizehint_offset

        # Act
        buffer = serializer.create_deserializer_buffer(sizehint)

        # Assert
        assert isinstance(buffer, memoryview)
        assert isinstance(buffer.obj, bytearray)
        if sizehint >= packet_size:
            assert buffer.nbytes == sizehint
        else:
            assert buffer.nbytes == packet_size

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
        ],
    )
    def test____buffered_incremental_deserialize____one_shot_chunk(
        self,
        expected_remaining_data: bytes,
        packet_size: int,
        mock_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
        packet_data: bytes = random.randbytes(packet_size)
        mock_deserialize_func.return_value = mocker.sentinel.packet

        # Act
        buffer = serializer.create_deserializer_buffer(packet_size + len(expected_remaining_data) + 1024)
        consumer = serializer.buffered_incremental_deserialize(buffer)
        assert next(consumer) == 0
        nbytes, _ = write_data_and_extra_in_buffer(
            buffer,
            packet_data,
            expected_remaining_data,
            too_short_buffer_for_extra_data="error",
        )
        packet, remaining_data = send_return(consumer, nbytes)

        # Assert
        mock_deserialize_func.assert_called_once_with(packet_data)
        assert packet is mocker.sentinel.packet
        assert remaining_data == expected_remaining_data

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
        ],
    )
    def test____buffered_incremental_deserialize____several_chunks(
        self,
        expected_remaining_data: bytes,
        packet_size: int,
        mock_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
        packet_data: bytes = random.randbytes(packet_size)
        mock_deserialize_func.return_value = mocker.sentinel.packet

        # Act
        buffer = serializer.create_deserializer_buffer(packet_size + len(expected_remaining_data) + 1024)
        consumer = serializer.buffered_incremental_deserialize(buffer)
        assert next(consumer) == 0
        nbytes = write_in_buffer(buffer, packet_data[:-1])
        start_pos = consumer.send(nbytes)
        assert start_pos == nbytes
        nbytes, _ = write_data_and_extra_in_buffer(
            buffer,
            packet_data[-1:],
            expected_remaining_data,
            start_pos=start_pos,
            too_short_buffer_for_extra_data="error",
        )
        packet, remaining_data = send_return(consumer, nbytes)

        # Assert
        mock_deserialize_func.assert_called_once_with(packet_data)
        assert packet is mocker.sentinel.packet
        assert remaining_data == expected_remaining_data

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
        ],
    )
    def test____buffered_incremental_deserialize____translate_deserialize_errors(
        self,
        expected_remaining_data: bytes,
        packet_size: int,
        mock_deserialize_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size, debug=debug_mode)
        packet_data: bytes = random.randbytes(packet_size)
        mock_deserialize_func.side_effect = DeserializeError("Bad news", error_info=mocker.sentinel.error_info)

        # Act
        buffer = serializer.create_deserializer_buffer(packet_size + len(expected_remaining_data) + 1024)
        consumer = serializer.buffered_incremental_deserialize(buffer)
        assert next(consumer) == 0
        nbytes, _ = write_data_and_extra_in_buffer(
            buffer,
            packet_data,
            expected_remaining_data,
            too_short_buffer_for_extra_data="error",
        )
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            consumer.send(nbytes)
        exception = exc_info.value

        # Assert
        mock_deserialize_func.assert_called_once_with(packet_data)
        assert exception.__cause__ is mock_deserialize_func.side_effect
        assert bytes(exception.remaining_data) == expected_remaining_data
        assert exception.error_info is mocker.sentinel.error_info


class _FileBasedPacketSerializerForTest(FileBasedPacketSerializer[Any, Any]):
    def dump_to_file(self, packet: Any, file: IO[bytes]) -> None:
        raise NotImplementedError

    def load_from_file(self, file: IO[bytes]) -> Any:
        raise NotImplementedError


class TestFileBasedPacketSerializer:
    @pytest.fixture
    @staticmethod
    def mock_dump_to_file_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_FileBasedPacketSerializerForTest, "dump_to_file")

    @pytest.fixture
    @staticmethod
    def mock_load_from_file_func(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_FileBasedPacketSerializerForTest, "load_from_file")

    @pytest.fixture(params=["data", "buffer"])
    @staticmethod
    def incremental_deserialize_mode(request: pytest.FixtureRequest) -> str:
        assert request.param in ("data", "buffer")
        return request.param

    def test____properties____right_values(self, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer = _FileBasedPacketSerializerForTest(expected_load_error=(), debug=debug_mode, limit=123456789)

        # Assert
        assert serializer.debug is debug_mode
        assert serializer.buffer_limit == 123456789

    @pytest.mark.parametrize("limit", [0, -42], ids=lambda p: f"limit=={p}")
    def test____dunder_init____invalid_limit(self, limit: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^limit must be a positive integer$"):
            _ = _FileBasedPacketSerializerForTest(expected_load_error=(), limit=limit)

    def test____serialize____dump_to_file(
        self,
        mock_dump_to_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any, file: IO[bytes]) -> None:
            file.write(b"success")

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_dump_to_file_func.side_effect = side_effect

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_dump_to_file_func.assert_called_once_with(mocker.sentinel.packet, mocker.ANY)
        assert data == b"success"

    def test____deserialize____load_from_file(
        self,
        mock_load_from_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(file: IO[bytes]) -> Any:
            assert file.read() == b"data"
            return mocker.sentinel.packet

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_load_from_file_func.side_effect = side_effect

        # Act
        packet = serializer.deserialize(b"data")

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert packet is mocker.sentinel.packet

    def test____deserialize____translate_eof_errors(
        self,
        mock_load_from_file_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FileBasedPacketSerializerForTest(expected_load_error=(), debug=debug_mode)
        mock_load_from_file_func.side_effect = EOFError()

        # Act
        with pytest.raises(DeserializeError, match=r"^Missing data to create packet$") as exc_info:
            _ = serializer.deserialize(b"data")
        exception = exc_info.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert exception.__cause__ is mock_load_from_file_func.side_effect
        if debug_mode:
            assert exception.error_info == {"data": b"data"}
        else:
            assert exception.error_info is None

    @pytest.mark.parametrize("give_as_tuple", [False, True], ids=lambda boolean: f"give_as_tuple=={boolean}")
    def test____deserialize____translate_given_exceptions(
        self,
        give_as_tuple: bool,
        mock_load_from_file_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        class MyFileAPIBaseException(Exception):
            pass

        class MyFileAPIValueError(MyFileAPIBaseException, ValueError):
            pass

        if give_as_tuple:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=(MyFileAPIBaseException,), debug=debug_mode)
        else:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=MyFileAPIBaseException, debug=debug_mode)
        mock_load_from_file_func.side_effect = MyFileAPIValueError()

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(b"data")
        exception = exc_info.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert exception.__cause__ is mock_load_from_file_func.side_effect
        if debug_mode:
            assert exception.error_info == {"data": b"data"}
        else:
            assert exception.error_info is None

    def test____deserialize____with_remaining_data_to_read(
        self,
        mock_load_from_file_func: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(file: IO[bytes]) -> Any:
            assert file.read(2) == b"da"
            return mocker.sentinel.packet

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=(), debug=debug_mode)
        mock_load_from_file_func.side_effect = side_effect

        # Act
        with pytest.raises(DeserializeError, match=r"^Extra data caught$") as exc_info:
            _ = serializer.deserialize(b"data")
        exception = exc_info.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        if debug_mode:
            assert exception.error_info == {"packet": mocker.sentinel.packet, "extra": b"ta"}
        else:
            assert exception.error_info is None

    def test____incremental_serialize____dump_to_file(
        self,
        mock_dump_to_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any, file: IO[bytes]) -> None:
            file.write(b"success")

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_dump_to_file_func.side_effect = side_effect

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_dump_to_file_func.assert_called_once_with(mocker.sentinel.packet, mocker.ANY)
        assert data == [b"success"]

    def test____incremental_serialize____does_not_yield_if_there_is_no_data(
        self,
        mock_dump_to_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(_: Any, file: IO[bytes]) -> None:
            pass

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_dump_to_file_func.side_effect = side_effect

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_dump_to_file_func.assert_called_once_with(mocker.sentinel.packet, mocker.ANY)
        assert data == []

    @pytest.mark.parametrize(
        ["sizehint", "limit"],
        [
            pytest.param(1024, 65536, id="lower_than_limit"),
            pytest.param(65536, 65536, id="equal_to_limit"),
            pytest.param(65536, 1024, id="greater_than_limit"),
        ],
    )
    def test____create_deserializer____sizehint_limit(self, sizehint: int, limit: int) -> None:
        # Arrange
        serializer = _FileBasedPacketSerializerForTest(expected_load_error=(), limit=limit)

        # Act
        buffer = serializer.create_deserializer_buffer(sizehint)

        # Assert
        if sizehint <= limit:
            assert len(buffer) == sizehint
        else:
            assert len(buffer) == limit

    def test____incremental_deserialize____load_from_file____read_all(
        self,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_load_from_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(file: IO[bytes]) -> Any:
            assert file.read() == b"data"
            return mocker.sentinel.packet

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_load_from_file_func.side_effect = side_effect

        # Act
        remaining_data: ReadableBuffer
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                packet, remaining_data = send_return(data_consumer, b"data")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                packet, remaining_data = send_return(buffered_consumer, write_in_buffer(buffer, b"data"))
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert packet is mocker.sentinel.packet
        assert remaining_data == b""

    def test____incremental_deserialize____load_from_file____partial_read(
        self,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_load_from_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(file: IO[bytes]) -> Any:
            assert file.read(2) == b"da"
            return mocker.sentinel.packet

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_load_from_file_func.side_effect = side_effect

        # Act
        remaining_data: ReadableBuffer
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                packet, remaining_data = send_return(data_consumer, b"data")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                packet, remaining_data = send_return(buffered_consumer, write_in_buffer(buffer, b"data"))
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert packet is mocker.sentinel.packet
        assert remaining_data == b"ta"

    def test____incremental_deserialize____load_from_file____insufficient_read(
        self,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_load_from_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(file: IO[bytes]) -> Any:
            if len(data := file.read(4)) < 4:
                assert data == b"data"[: len(data)]
                raise EOFError
            assert data == b"data"
            return mocker.sentinel.packet

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_load_from_file_func.side_effect = side_effect

        # Act
        remaining_data: ReadableBuffer
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                data_consumer.send(b"d")
                data_consumer.send(b"a")
                data_consumer.send(b"t")
                packet, remaining_data = send_return(data_consumer, b"a")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                buffered_consumer.send(write_in_buffer(buffer, b"d"))
                buffered_consumer.send(write_in_buffer(buffer, b"a"))
                buffered_consumer.send(write_in_buffer(buffer, b"t"))
                packet, remaining_data = send_return(buffered_consumer, write_in_buffer(buffer, b"a"))
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        assert len(mock_load_from_file_func.call_args_list) == 4
        assert packet is mocker.sentinel.packet
        assert remaining_data == b""

    @pytest.mark.parametrize("give_as_tuple", [False, True], ids=lambda boolean: f"give_as_tuple=={boolean}")
    def test____incremental_deserialize____load_from_file____translate_given_exceptions(
        self,
        give_as_tuple: bool,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_load_from_file_func: MagicMock,
        debug_mode: bool,
    ) -> None:
        # Arrange
        class MyFileAPIBaseException(Exception):
            pass

        class MyFileAPIValueError(MyFileAPIBaseException, ValueError):
            pass

        class MyFileAPIEOFError(MyFileAPIBaseException, EOFError):
            pass

        def side_effect(file: IO[bytes]) -> Any:
            if len(data := file.read(4)) < 4:
                assert data == b"data"[: len(data)]
                raise MyFileAPIEOFError
            assert data.startswith(b"data")
            raise MyFileAPIValueError

        if give_as_tuple:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=(MyFileAPIBaseException,), debug=debug_mode)
        else:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=MyFileAPIBaseException, debug=debug_mode)
        mock_load_from_file_func.side_effect = side_effect

        # Act
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                data_consumer.send(b"d")
                data_consumer.send(b"a")
                data_consumer.send(b"t")
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    data_consumer.send(b"a")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                buffered_consumer.send(write_in_buffer(buffer, b"d"))
                buffered_consumer.send(write_in_buffer(buffer, b"a"))
                buffered_consumer.send(write_in_buffer(buffer, b"t"))
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    buffered_consumer.send(write_in_buffer(buffer, b"a"))
            case _:
                pytest.fail("Invalid fixture argument")

        exception = exc_info.value

        # Assert
        assert bytes(exception.remaining_data) == b""
        assert type(exception.__cause__) is MyFileAPIValueError
        if debug_mode:
            assert exception.error_info == {"data": b"data"}
        else:
            assert exception.error_info is None

    @pytest.mark.parametrize("at_first_chunk", [False, True], ids=lambda p: f"at_first_chunk=={p}")
    def test____incremental_deserialize____load_from_file____buffer_limit_overrun(
        self,
        at_first_chunk: bool,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_load_from_file_func: MagicMock,
    ) -> None:
        # Arrange
        def side_effect(file: IO[bytes]) -> Any:
            file.read()
            raise EOFError

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=(), limit=3)
        mock_load_from_file_func.side_effect = side_effect

        # Act
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                if at_first_chunk:
                    with pytest.raises(LimitOverrunError) as exc_info:
                        data_consumer.send(b"data")
                else:
                    data_consumer.send(b"d")
                    data_consumer.send(b"a")
                    data_consumer.send(b"t")
                    with pytest.raises(LimitOverrunError) as exc_info:
                        data_consumer.send(b"a")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                if at_first_chunk:
                    buffered_consumer.send(write_in_buffer(buffer, b"dat"))  # <- The buffer size is set to 3 (because of "limit")
                    with pytest.raises(LimitOverrunError) as exc_info:
                        buffered_consumer.send(write_in_buffer(buffer, b"a"))
                else:
                    buffered_consumer.send(write_in_buffer(buffer, b"d"))
                    buffered_consumer.send(write_in_buffer(buffer, b"a"))
                    buffered_consumer.send(write_in_buffer(buffer, b"t"))
                    with pytest.raises(LimitOverrunError) as exc_info:
                        buffered_consumer.send(write_in_buffer(buffer, b"a"))
            case _:
                pytest.fail("Invalid fixture argument")

        exception = exc_info.value

        # Assert
        assert bytes(exception.remaining_data) == b""
        assert exception.consumed == 4
