# -*- coding: Utf-8 -*

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.line import StringLineSerializer

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

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

    @pytest.fixture(params=["ascii", "utf-8"])
    @staticmethod
    def encoding(request: pytest.FixtureRequest) -> str:
        return getattr(request, "param")

    @pytest.fixture(params=["strict", "ignore", "replace"])
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
        encoding: str,
        unicode_errors: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_string = mocker.NonCallableMagicMock(spec=str)
        mock_string.encode.return_value = mocker.sentinel.result

        # Act
        data = serializer.serialize(mock_string)

        # Assert
        assert data is mocker.sentinel.result
        mock_string.encode.assert_called_once_with(encoding, unicode_errors)

    def test____serialize____not_a_string_error(
        self,
        serializer: StringLineSerializer,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a string, got 4$"):
            serializer.serialize(4)  # type: ignore[arg-type]

    def test____deserialize____decode_string(
        self,
        serializer: StringLineSerializer,
        encoding: str,
        unicode_errors: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_bytes = mocker.NonCallableMagicMock(spec=bytes)
        mock_bytes.decode.return_value = mocker.sentinel.result

        # Act
        line = serializer.deserialize(mock_bytes)

        # Assert
        assert line is mocker.sentinel.result
        mock_bytes.decode.assert_called_once_with(encoding, unicode_errors)

    def test____deserialize____decode_string_error(
        self,
        serializer: StringLineSerializer,
        encoding: str,
        unicode_errors: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_bytes = mocker.NonCallableMagicMock(spec=bytes)
        mock_bytes.decode.side_effect = UnicodeError

        # Act
        with pytest.raises(DeserializeError):
            serializer.deserialize(mock_bytes)

        # Assert
        mock_bytes.decode.assert_called_once_with(encoding, unicode_errors)
