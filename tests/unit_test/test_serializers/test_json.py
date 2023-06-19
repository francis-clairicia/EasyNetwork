# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generator

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.json import JSONDecoderConfig, JSONEncoderConfig, JSONSerializer, _JSONParser

import pytest

from ...tools import send_return
from .base import BaseSerializerConfigInstanceCheck

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestJSONSerializer(BaseSerializerConfigInstanceCheck):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[JSONSerializer[Any, Any]]:
        return JSONSerializer

    @pytest.fixture(params=["encoder", "decoder"])
    @staticmethod
    def config_param(request: Any) -> tuple[str, str]:
        name: str = request.param
        return (name, f"JSON{name.capitalize()}Config")

    @pytest.fixture
    @staticmethod
    def mock_encoder(mocker: MockerFixture) -> MagicMock:
        from json import JSONEncoder

        return mocker.NonCallableMagicMock(spec=JSONEncoder)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_encoder_cls(mocker: MockerFixture, mock_encoder: MagicMock) -> MagicMock:
        return mocker.patch("json.JSONEncoder", return_value=mock_encoder)

    @pytest.fixture
    @staticmethod
    def mock_decoder(mocker: MockerFixture) -> MagicMock:
        from json import JSONDecoder

        return mocker.NonCallableMagicMock(spec=JSONDecoder)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_decoder_cls(mocker: MockerFixture, mock_decoder: MagicMock) -> MagicMock:
        return mocker.patch("json.JSONDecoder", return_value=mock_decoder)

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_encoder_config=={boolean}")
    @staticmethod
    def encoder_config(request: Any, mocker: MockerFixture) -> JSONEncoderConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return JSONEncoderConfig(
            skipkeys=mocker.sentinel.skipkeys,
            check_circular=mocker.sentinel.check_circular,
            ensure_ascii=mocker.sentinel.ensure_ascii,
            allow_nan=mocker.sentinel.allow_nan,
            indent=mocker.sentinel.indent,
            separators=mocker.sentinel.separators,
            default=mocker.sentinel.object_default,
        )

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_decoder_config=={boolean}")
    @staticmethod
    def decoder_config(request: Any, mocker: MockerFixture) -> JSONDecoderConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return JSONDecoderConfig(
            object_hook=mocker.sentinel.object_hook,
            parse_int=mocker.sentinel.parse_int,
            parse_float=mocker.sentinel.parse_float,
            parse_constant=mocker.sentinel.parse_constant,
            object_pairs_hook=mocker.sentinel.object_pairs_hook,
            strict=mocker.sentinel.strict,
        )

    @pytest.fixture
    @staticmethod
    def mock_json_parser(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_JSONParser, "raw_parse", autospec=True)

    def test____dunder_init____with_encoder_config(
        self,
        encoder_config: JSONEncoderConfig | None,
        mock_encoder_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = JSONSerializer(encoder_config=encoder_config)

        # Assert
        mock_encoder_cls.assert_called_once_with(
            skipkeys=mocker.sentinel.skipkeys if encoder_config is not None else False,
            check_circular=mocker.sentinel.check_circular if encoder_config is not None else True,
            ensure_ascii=mocker.sentinel.ensure_ascii if encoder_config is not None else True,
            allow_nan=mocker.sentinel.allow_nan if encoder_config is not None else True,
            indent=mocker.sentinel.indent if encoder_config is not None else None,
            separators=mocker.sentinel.separators if encoder_config is not None else (",", ":"),
            default=mocker.sentinel.object_default if encoder_config is not None else None,
        )

    def test____dunder_init____with_decoder_config(
        self,
        decoder_config: JSONDecoderConfig | None,
        mock_decoder_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = JSONSerializer(decoder_config=decoder_config)

        # Assert
        mock_decoder_cls.assert_called_once_with(
            object_hook=mocker.sentinel.object_hook if decoder_config is not None else None,
            parse_int=mocker.sentinel.parse_int if decoder_config is not None else None,
            parse_float=mocker.sentinel.parse_float if decoder_config is not None else None,
            parse_constant=mocker.sentinel.parse_constant if decoder_config is not None else None,
            object_pairs_hook=mocker.sentinel.object_pairs_hook if decoder_config is not None else None,
            strict=mocker.sentinel.strict if decoder_config is not None else True,
        )

    def test____serialize____encode_packet(
        self,
        mock_encoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer[Any, Any] = JSONSerializer(
            encoding=mocker.sentinel.encoding,
            unicode_errors=mocker.sentinel.str_errors,
        )
        mock_string = mock_encoder.encode.return_value = mocker.NonCallableMagicMock()
        mock_string.encode.return_value = mocker.sentinel.data

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_encoder.encode.assert_called_once_with(mocker.sentinel.packet)
        mock_string.encode.assert_called_once_with(mocker.sentinel.encoding, mocker.sentinel.str_errors)
        assert data is mocker.sentinel.data

    def test____incremental_serialize____iterencode_packet(
        self,
        mock_encoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer[Any, Any] = JSONSerializer(
            encoding=mocker.sentinel.encoding,
            unicode_errors=mocker.sentinel.str_errors,
        )
        chunk_a = mocker.NonCallableMagicMock(**{"encode.return_value": mocker.sentinel.chunk_a})
        chunk_b = mocker.NonCallableMagicMock(**{"encode.return_value": mocker.sentinel.chunk_b})
        chunk_c = mocker.NonCallableMagicMock(**{"encode.return_value": mocker.sentinel.chunk_c})
        mock_encoder.iterencode.return_value = iter([chunk_a, chunk_b, chunk_c])

        # Act & Assert
        generator = serializer.incremental_serialize(mocker.sentinel.packet)
        first_chunk = next(generator)
        chunk_a.encode.assert_called_once_with(mocker.sentinel.encoding, mocker.sentinel.str_errors)
        assert first_chunk is mocker.sentinel.chunk_a
        del chunk_a, first_chunk
        second_chunk = next(generator)
        chunk_b.encode.assert_called_once_with(mocker.sentinel.encoding, mocker.sentinel.str_errors)
        assert second_chunk is mocker.sentinel.chunk_b
        del chunk_b, second_chunk
        third_chunk = next(generator)
        chunk_c.encode.assert_called_once_with(mocker.sentinel.encoding, mocker.sentinel.str_errors)
        assert third_chunk is mocker.sentinel.chunk_c
        del chunk_c, third_chunk
        last_chunk = next(generator)
        assert isinstance(last_chunk, bytes)
        assert last_chunk == b"\n"
        with pytest.raises(StopIteration):
            next(generator)

        mock_encoder.iterencode.assert_called_once_with(mocker.sentinel.packet)

    def test____deserialize____decode_data(
        self,
        mock_decoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer[Any, Any] = JSONSerializer(
            encoding=mocker.sentinel.encoding,
            unicode_errors=mocker.sentinel.str_errors,
        )
        mock_bytes = mocker.NonCallableMagicMock()
        mock_bytes.decode.return_value = mocker.sentinel.document
        mock_decoder.decode.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(mock_bytes)

        # Assert
        mock_bytes.decode.assert_called_once_with(mocker.sentinel.encoding, mocker.sentinel.str_errors)
        mock_decoder.decode.assert_called_once_with(mocker.sentinel.document)
        assert packet is mocker.sentinel.packet

    def test____deserialize____translate_unicode_decode_errors(
        self,
        mock_decoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer[Any, Any] = JSONSerializer()
        mock_bytes = mocker.NonCallableMagicMock()
        mock_bytes.decode.side_effect = UnicodeDecodeError("some encoding", b"invalid data", 0, 2, "Bad encoding ?")

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(mock_bytes)
        exception = exc_info.value

        # Assert
        mock_bytes.decode.assert_called_once()
        mock_decoder.decode.assert_not_called()
        assert exception.__cause__ is mock_bytes.decode.side_effect
        assert exception.error_info == {"data": mock_bytes}

    def test____deserialize____translate_json_decode_errors(
        self,
        mock_decoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from json import JSONDecodeError

        serializer: JSONSerializer[Any, Any] = JSONSerializer()
        mock_bytes = mocker.NonCallableMagicMock()
        mock_decoder.decode.side_effect = JSONDecodeError("Invalid payload", "invalid\ndocument", 8)

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(mock_bytes)
        exception = exc_info.value

        # Assert
        mock_bytes.decode.assert_called_once()
        mock_decoder.decode.assert_called_once()
        assert exception.__cause__ is mock_decoder.decode.side_effect
        assert exception.error_info == {
            "document": "invalid\ndocument",
            "position": 8,
            "lineno": 2,
            "colno": 1,
        }

    def test____incremental_deserialize____parse_and_decode_data(
        self,
        mock_decoder: MagicMock,
        mock_json_parser: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def raw_parse_side_effect() -> Generator[None, bytes, tuple[bytes, bytes]]:
            data = yield
            assert data is mocker.sentinel.data
            return mock_bytes, b"Hello World !"

        serializer: JSONSerializer[Any, Any] = JSONSerializer(
            encoding=mocker.sentinel.encoding,
            unicode_errors=mocker.sentinel.str_errors,
        )
        mock_bytes = mocker.NonCallableMagicMock()
        mock_string_document = mock_bytes.decode.return_value = mocker.NonCallableMagicMock()
        mock_sliced_string = mock_string_document.__getitem__.return_value = mocker.NonCallableMagicMock()
        mock_sliced_string.encode.return_value = b"Trailing data + "
        mock_decoder.raw_decode.return_value = mocker.sentinel.packet, 123456789
        mock_json_parser.side_effect = raw_parse_side_effect

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        packet, remaining_data = send_return(consumer, mocker.sentinel.data)

        # Assert
        mock_json_parser.assert_called_once_with()
        mock_bytes.decode.assert_called_once_with(mocker.sentinel.encoding, mocker.sentinel.str_errors)
        mock_decoder.raw_decode.assert_called_once_with(mock_string_document)
        mock_string_document.__getitem__.assert_called_once_with(slice(123456789, None, None))
        mock_sliced_string.encode.assert_called_once_with(mocker.sentinel.encoding, mocker.sentinel.str_errors)
        assert packet is mocker.sentinel.packet
        assert remaining_data == b"Trailing data + Hello World !"

    def test____incremental_deserialize____translate_unicode_decode_errors(
        self,
        mock_decoder: MagicMock,
        mock_json_parser: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def raw_parse_side_effect() -> Generator[None, bytes, tuple[bytes, bytes]]:
            data = yield
            assert data is mocker.sentinel.data
            return mock_bytes, mocker.sentinel.remaining_data

        serializer: JSONSerializer[Any, Any] = JSONSerializer(
            encoding=mocker.sentinel.encoding,
            unicode_errors=mocker.sentinel.str_errors,
        )
        mock_bytes = mocker.NonCallableMagicMock()
        mock_bytes.decode.side_effect = UnicodeDecodeError("some encoding", b"invalid data", 0, 2, "Bad encoding ?")
        mock_json_parser.side_effect = raw_parse_side_effect

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            _ = consumer.send(mocker.sentinel.data)
        exception = exc_info.value

        # Assert
        mock_bytes.decode.assert_called_once()
        mock_decoder.raw_decode.assert_not_called()
        assert exception.remaining_data is mocker.sentinel.remaining_data
        assert exception.__cause__ is mock_bytes.decode.side_effect
        assert exception.error_info == {"data": mock_bytes}

    def test____incremental_deserialize____translate_json_decode_errors(
        self,
        mock_decoder: MagicMock,
        mock_json_parser: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from json import JSONDecodeError

        def raw_parse_side_effect() -> Generator[None, bytes, tuple[bytes, bytes]]:
            data = yield
            assert data is mocker.sentinel.data
            return mock_bytes, mocker.sentinel.remaining_data

        serializer: JSONSerializer[Any, Any] = JSONSerializer(
            encoding=mocker.sentinel.encoding,
            unicode_errors=mocker.sentinel.str_errors,
        )
        mock_bytes = mocker.NonCallableMagicMock()
        mock_decoder.raw_decode.side_effect = JSONDecodeError("Invalid payload", "invalid\ndocument", 8)
        mock_json_parser.side_effect = raw_parse_side_effect

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            _ = consumer.send(mocker.sentinel.data)
        exception = exc_info.value

        # Assert
        mock_bytes.decode.assert_called_once()
        mock_decoder.raw_decode.assert_called_once()
        assert exception.remaining_data is mocker.sentinel.remaining_data
        assert exception.__cause__ is mock_decoder.raw_decode.side_effect
        assert exception.error_info == {
            "document": "invalid\ndocument",
            "position": 8,
            "lineno": 2,
            "colno": 1,
        }
