from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError, LimitOverrunError
from easynetwork.lowlevel.constants import DEFAULT_SERIALIZER_LIMIT as DEFAULT_LIMIT
from easynetwork.serializers.json import JSONDecoderConfig, JSONEncoderConfig, JSONSerializer, _JSONParser
from easynetwork.serializers.tools import GeneratorStreamReader

import pytest

from ...tools import send_return
from .base import BaseSerializerConfigInstanceCheck

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestJSONSerializer(BaseSerializerConfigInstanceCheck):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[JSONSerializer]:
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

        mock_decoder = mocker.NonCallableMagicMock(spec=JSONDecoder)
        del mock_decoder.raw_decode  # JSONSeralizer must never use it
        return mock_decoder

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

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"use_lines=={boolean}")
    @staticmethod
    def use_lines(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param")

    @pytest.fixture
    @staticmethod
    def mock_json_parser(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_JSONParser, "raw_parse", autospec=True)

    @pytest.fixture
    @staticmethod
    def mock_generator_stream_reader(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=GeneratorStreamReader)

    @pytest.fixture
    @staticmethod
    def mock_generator_stream_reader_cls(mock_generator_stream_reader: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(f"{JSONSerializer.__module__}.GeneratorStreamReader", return_value=mock_generator_stream_reader)

    def test____properties____right_values(self, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer = JSONSerializer(debug=debug_mode, limit=123456789)

        # Assert
        assert serializer.debug is debug_mode
        assert serializer.buffer_limit == 123456789

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
            indent=None,
            separators=(",", ":"),
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

    @pytest.mark.parametrize("limit", [0, -42], ids=lambda p: f"limit=={p}")
    def test____dunder_init____invalid_limit(self, limit: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^limit must be a positive integer$"):
            _ = JSONSerializer(limit=limit)

    def test____serialize____encode_packet(
        self,
        mock_encoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer = JSONSerializer()
        mock_encoder.encode.return_value = '{"data":42}'

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_encoder.encode.assert_called_once_with(mocker.sentinel.packet)
        assert data == b'{"data":42}'

    @pytest.mark.parametrize("value", [b'{"data":42}', b"[4]", b'"string"'])
    def test____incremental_serialize____encode_packet____with_frames(
        self,
        value: bytes,
        use_lines: bool,
        mock_encoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer = JSONSerializer(use_lines=use_lines)
        mock_encoder.encode.return_value = value.decode()

        # Act
        chunks = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_encoder.encode.assert_called_once_with(mocker.sentinel.packet)
        if use_lines:
            assert chunks == [value + b"\n"]
        else:
            assert chunks == [value]

    @pytest.mark.parametrize("value", [b"12345", b"true", b"false", b"null"])
    def test____incremental_serialize____encode_packet____plain_value(
        self,
        value: bytes,
        use_lines: bool,
        mock_encoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer = JSONSerializer(use_lines=use_lines)
        mock_encoder.encode.return_value = value.decode()

        # Act
        chunks = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_encoder.encode.assert_called_once_with(mocker.sentinel.packet)
        assert chunks == [value + b"\n"]

    def test____deserialize____decode_data(
        self,
        mock_decoder: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: JSONSerializer = JSONSerializer()
        data = b'{"data": 42}'
        mock_decoder.decode.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(data)

        # Assert
        mock_decoder.decode.assert_called_once_with(data.decode())
        assert packet is mocker.sentinel.packet

    def test____deserialize____translate_unicode_decode_errors(
        self,
        mock_decoder: MagicMock,
        debug_mode: bool,
    ) -> None:
        # Arrange
        serializer: JSONSerializer = JSONSerializer(encoding="utf-8", debug=debug_mode)
        data = "é".encode("latin-1")

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(data)
        exception = exc_info.value

        # Assert
        mock_decoder.decode.assert_not_called()
        assert isinstance(exception.__cause__, UnicodeError)
        if debug_mode:
            assert exception.error_info == {"data": data}
        else:
            assert exception.error_info is None

    def test____deserialize____translate_json_decode_errors(
        self,
        mock_decoder: MagicMock,
        debug_mode: bool,
    ) -> None:
        # Arrange
        from json import JSONDecodeError

        serializer: JSONSerializer = JSONSerializer(debug=debug_mode)
        data = b"invalid\ndocument"
        mock_decoder.decode.side_effect = JSONDecodeError("Invalid payload", data.decode(), 8)

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(data)
        exception = exc_info.value

        # Assert
        mock_decoder.decode.assert_called_once()
        assert exception.__cause__ is mock_decoder.decode.side_effect
        if debug_mode:
            assert exception.error_info == {
                "document": data.decode(),
                "position": 8,
                "lineno": 2,
                "colno": 1,
            }
        else:
            assert exception.error_info is None

    def test____incremental_deserialize____parse_and_decode_data(
        self,
        use_lines: bool,
        mock_decoder: MagicMock,
        mock_json_parser: MagicMock,
        mock_generator_stream_reader_cls: MagicMock,
        mock_generator_stream_reader: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def raw_parse_side_effect(*args: Any, **kwargs: Any) -> Generator[None, bytes, tuple[bytes, bytes]]:
            data = yield
            return data, b"Hello World !"

        def reader_read_until_side_effect(*args: Any, **kwargs: Any) -> Generator[None, bytes, bytes]:
            data = yield
            return data

        serializer: JSONSerializer = JSONSerializer(use_lines=use_lines)
        data = b'{"data": 42}'
        mock_decoder.decode.return_value = mocker.sentinel.packet
        mock_json_parser.side_effect = raw_parse_side_effect
        mock_generator_stream_reader.read_until.side_effect = reader_read_until_side_effect
        mock_generator_stream_reader.read_all.return_value = b"Hello World !"

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        packet, remaining_data = send_return(consumer, data)

        # Assert
        if use_lines:
            mock_json_parser.assert_not_called()
            mock_generator_stream_reader_cls.assert_called_once_with()
            mock_generator_stream_reader.read_until.assert_called_once_with(b"\n", limit=DEFAULT_LIMIT, keep_end=False)
            mock_generator_stream_reader.read_all.assert_called_once_with()
        else:
            mock_json_parser.assert_called_once_with(limit=DEFAULT_LIMIT)
            mock_generator_stream_reader_cls.assert_not_called()
            mock_generator_stream_reader.read_until.assert_not_called()
            mock_generator_stream_reader.read_all.assert_not_called()
        mock_decoder.decode.assert_called_once_with(data.decode())
        assert packet is mocker.sentinel.packet
        assert remaining_data == b"Hello World !"

    def test____incremental_deserialize____translate_unicode_decode_errors(
        self,
        mock_decoder: MagicMock,
        mock_json_parser: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def raw_parse_side_effect(*args: Any, **kwargs: Any) -> Generator[None, bytes, tuple[bytes, bytes]]:
            data = yield
            return data, mocker.sentinel.remaining_data

        serializer: JSONSerializer = JSONSerializer(
            encoding="utf-8",
            use_lines=False,
            debug=debug_mode,
        )
        data = "é".encode("latin-1")
        mock_json_parser.side_effect = raw_parse_side_effect

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            _ = consumer.send(data)
        exception = exc_info.value

        # Assert
        mock_decoder.decode.assert_not_called()
        assert exception.remaining_data is mocker.sentinel.remaining_data
        assert isinstance(exception.__cause__, UnicodeError)
        if debug_mode:
            assert exception.error_info == {"data": data}
        else:
            assert exception.error_info is None

    def test____incremental_deserialize____translate_json_decode_errors(
        self,
        mock_decoder: MagicMock,
        mock_json_parser: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from json import JSONDecodeError

        def raw_parse_side_effect(*args: Any, **kwargs: Any) -> Generator[None, bytes, tuple[bytes, bytes]]:
            data = yield
            return data, mocker.sentinel.remaining_data

        serializer: JSONSerializer = JSONSerializer(
            use_lines=False,
            debug=debug_mode,
        )
        data = b"invalid\ndocument"
        mock_decoder.decode.side_effect = JSONDecodeError("Invalid payload", data.decode(), 8)
        mock_json_parser.side_effect = raw_parse_side_effect

        # Act
        consumer = serializer.incremental_deserialize()
        next(consumer)
        with pytest.raises(IncrementalDeserializeError) as exc_info:
            _ = consumer.send(data)
        exception = exc_info.value

        # Assert
        mock_decoder.decode.assert_called_once()
        assert exception.remaining_data is mocker.sentinel.remaining_data
        assert exception.__cause__ is mock_decoder.decode.side_effect
        if debug_mode:
            assert exception.error_info == {
                "document": data.decode(),
                "position": 8,
                "lineno": 2,
                "colno": 1,
            }
        else:
            assert exception.error_info is None


class TestJSONParser:
    def test____raw_parse____object_frame(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'{"data"')
        complete, remainder = send_return(consumer, b":42}remainder")

        # Assert
        assert complete == b'{"data":42}'
        assert remainder == b"remainder"

    def test____raw_parse____object_frame____skip_inner_brackets(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b'{"data": {"something": 42}}remainder')

        # Assert
        assert complete == b'{"data": {"something": 42}}'
        assert remainder == b"remainder"

    def test____raw_parse____object_frame____skip_bracket_in_strings(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b'{"data}": "something}"}remainder')

        # Assert
        assert complete == b'{"data}": "something}"}'
        assert remainder == b"remainder"

    def test____raw_parse____object_frame____whitespaces(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'{"data": 42,\n')
        consumer.send(b'"list": [true, false, null]\n')
        complete, remainder = send_return(consumer, b"}\n")

        # Assert
        assert complete == b'{"data": 42,\n"list": [true, false, null]\n}\n'
        assert remainder == b""

    def test____raw_parse____object_frame____leading_whitespace_skip(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b"\t\r\n ")
        consumer.send(b'\n {"data"')
        complete, remainder = send_return(consumer, b":42}remainder")

        # Assert
        assert complete == b'{"data":42}'
        assert remainder == b"remainder"

    def test____raw_parse____object_frame____escaped_quote(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b'{"data\\"":42}remainder')

        # Assert
        assert complete == b'{"data\\"":42}'
        assert remainder == b"remainder"

    def test____raw_parse____object_frame____escaped_quote____partial(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'{"data')
        consumer.send(b'\\"')
        complete, remainder = send_return(consumer, b'":42}remainder')

        # Assert
        assert complete == b'{"data\\"":42}'
        assert remainder == b"remainder"

    def test____raw_parse____list_frame(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'[{"data"')
        consumer.send(b":42}")
        complete, remainder = send_return(consumer, b"]remainder")

        # Assert
        assert complete == b'[{"data":42}]'
        assert remainder == b"remainder"

    def test____raw_parse____list_frame____skip_inner_brackets(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b'[["string"], ["second"]]remainder')

        # Assert
        assert complete == b'[["string"], ["second"]]'
        assert remainder == b"remainder"

    def test____raw_parse____list_frame____skip_bracket_in_strings(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b'["string]", "second]"]remainder')

        # Assert
        assert complete == b'["string]", "second]"]'
        assert remainder == b"remainder"

    def test____raw_parse____list_frame____whitespaces(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'[{\n"data"')
        consumer.send(b': 42,\n "test": true},\n')
        consumer.send(b"null,\n")
        consumer.send(b'"string"\n')
        complete, remainder = send_return(consumer, b"]\n")

        # Assert
        assert complete == b'[{\n"data": 42,\n "test": true},\nnull,\n"string"\n]\n'
        assert remainder == b""

    def test____raw_parse____leading_whitespace_skip(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b"\t\r\n ")
        consumer.send(b'\n [{"data"')
        complete, remainder = send_return(consumer, b":42}]remainder")

        # Assert
        assert complete == b'[{"data":42}]'
        assert remainder == b"remainder"

    def test____raw_parse____list_frame____escaped_quote(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b'["data\\""]remainder')

        # Assert
        assert complete == b'["data\\""]'
        assert remainder == b"remainder"

    def test____raw_parse____list_frame____escaped_quote____partial(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'["data')
        consumer.send(b'\\"')
        complete, remainder = send_return(consumer, b'"]remainder')

        # Assert
        assert complete == b'["data\\""]'
        assert remainder == b"remainder"

    def test____raw_parse____string_frame(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'"data{')
        consumer.send(b"}")
        complete, remainder = send_return(consumer, b'"remainder')

        # Assert
        assert complete == b'"data{}"'
        assert remainder == b"remainder"

    def test____raw_parse____string_frame____leading_whitespace_skip(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b"\t\r\n ")
        consumer.send(b'\n "data')
        complete, remainder = send_return(consumer, b'"remainder')

        # Assert
        assert complete == b'"data"'
        assert remainder == b"remainder"

    def test____raw_parse____string_frame____escaped_quote(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b'"data\\""remainder')

        # Assert
        assert complete == b'"data\\""'
        assert remainder == b"remainder"

    def test____raw_parse____string_frame____escaped_quote____partial(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'"data')
        consumer.send(b'\\"')
        complete, remainder = send_return(consumer, b'"remainder')

        # Assert
        assert complete == b'"data\\""'
        assert remainder == b"remainder"

    def test____raw_parse____string_frame____escape_character(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b'"data')
        consumer.send(b"\\\\")
        complete, remainder = send_return(consumer, b'"remainder')

        # Assert
        assert complete == b'"data\\\\"'
        assert remainder == b"remainder"

    def test____raw_parse____plain_value(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b"tr")
        complete, remainder = send_return(consumer, b"ue\nremainder")

        # Assert
        assert complete == b"true\n"
        assert remainder == b"remainder"

    def test____raw_parse____plain_value____first_character_is_invalid(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        complete, remainder = send_return(consumer, b"\0")

        # Assert
        assert complete == b"\0"
        assert remainder == b""

    def test____raw_parse____plain_value____leading_whitespace_skip(self) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=DEFAULT_LIMIT)
        next(consumer)

        # Act
        consumer.send(b"\t\r\n ")
        consumer.send(b"\n tr")
        complete, remainder = send_return(consumer, b"ue\nremainder")

        # Assert
        assert complete == b"true\n"
        assert remainder == b"remainder"

    @pytest.mark.parametrize("limit", [0, -42], ids=lambda p: f"limit=={p}")
    def test____raw_parse____invalid_limit(self, limit: int) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=limit)

        # Act & Assert
        with pytest.raises(ValueError, match=r"^limit must be a positive integer$"):
            next(consumer)

    @pytest.mark.parametrize(
        ["start_frame", "end_frame"],
        [
            pytest.param(b'{"data":', b'"something"}\n', id="object frame"),
            pytest.param(b'["data",', b'"something"]\n', id="list frame"),
            pytest.param(b'"data', b' something"\n', id="string frame"),
            pytest.param(b"123", b"45\n", id="plain value"),
        ],
    )
    @pytest.mark.parametrize("end_frame_found", [False, True], ids=lambda p: f"end_frame_found=={p}")
    def test____raw_parse____reached_limit(self, start_frame: bytes, end_frame: bytes, end_frame_found: bool) -> None:
        # Arrange
        consumer = _JSONParser.raw_parse(limit=2)
        next(consumer)
        data_to_test = start_frame
        if end_frame_found:
            data_to_test += end_frame

        # Act
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(data_to_test)

        # Assert
        if end_frame_found:
            assert str(exc_info.value) == "JSON object's end frame is found, but chunk is longer than limit"
            assert bytes(exc_info.value.remaining_data) == b"\n"
        else:
            assert str(exc_info.value) == "JSON object's end frame is not found, and chunk exceed the limit"
            assert bytes(exc_info.value.remaining_data) == b""
