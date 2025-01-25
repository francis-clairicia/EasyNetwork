from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError, LimitOverrunError
from easynetwork.lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from easynetwork.serializers.line import StringLineSerializer

import pytest

from ...tools import send_return, write_in_buffer

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

_NEWLINES: dict[str, bytes] = {
    "LF": b"\n",
    "CR": b"\r",
    "CRLF": b"\r\n",
}


class TestStringLineSerializer:
    @pytest.fixture(params=list(_NEWLINES))
    @staticmethod
    def newline(request: pytest.FixtureRequest) -> Literal["LF", "CR", "CRLF"]:
        return getattr(request, "param")

    @pytest.fixture(params=["ascii"])
    @staticmethod
    def encoding(request: pytest.FixtureRequest) -> str:
        return getattr(request, "param")

    @pytest.fixture(params=["strict"])
    @staticmethod
    def unicode_errors(request: pytest.FixtureRequest) -> str:
        return getattr(request, "param")

    @pytest.fixture(params=[False, True], ids=lambda p: f"keep_end=={p}")
    @staticmethod
    def keep_end(request: pytest.FixtureRequest) -> bool:
        return bool(request.param)

    @pytest.fixture(params=[DEFAULT_SERIALIZER_LIMIT], ids=lambda p: f"limit=={p}")
    @staticmethod
    def buffer_limit(request: pytest.FixtureRequest) -> int:
        return int(request.param)

    @pytest.fixture
    @staticmethod
    def serializer(
        newline: Literal["LF", "CR", "CRLF"],
        encoding: str,
        unicode_errors: str,
        buffer_limit: int,
        keep_end: bool,
        debug_mode: bool,
    ) -> StringLineSerializer:
        return StringLineSerializer(
            newline,
            encoding=encoding,
            unicode_errors=unicode_errors,
            limit=buffer_limit,
            keep_end=keep_end,
            debug=debug_mode,
        )

    @pytest.fixture(params=["data", "buffer"])
    @staticmethod
    def incremental_deserialize_mode(request: pytest.FixtureRequest) -> str:
        assert request.param in ("data", "buffer")
        return request.param

    def test____dunder_init____default(self) -> None:
        # Arrange

        # Act
        serializer = StringLineSerializer()

        # Assert
        assert serializer.separator == b"\n"
        assert serializer.encoding == "ascii"
        assert serializer.unicode_errors == "strict"
        assert serializer.debug is False
        assert serializer.buffer_limit == DEFAULT_SERIALIZER_LIMIT
        assert serializer.keep_end is False

    @pytest.mark.parametrize("encoding", ["ascii", "utf-8"], indirect=True)
    @pytest.mark.parametrize("unicode_errors", ["strict", "ignore", "replace"], indirect=True)
    @pytest.mark.parametrize("keep_end", [False, True], ids=lambda p: f"keep_end=={p}", indirect=True)
    def test____dunder_init____with_parameters(
        self,
        newline: Literal["LF", "CR", "CRLF"],
        encoding: str,
        unicode_errors: str,
        keep_end: bool,
        debug_mode: bool,
    ) -> None:
        # Arrange

        # Act
        serializer = StringLineSerializer(
            newline,
            encoding=encoding,
            unicode_errors=unicode_errors,
            keep_end=keep_end,
            debug=debug_mode,
            limit=123456789,
        )

        # Assert
        assert serializer.separator == _NEWLINES[newline]
        assert serializer.encoding == encoding
        assert serializer.unicode_errors == unicode_errors
        assert serializer.debug is debug_mode
        assert serializer.buffer_limit == 123456789
        assert serializer.keep_end is keep_end

    def test____dunder_init____invalid_newline_value(
        self,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(AssertionError):
            StringLineSerializer("something else")  # type: ignore[arg-type]

    @pytest.mark.parametrize("limit", [0, -42], ids=lambda p: f"limit=={p}")
    def test____dunder_init____invalid_limit(self, limit: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^limit must be a positive integer$"):
            StringLineSerializer(limit=limit)

    def test____serialize____encode_string(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act
        data = serializer.serialize("abc")

        # Assert
        assert isinstance(data, bytes)
        assert data == b"abc"

    def test____serialize____not_a_string_error(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^encoding without a string argument$"):
            serializer.serialize(4)  # type: ignore[arg-type]

    def test____serialize____empty_string(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act
        data = serializer.serialize("")

        # Assert
        assert isinstance(data, bytes)
        assert data == b""

    @pytest.mark.parametrize("with_newlines", [False, True], ids=lambda boolean: f"with_newlines=={boolean}")
    def test____deserialize____decode_string(
        self,
        with_newlines: bool,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        separator_b = serializer.separator * 3
        separator = separator_b.decode(serializer.encoding)

        # Act
        line = serializer.deserialize(b"abc" + (separator_b if with_newlines else b""))

        # Assert
        assert isinstance(line, str)
        if serializer.keep_end and with_newlines:
            assert line == f"abc{separator}"
        else:
            assert line == "abc"

    @pytest.mark.parametrize("with_newlines", [False, True], ids=lambda boolean: f"with_newlines=={boolean}")
    @pytest.mark.parametrize("encoding", ["ascii", "utf-8"], indirect=True)
    def test____deserialize____decode_string_error(
        self,
        with_newlines: bool,
        serializer: StringLineSerializer,
        debug_mode: bool,
    ) -> None:
        # Arrange
        bad_unicode = "é".encode("latin-1")
        suffix = serializer.separator * 3 if with_newlines else b""

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(bad_unicode + suffix)
        exception = exc_info.value

        # Assert
        assert isinstance(exception.__cause__, UnicodeError)
        if debug_mode:
            if serializer.keep_end:
                assert exception.error_info == {"data": bad_unicode + suffix}
            else:
                assert exception.error_info == {"data": bad_unicode}
        else:
            assert exception.error_info is None

    def test____incremental_serialize____empty_bytes(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act
        data = list(serializer.incremental_serialize(""))

        # Assert
        assert data == []

    def test____incremental_serialize____not_a_string_error(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^encoding without a string argument$"):
            list(serializer.incremental_serialize(4))  # type: ignore[arg-type]

    def test____incremental_serialize____append_separator(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act
        data = list(serializer.incremental_serialize("data"))

        # Assert
        assert data == [b"data" + serializer.separator]

    def test____incremental_serialize____keep_already_present_separator(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act
        data = list(serializer.incremental_serialize("data" + serializer.separator.decode()))

        # Assert
        assert data == [b"data" + serializer.separator]

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    @pytest.mark.parametrize("newline", ["CRLF"], indirect=True)
    def test____incremental_deserialize____one_shot_chunk(
        self,
        expected_remaining_data: bytes,
        incremental_deserialize_mode: Literal["data", "buffer"],
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
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
        assert bytes(remaining_data) == expected_remaining_data
        if serializer.keep_end:
            assert packet == "data\r\n"
        else:
            assert packet == "data"

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    @pytest.mark.parametrize("newline", ["CRLF"], indirect=True)
    def test____incremental_deserialize____several_chunks(
        self,
        expected_remaining_data: bytes,
        incremental_deserialize_mode: Literal["data", "buffer"],
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

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
        assert remaining_data == expected_remaining_data
        if serializer.keep_end:
            assert packet == "data\r\n"
        else:
            assert packet == "data"

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    @pytest.mark.parametrize("newline", ["CRLF"], indirect=True)
    def test____incremental_deserialize____translate_unicode_errors(
        self,
        expected_remaining_data: bytes,
        incremental_deserialize_mode: Literal["data", "buffer"],
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        bad_encoded_line = "é".encode("latin-1")

        # Act
        sent_data = bad_encoded_line + b"\r\n" + expected_remaining_data
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    data_consumer.send(sent_data)
                exception = exc_info.value
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                start_pos = next(buffered_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    buffered_consumer.send(write_in_buffer(buffer, sent_data, start_pos=start_pos))
                exception = exc_info.value
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        assert isinstance(exception.__cause__, UnicodeError)
        if serializer.debug:
            if serializer.keep_end:
                assert exception.error_info == {"data": bad_encoded_line + b"\r\n"}
            else:
                assert exception.error_info == {"data": bad_encoded_line}
        else:
            assert exception.error_info is None

    @pytest.mark.parametrize("separator_found", [False, True], ids=lambda p: f"separator_found=={p}")
    @pytest.mark.parametrize("newline", ["CRLF"], indirect=True)
    @pytest.mark.parametrize("buffer_limit", [1], indirect=True, ids=lambda p: f"limit=={p}")
    def test____incremental_deserialize____reached_limit(
        self,
        separator_found: bool,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        data_to_test: bytes = b"data"
        if separator_found:
            data_to_test += b"\r\n"

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(data_to_test)

        # Assert
        if separator_found:
            assert str(exc_info.value) == "Separator is found, but chunk is longer than limit"
        else:
            assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
        assert bytes(exc_info.value.remaining_data) == b""
        assert exc_info.value.error_info is None

    @pytest.mark.parametrize("separator_found", [False, True], ids=lambda p: f"separator_found=={p}")
    @pytest.mark.parametrize("newline", ["CRLF"], indirect=True)
    @pytest.mark.parametrize("buffer_limit", [1], indirect=True, ids=lambda p: f"limit=={p}")
    def test____incremental_deserialize____reached_limit____separator_partially_received(
        self,
        separator_found: bool,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        data_to_test: bytes = b"data\r"
        if separator_found:
            data_to_test += b"\n"

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(data_to_test)

        # Assert
        if separator_found:
            assert str(exc_info.value) == "Separator is found, but chunk is longer than limit"
            assert bytes(exc_info.value.remaining_data) == b""
        else:
            assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
            assert bytes(exc_info.value.remaining_data) == b"\r"
        assert exc_info.value.error_info is None

    @pytest.mark.parametrize("newline", ["CRLF"], indirect=True)
    @pytest.mark.parametrize("buffer_limit", [1024], indirect=True, ids=lambda p: f"limit=={p}")
    def test____buffered_incremental_deserialize____reached_limit(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        data_to_test: bytes = b"X" * 1023

        # Act
        buffer = serializer.create_deserializer_buffer(1024)
        consumer = serializer.buffered_incremental_deserialize(buffer)
        start_pos = next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(write_in_buffer(buffer, data_to_test, start_pos=start_pos))

        # Assert
        assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
        assert bytes(exc_info.value.remaining_data) == b""
        assert exc_info.value.error_info is None

    @pytest.mark.parametrize("newline", ["CRLF"], indirect=True)
    @pytest.mark.parametrize("buffer_limit", [1024], indirect=True, ids=lambda p: f"limit=={p}")
    def test____buffered_incremental_deserialize____reached_limit____separator_partially_received(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        data_to_test: bytes = b"X" * 1023 + b"\r"

        # Act
        buffer = serializer.create_deserializer_buffer(1024)
        consumer = serializer.buffered_incremental_deserialize(buffer)
        start_pos = next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(write_in_buffer(buffer, data_to_test, start_pos=start_pos))

        # Assert
        assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
        assert bytes(exc_info.value.remaining_data) == b"\r"
        assert exc_info.value.error_info is None
