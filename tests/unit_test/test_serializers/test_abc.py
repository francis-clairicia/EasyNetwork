# -*- coding: utf-8 -*

from __future__ import annotations

import random
from typing import IO, TYPE_CHECKING, Any, Generator, final

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer
from easynetwork.serializers.base_stream import (
    AutoSeparatedPacketSerializer,
    FileBasedPacketSerializer,
    FixedSizePacketSerializer,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
class _IncrementalPacketSerializerForTest(AbstractIncrementalPacketSerializer[Any, Any]):
    def incremental_serialize(self, packet: Any) -> Generator[bytes, None, None]:
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
        def side_effect(_: Any) -> Generator[bytes, None, None]:
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
        with pytest.raises(DeserializeError, match=r"^Extra data caught$"):
            _ = serializer.deserialize(mocker.sentinel.data)

        # Assert
        mock_incremental_deserialize_func.assert_called_once_with()
        mock_consumer_generator.__next__.assert_called_once_with()
        mock_consumer_generator.send.assert_called_once_with(mocker.sentinel.data)

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

    @pytest.mark.parametrize("separator", [b"\n", b".", b"\r\n", b"--"], ids=lambda p: f"separator=={p}")
    def test____properties____right_values(self, separator: bytes) -> None:
        # Arrange

        # Act
        serializer = _AutoSeparatedPacketSerializerForTest(separator=separator)

        # Assert
        assert serializer.separator == separator

    def test____dunder_init____empty_separator_bytes(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Empty separator$"):
            _ = _AutoSeparatedPacketSerializerForTest(b"")

    def test____incremental_serialize____append_separator(
        self,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_serialize_func.return_value = b"data"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\n"]

    def test____incremental_serialize____keep_already_present_separator(
        self,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_serialize_func.return_value = b"data\r\n"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\n"]

    def test____incremental_serialize____remove_useless_trailing_separators(
        self,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_serialize_func.return_value = b"data\r\n\r\n\r\n\r\n"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\n"]

    def test____incremental_serialize____does_not_remove_partial_separator_at_end(
        self,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_serialize_func.return_value = b"data\r\r\n"

        # Act
        data = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serialize_func.assert_called_once_with(mocker.sentinel.packet)
        assert data == [b"data\r\r\n"]

    def test____incremental_serialize____error_if_separator_is_within_output(
        self,
        mock_serialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_serialize_func.return_value = b"data\r\nother"

        # Act & Assert
        with pytest.raises(
            ValueError,
            match=r"^b'[\\]r[\\]n' separator found in serialized packet sentinel\.packet which was not at the end$",
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
    @pytest.mark.parametrize("several_trailing_separators", [False, True], ids=lambda b: f"several_trailing_separators=={b}")
    @pytest.mark.parametrize("several_leading_separators", [False, True], ids=lambda b: f"several_leading_separators=={b}")
    def test____incremental_deserialize____one_shot_chunk(
        self,
        expected_remaining_data: bytes,
        several_trailing_separators: bool,
        several_leading_separators: bool,
        mock_deserialize_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_deserialize_func.return_value = mocker.sentinel.packet
        data_to_test: bytes = b"data\r\n"
        if several_trailing_separators:
            data_to_test = data_to_test + b"\r\n\r\n\r\n"
        if several_leading_separators:
            data_to_test = b"\r\n\r\n\r\n" + data_to_test

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(data_to_test + expected_remaining_data)
        packet, remaining_data = exc_info.value.value

        # Assert
        mock_deserialize_func.assert_called_once_with(b"data")
        assert remaining_data == expected_remaining_data
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
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_deserialize_func.return_value = mocker.sentinel.packet

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        consumer.send(b"data\r")
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(b"\n" + expected_remaining_data)
        packet, remaining_data = exc_info.value.value

        # Assert
        mock_deserialize_func.assert_called_once_with(b"data")
        assert remaining_data == expected_remaining_data
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
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _AutoSeparatedPacketSerializerForTest(separator=b"\r\n")
        mock_deserialize_func.side_effect = DeserializeError("Bad news", error_info=mocker.sentinel.error_info)

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            consumer.send(b"data\r\n" + expected_remaining_data)
        exception = exc_info.value

        # Assert
        mock_deserialize_func.assert_called_once_with(b"data")
        assert exception.__cause__ is mock_deserialize_func.side_effect
        assert exception.remaining_data == expected_remaining_data
        assert exception.error_info is mocker.sentinel.error_info


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

    def test____dunder_init____valid_packet_size(self, packet_size: int) -> None:
        # Arrange

        # Act
        serializer = _FixedSizePacketSerializerForTest(packet_size)

        # Assert
        assert serializer.packet_size == packet_size

    @pytest.mark.parametrize(
        "packet_size",
        [
            pytest.param(0, id="null value"),
            pytest.param(-1, id="negative value"),
        ],
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
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(packet_data + expected_remaining_data)
        packet, remaining_data = exc_info.value.value

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
    def test____incremental_deserialize____several_chunk(
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
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(packet_data[-1:] + expected_remaining_data)
        packet, remaining_data = exc_info.value.value

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
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FixedSizePacketSerializerForTest(packet_size)
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
        assert exception.remaining_data == expected_remaining_data
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
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_load_from_file_func.side_effect = EOFError()

        # Act
        with pytest.raises(DeserializeError, match=r"^Missing data to create packet$") as exc_info:
            _ = serializer.deserialize(b"data")
        exception = exc_info.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert exception.__cause__ is mock_load_from_file_func.side_effect
        assert exception.error_info == {"data": b"data"}

    @pytest.mark.parametrize("give_as_tuple", [False, True], ids=lambda boolean: f"give_as_tuple=={boolean}")
    def test____deserialize____translate_given_exceptions(
        self,
        give_as_tuple: bool,
        mock_load_from_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        class MyFileAPIBaseException(Exception):
            pass

        class MyFileAPIValueError(MyFileAPIBaseException, ValueError):
            pass

        if give_as_tuple:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=(MyFileAPIBaseException,))
        else:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=MyFileAPIBaseException)
        mock_load_from_file_func.side_effect = MyFileAPIValueError()

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(b"data")
        exception = exc_info.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert exception.__cause__ is mock_load_from_file_func.side_effect
        assert exception.error_info == {"data": b"data"}

    def test____deserialize____with_remaining_data_to_read(
        self,
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
        with pytest.raises(DeserializeError, match=r"^Extra data caught$") as exc_info:
            _ = serializer.deserialize(b"data")
        exception = exc_info.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert exception.error_info == {"packet": mocker.sentinel.packet, "extra": b"ta"}

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

    def test____incremental_deserialize____load_from_file____read_all(
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
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(b"data")
        packet, remaining_data = exc_info.value.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert packet is mocker.sentinel.packet
        assert remaining_data == b""

    def test____incremental_deserialize____load_from_file____partial_read(
        self,
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
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(b"data")
        packet, remaining_data = exc_info.value.value

        # Assert
        mock_load_from_file_func.assert_called_once_with(mocker.ANY)
        assert packet is mocker.sentinel.packet
        assert remaining_data == b"ta"

    def test____incremental_deserialize____load_from_file____insufficient_read(
        self,
        mock_load_from_file_func: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def side_effect(file: IO[bytes]) -> Any:
            if len((data := file.read(4))) < 4:
                assert data == b"data"[: len(data)]
                raise EOFError
            assert data == b"data"
            return mocker.sentinel.packet

        serializer = _FileBasedPacketSerializerForTest(expected_load_error=())
        mock_load_from_file_func.side_effect = side_effect

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        consumer.send(b"d")
        consumer.send(b"a")
        consumer.send(b"t")
        with pytest.raises(StopIteration) as exc_info:
            consumer.send(b"a")
        packet, remaining_data = exc_info.value.value

        # Assert
        assert len(mock_load_from_file_func.mock_calls) == 4
        assert packet is mocker.sentinel.packet
        assert remaining_data == b""

    @pytest.mark.parametrize("give_as_tuple", [False, True], ids=lambda boolean: f"give_as_tuple=={boolean}")
    def test____incremental_deserialize____load_from_file____translate_given_exceptions(
        self,
        give_as_tuple: bool,
        mock_load_from_file_func: MagicMock,
    ) -> None:
        # Arrange
        class MyFileAPIBaseException(Exception):
            pass

        class MyFileAPIValueError(MyFileAPIBaseException, ValueError):
            pass

        class MyFileAPIEOFError(MyFileAPIBaseException, EOFError):
            pass

        def side_effect(file: IO[bytes]) -> Any:
            if len((data := file.read(4))) < 4:
                assert data == b"data"[: len(data)]
                raise MyFileAPIEOFError
            assert data.startswith(b"data")
            raise MyFileAPIValueError

        if give_as_tuple:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=(MyFileAPIBaseException,))
        else:
            serializer = _FileBasedPacketSerializerForTest(expected_load_error=MyFileAPIBaseException)
        mock_load_from_file_func.side_effect = side_effect

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        consumer.send(b"d")
        consumer.send(b"a")
        consumer.send(b"t")
        consumer.send(b"a")  # MyFileAPIValueError was raised but there is no remaining data, so it must continue
        with pytest.raises(IncrementalDeserializeError) as exc_info:  # There is new data and error still here
            consumer.send(b"other")
        exception = exc_info.value

        # Assert
        assert exception.remaining_data == b"other"
        assert type(exception.__cause__) is MyFileAPIValueError
        assert exception.error_info == {"data": b"dataother"}
