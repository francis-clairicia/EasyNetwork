# -*- coding: utf-8 -*

from __future__ import annotations

from typing import Literal

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.line import StringLineSerializer

import pytest

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

    @pytest.fixture
    @staticmethod
    def serializer(newline: Literal["LF", "CR", "CRLF"], encoding: str, unicode_errors: str) -> StringLineSerializer:
        return StringLineSerializer(newline, encoding=encoding, unicode_errors=unicode_errors)

    @pytest.mark.parametrize("method", ["incremental_serialize", "incremental_deserialize"])
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange
        from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer

        # Act & Assert
        assert getattr(StringLineSerializer, method) is getattr(AutoSeparatedPacketSerializer, method)

    def test____dunder_init____default(self) -> None:
        # Arrange

        # Act
        serializer = StringLineSerializer()

        # Assert
        assert serializer.separator == b"\n"
        assert serializer.encoding == "ascii"
        assert serializer.unicode_errors == "strict"

    @pytest.mark.parametrize("encoding", ["ascii", "utf-8"], indirect=True)
    @pytest.mark.parametrize("unicode_errors", ["strict", "ignore", "replace"], indirect=True)
    def test____dunder_init____with_parameters(
        self,
        newline: Literal["LF", "CR", "CRLF"],
        encoding: str,
        unicode_errors: str,
    ) -> None:
        # Arrange

        # Act
        serializer = StringLineSerializer(newline, encoding=encoding, unicode_errors=unicode_errors)

        # Assert
        assert serializer.separator == _NEWLINES[newline]
        assert serializer.encoding == encoding
        assert serializer.unicode_errors == unicode_errors

    def test____dunder_init____invalid_newline_value(
        self,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(AssertionError):
            StringLineSerializer("something else")  # type: ignore[arg-type]

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
        with pytest.raises(TypeError, match=r"^Expected a string, got 4$"):
            serializer.serialize(4)  # type: ignore[arg-type]

    def test____serialize____empty_string_error(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Empty packet$"):
            serializer.serialize("")

    @pytest.mark.parametrize("position", ["beginning", "between", "end"])
    def test____serialize____newline_in_string_error(
        self,
        position: Literal["beginning", "between", "end"],
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        separator = serializer.separator.decode()
        match position:
            case "beginning":
                packet = f"{separator}a"
            case "between":
                packet = f"a{separator}b"
            case "end":
                packet = f"b{separator}"
            case _:
                pytest.fail("Invalid fixture")

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Newline found in string$"):
            serializer.serialize(packet)

    @pytest.mark.parametrize("with_newlines", [False, True], ids=lambda boolean: f"with_newlines=={boolean}")
    def test____deserialize____decode_string(
        self,
        with_newlines: bool,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act
        line = serializer.deserialize(b"abc" + (serializer.separator * 3 if with_newlines else b""))

        # Assert
        assert isinstance(line, str)
        assert line == "abc"

    @pytest.mark.parametrize("with_newlines", [False, True], ids=lambda boolean: f"with_newlines=={boolean}")
    @pytest.mark.parametrize("encoding", ["ascii", "utf-8"], indirect=True)
    def test____deserialize____decode_string_error(
        self,
        with_newlines: bool,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        bad_unicode = "é".encode("latin-1")

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(bad_unicode + (serializer.separator * 3 if with_newlines else b""))
        exception = exc_info.value

        # Assert
        assert isinstance(exception.__cause__, UnicodeError)
        assert exception.error_info == {"data": bad_unicode}

    @pytest.mark.parametrize("with_newlines", [False, True], ids=lambda boolean: f"with_newlines=={boolean}")
    def test____deserialize____empty_string_error(
        self,
        with_newlines: bool,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(serializer.separator * 3 if with_newlines else b"")
        exception = exc_info.value

        # Assert
        assert exception.__cause__ is None
        assert exception.error_info == {"data": b""}

    @pytest.mark.parametrize("with_newlines_at_end", [False, True], ids=lambda boolean: f"with_newlines=={boolean}")
    @pytest.mark.parametrize("position", ["beginning", "between"])
    def test____deserialize____newline_in_string_error(
        self,
        with_newlines_at_end: bool,
        position: Literal["beginning", "between"],
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange
        separator = serializer.separator
        match position:
            case "beginning":
                packet = separator + b"a"
            case "between":
                packet = b"a" + separator + b"b"
            case _:
                pytest.fail("Invalid fixture")

        if with_newlines_at_end:
            packet += separator

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(packet)
        exception = exc_info.value

        # Assert
        assert exception.__cause__ is None
        assert exception.error_info == {"data": packet.removesuffix(separator)}
