from __future__ import annotations

import collections
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, final

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.struct import (
    _ENDIANNESS_CHARACTERS,
    AbstractStructSerializer,
    NamedTupleStructSerializer,
    StructSerializer,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
class _StructSerializerForTest(AbstractStructSerializer[Any, Any]):
    def iter_values(self, packet: Any) -> Iterable[Any]:
        raise NotImplementedError

    def from_tuple(self, t: tuple[Any, ...]) -> Any:
        raise NotImplementedError


class BaseTestStructBasedSerializer:
    @pytest.fixture
    @staticmethod
    def mock_struct(mocker: MockerFixture) -> MagicMock:
        from struct import Struct

        mock = mocker.NonCallableMagicMock(spec=Struct)
        mock.size = 123456789
        return mock

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_struct_cls(mocker: MockerFixture, mock_struct: MagicMock) -> MagicMock:
        return mocker.patch("struct.Struct", return_value=mock_struct)


class TestAbstractStructSerializer(BaseTestStructBasedSerializer):
    @pytest.fixture
    @staticmethod
    def mock_serializer_iter_values(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_StructSerializerForTest, "iter_values")

    @pytest.fixture
    @staticmethod
    def mock_serializer_from_tuple(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_StructSerializerForTest, "from_tuple")

    @pytest.mark.parametrize(
        "method",
        [
            "incremental_serialize",
            "incremental_deserialize",
            "create_deserializer_buffer",
            "buffered_incremental_deserialize",
        ],
    )
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange
        from easynetwork.serializers.base_stream import FixedSizePacketSerializer

        # Act & Assert
        assert getattr(AbstractStructSerializer, method) is getattr(FixedSizePacketSerializer, method)

    @pytest.mark.parametrize("endianness", sorted(_ENDIANNESS_CHARACTERS.union([""])), ids=repr)
    def test____dunder_init____format_with_endianness(
        self,
        endianness: str,
        mock_struct_cls: MagicMock,
        mock_struct: MagicMock,
    ) -> None:
        # Arrange
        format = "format"
        expected_format = f"{endianness}{format}" if endianness else f"!{format}"

        # Act
        serializer = _StructSerializerForTest(f"{endianness}{format}")

        # Assert
        mock_struct_cls.assert_called_once_with(expected_format)
        assert serializer.struct is mock_struct
        assert serializer.packet_size == 123456789

    def test____serialize____pack_values(
        self,
        mock_struct: MagicMock,
        mock_serializer_iter_values: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _StructSerializerForTest("format")
        mock_struct_pack: MagicMock = mock_struct.pack
        mock_struct_pack.return_value = mocker.sentinel.data
        mock_serializer_iter_values.return_value = iter([getattr(mocker.sentinel, f"value_{i + 1}") for i in range(3)])

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_serializer_iter_values.assert_called_once_with(mocker.sentinel.packet)
        mock_struct_pack.assert_called_once_with(
            mocker.sentinel.value_1,
            mocker.sentinel.value_2,
            mocker.sentinel.value_3,
        )
        assert data is mocker.sentinel.data

    def test____deserialize____unpack_values(
        self,
        mock_struct: MagicMock,
        mock_serializer_from_tuple: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _StructSerializerForTest("format")
        mock_struct_unpack: MagicMock = mock_struct.unpack
        mock_struct_unpack.return_value = mocker.sentinel.packet_tuple
        mock_serializer_from_tuple.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(mocker.sentinel.data)

        # Assert
        mock_struct_unpack.assert_called_once_with(mocker.sentinel.data)
        mock_serializer_from_tuple.assert_called_once_with(mocker.sentinel.packet_tuple)
        assert packet is mocker.sentinel.packet

    def test____deserialize____translate_struct_errors(
        self,
        mock_struct: MagicMock,
        mock_serializer_from_tuple: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from struct import error as StructError

        serializer = _StructSerializerForTest("format", debug=debug_mode)
        mock_struct_unpack: MagicMock = mock_struct.unpack
        mock_struct_unpack.side_effect = StructError()

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(mocker.sentinel.data)
        exception = exc_info.value

        # Assert
        mock_struct_unpack.assert_called_once_with(mocker.sentinel.data)
        mock_serializer_from_tuple.assert_not_called()
        assert exception.__cause__ is mock_struct_unpack.side_effect
        if debug_mode:
            assert exception.error_info == {"data": mocker.sentinel.data}
        else:
            assert exception.error_info is None


class TestNamedTupleStructSerializer(BaseTestStructBasedSerializer):
    @pytest.mark.parametrize(
        "method",
        [
            "serialize",
            "incremental_serialize",
            "deserialize",
            "incremental_deserialize",
            "create_deserializer_buffer",
            "buffered_incremental_deserialize",
        ],
    )
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange

        # Act & Assert
        assert getattr(NamedTupleStructSerializer, method) is getattr(AbstractStructSerializer, method)

    @pytest.mark.parametrize(
        ["fields", "field_formats", "expected_format"],
        [
            pytest.param((), {}, "", id="no fields"),
            pytest.param(("string", "int"), {"string": "10s", "int": "Q"}, "10sQ", id="10sQ"),
            pytest.param(("int", "string"), {"string": "10s", "int": "Q"}, "Q10s", id="Q10s"),
            pytest.param(("string", "int"), {"string": "s", "int": "Q"}, "sQ", id="sQ"),
            pytest.param(("int", "string"), {"string": "s", "int": "Q"}, "Qs", id="Qs"),
        ],
    )
    @pytest.mark.parametrize("endianness", sorted(_ENDIANNESS_CHARACTERS.union([""])), ids=repr)
    def test____dunder_init____compute_right_format(
        self,
        fields: tuple[str, ...],
        field_formats: dict[str, str],
        expected_format: str,
        endianness: str,
        mock_struct_cls: MagicMock,
        debug_mode: bool,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", fields)  # type: ignore[misc]
        if not endianness and expected_format:
            expected_format = f"!{expected_format}"
        else:
            expected_format = f"{endianness}{expected_format}"

        # Act
        serializer = NamedTupleStructSerializer(namedtuple_cls, field_formats, format_endianness=endianness, debug=debug_mode)

        # Assert
        mock_struct_cls.assert_called_once_with(expected_format)
        assert serializer.debug is debug_mode

    @pytest.mark.parametrize("endianness", ["z", "word"], ids=repr)
    def test____dunder_init____invalid_endianness_character(
        self,
        endianness: str,
        mock_struct_cls: MagicMock,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        field_formats: dict[str, str] = {"x": "Q", "y": "I"}

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Invalid endianness character$"):
            _ = NamedTupleStructSerializer(namedtuple_cls, field_formats, format_endianness=endianness)

        mock_struct_cls.assert_not_called()

    @pytest.mark.parametrize("endianness", sorted(_ENDIANNESS_CHARACTERS), ids=repr)
    @pytest.mark.parametrize("field", ["x", "y"], ids=repr)
    def test____dunder_init____endianness_character_in_fields_format_error(
        self,
        endianness: str,
        field: str,
        mock_struct_cls: MagicMock,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        field_formats: dict[str, str] = {"x": "Q", "y": "I"}
        field_formats[field] += endianness

        # Act & Assert
        with pytest.raises(ValueError, match=rf"^{field!r}: Invalid field format$"):
            _ = NamedTupleStructSerializer(namedtuple_cls, field_formats)

        mock_struct_cls.assert_not_called()

    @pytest.mark.parametrize("field", ["x", "y"], ids=repr)
    def test____dunder_init____missing_field_format_error(
        self,
        field: str,
        mock_struct_cls: MagicMock,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        field_formats: dict[str, str] = {"x": "Q", "y": "I"}
        del field_formats[field]

        # Act & Assert
        with pytest.raises(KeyError, match=rf"^{field!r}$"):
            _ = NamedTupleStructSerializer(namedtuple_cls, field_formats)

        mock_struct_cls.assert_not_called()

    @pytest.mark.parametrize("format", ["4Q", "10c", "abc"], ids=repr)
    @pytest.mark.parametrize("field", ["x", "y"], ids=repr)
    def test____dunder_init____field_format_not_a_single_character_error(
        self,
        format: str,
        field: str,
        mock_struct_cls: MagicMock,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        field_formats: dict[str, str] = {"x": "Q", "y": "I"}
        field_formats[field] = format

        # Act & Assert
        with pytest.raises(ValueError, match=rf"^{field!r}: Invalid field format$"):
            _ = NamedTupleStructSerializer(namedtuple_cls, field_formats)

        mock_struct_cls.assert_not_called()

    @pytest.mark.parametrize("format", ["4", "#", "\\"], ids=repr)
    @pytest.mark.parametrize("field", ["x", "y"], ids=repr)
    def test____dunder_init____field_format_not_a_alphabet_character_error(
        self,
        format: str,
        field: str,
        mock_struct_cls: MagicMock,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        field_formats: dict[str, str] = {"x": "Q", "y": "I"}
        field_formats[field] = format

        # Act & Assert
        with pytest.raises(ValueError, match=rf"^{field!r}: Invalid field format$"):
            _ = NamedTupleStructSerializer(namedtuple_cls, field_formats)

        mock_struct_cls.assert_not_called()

    @pytest.mark.parametrize("format", ["²s", "b2s", "abcs"], ids=repr)
    @pytest.mark.parametrize("field", ["x", "y"], ids=repr)
    def test____dunder_init____string_field_format_with_non_number_sequence_error(
        self,
        format: str,
        field: str,
        mock_struct_cls: MagicMock,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        field_formats: dict[str, str] = {"x": "Q", "y": "I"}
        field_formats[field] = format

        # Act & Assert
        with pytest.raises(ValueError, match=rf"^{field!r}: Invalid field format$"):
            _ = NamedTupleStructSerializer(namedtuple_cls, field_formats)

        mock_struct_cls.assert_not_called()

    def test____iter_values____return_given_instance_if_there_is_no_strings(self) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        namedtuple_instance = namedtuple_cls(1234, 56789)
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"x": "I", "y": "I"})

        # Act
        iterable = serializer.iter_values(namedtuple_instance)

        # Assert
        assert iterable is namedtuple_instance

    def test____iter_values____return_given_instance_if_there_is_strings_but_no_encoding(self) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        namedtuple_instance = namedtuple_cls("1234", "56789")
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"x": "4s", "y": "5s"}, encoding=None)

        # Act
        iterable = serializer.iter_values(namedtuple_instance)

        # Assert
        assert iterable is namedtuple_instance

    def test____iter_values____return_transformed_instance_if_there_is_strings_and_encoding(self) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        namedtuple_instance = namedtuple_cls("1234", "56789")
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"x": "4s", "y": "5s"}, encoding="utf-8")

        # Act
        iterable = serializer.iter_values(namedtuple_instance)

        # Assert
        assert isinstance(iterable, namedtuple_cls)
        assert iterable is not namedtuple_instance
        assert isinstance(iterable.x, bytes)
        assert isinstance(iterable.y, bytes)
        assert iterable.x == b"1234"
        assert iterable.y == b"56789"

    def test____iter_values____wrong_namedtuple(self) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        namedtuple_cls_copy = collections.namedtuple("namedtuple_cls_copy", ["x", "y"])
        namedtuple_instance = namedtuple_cls_copy(1234, 56789)
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"x": "I", "y": "I"})

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a namedtuple_cls instance, got namedtuple_cls_copy\(x=1234, y=56789\)$"):
            _ = serializer.iter_values(namedtuple_instance)  # type: ignore[arg-type]

    def test____from_tuple____construct_namedtuple____without_strings(self) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"x": "I", "y": "I"})

        # Act
        result = serializer.from_tuple((1234, 56789))

        # Assert
        assert isinstance(result, namedtuple_cls)
        assert result.x == 1234
        assert result.y == 56789

    def test____from_tuple____construct_namedtuple____with_strings_but_no_encoding(self) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"x": "4s", "y": "5s"}, encoding=None)

        # Act
        result = serializer.from_tuple((b"1234", b"56789"))

        # Assert
        assert isinstance(result, namedtuple_cls)
        assert isinstance(result.x, bytes)
        assert isinstance(result.y, bytes)
        assert result.x == b"1234"
        assert result.y == b"56789"

    def test____from_tuple____construct_namedtuple____with_strings_and_encoding(self) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"x": "4s", "y": "5s"}, encoding="utf-8")

        # Act
        result = serializer.from_tuple((b"1234", b"56789"))

        # Assert
        assert isinstance(result, namedtuple_cls)
        assert isinstance(result.x, str)
        assert isinstance(result.y, str)
        assert result.x == "1234"
        assert result.y == "56789"

    def test____from_tuple____construct_namedtuple____with_strings_and_encoding____decode_error(
        self,
        debug_mode: bool,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["data"])
        serializer = NamedTupleStructSerializer(namedtuple_cls, {"data": "10s"}, encoding="utf-8", debug=debug_mode)
        packet_tuple = ("é".encode("latin-1").ljust(10, b"\0"),)

        # Act
        with pytest.raises(
            DeserializeError, match=r"^UnicodeError when building packet from unpacked struct value: .+$"
        ) as exc_info:
            _ = serializer.from_tuple(packet_tuple)

        # Assert
        assert isinstance(exc_info.value.__cause__, UnicodeError)
        if debug_mode:
            assert exc_info.value.error_info == {"unpacked_struct": packet_tuple}
        else:
            assert exc_info.value.error_info is None

    @pytest.mark.parametrize(
        "strip_string_trailing_nul_bytes",
        [True, False],
        ids=lambda boolean: f"strip_string_trailing_nul_bytes=={boolean}",
    )
    @pytest.mark.parametrize(
        "encoding",
        [None, "utf-8"],
        ids=lambda value: f"encoding=={value}",
    )
    def test____from_tuple____construct_namedtuple____string_padding(
        self,
        strip_string_trailing_nul_bytes: bool,
        encoding: str | None,
    ) -> None:
        # Arrange
        namedtuple_cls = collections.namedtuple("namedtuple_cls", ["x", "y"])
        serializer = NamedTupleStructSerializer(
            namedtuple_cls,
            {"x": "10s", "y": "10s"},
            encoding=encoding,
            strip_string_trailing_nul_bytes=strip_string_trailing_nul_bytes,
        )
        x, y = b"1234\x00\x00\x00\x00\x00\x00", b"56789\x00\x00\x00\x00\x00"
        expected_x, expected_y = x, y
        if strip_string_trailing_nul_bytes:
            expected_x = expected_x.rstrip(b"\x00")
            expected_y = expected_y.rstrip(b"\x00")

        # Act
        result = serializer.from_tuple((x, y))

        # Assert
        assert isinstance(result, namedtuple_cls)
        if encoding is not None:
            assert isinstance(result.x, str)
            assert isinstance(result.y, str)
            assert result.x == expected_x.decode(encoding)
            assert result.y == expected_y.decode(encoding)
        else:
            assert isinstance(result.x, bytes)
            assert isinstance(result.y, bytes)
            assert result.x == expected_x
            assert result.y == expected_y


class TestStructSerializer(BaseTestStructBasedSerializer):
    @pytest.mark.parametrize(
        "method",
        [
            "serialize",
            "incremental_serialize",
            "deserialize",
            "incremental_deserialize",
            "create_deserializer_buffer",
            "buffered_incremental_deserialize",
        ],
    )
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange

        # Act & Assert
        assert getattr(StructSerializer, method) is getattr(AbstractStructSerializer, method)

    @pytest.mark.parametrize("endianness", sorted(_ENDIANNESS_CHARACTERS.union([""])), ids=repr)
    def test____dunder_init____format_with_endianness(
        self,
        endianness: str,
        mock_struct_cls: MagicMock,
        mock_struct: MagicMock,
    ) -> None:
        # Arrange
        format = "format"
        expected_format = f"{endianness}{format}" if endianness else f"!{format}"

        # Act
        serializer = StructSerializer(f"{endianness}{format}")

        # Assert
        mock_struct_cls.assert_called_once_with(expected_format)
        assert serializer.struct is mock_struct
        assert serializer.packet_size == 123456789

    def test____iter_values____return_given_instance(self) -> None:
        # Arrange
        serializer = StructSerializer("format")
        packet = (10, b"data")

        # Act
        iterable = serializer.iter_values(packet)

        # Assert
        assert iterable is packet

    def test____iter_values____error_not_tuple(self) -> None:
        # Arrange
        serializer = StructSerializer("format")
        packet = [10, b"data"]

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a tuple instance, got \[10, b'data'\]$"):
            _ = serializer.iter_values(packet)  # type: ignore[arg-type]

    def test____from_tuple____return_given_instance(self) -> None:
        # Arrange
        serializer = StructSerializer("format")
        packet_tuple = (10, b"data")

        # Act
        packet = serializer.from_tuple(packet_tuple)

        # Assert
        assert packet is packet_tuple
