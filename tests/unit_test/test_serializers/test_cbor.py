from __future__ import annotations

from typing import TYPE_CHECKING, Any, final

from easynetwork.lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from easynetwork.serializers.cbor import CBORDecoderConfig, CBOREncoderConfig, CBORSerializer

import pytest

from .._utils import mock_import_module_not_found
from .base import BaseSerializerConfigInstanceCheck

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
@pytest.mark.feature_cbor
class TestCBORSerializer(BaseSerializerConfigInstanceCheck):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[CBORSerializer]:
        return CBORSerializer

    @pytest.fixture(params=["encoder", "decoder"])
    @staticmethod
    def config_param(request: Any) -> tuple[str, str]:
        name: str = request.param
        return (name, f"CBOR{name.capitalize()}Config")

    @pytest.fixture
    @staticmethod
    def mock_encoder(mocker: MockerFixture) -> MagicMock:
        from cbor2 import CBOREncoder

        return mocker.NonCallableMagicMock(spec=CBOREncoder)

    @pytest.fixture
    @staticmethod
    def mock_encoder_cls(mocker: MockerFixture, mock_encoder: MagicMock) -> MagicMock:
        return mocker.patch("cbor2.CBOREncoder", autospec=True, return_value=mock_encoder)

    @pytest.fixture
    @staticmethod
    def mock_decoder(mocker: MockerFixture) -> MagicMock:
        from cbor2 import CBORDecoder

        return mocker.NonCallableMagicMock(spec=CBORDecoder)

    @pytest.fixture
    @staticmethod
    def mock_decoder_cls(mocker: MockerFixture, mock_decoder: MagicMock) -> MagicMock:
        return mocker.patch("cbor2.CBORDecoder", autospec=True, return_value=mock_decoder)

    @pytest.fixture
    @staticmethod
    def mock_file(mocker: MockerFixture) -> MagicMock:
        from io import BytesIO

        return mocker.NonCallableMagicMock(spec=BytesIO)

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_encoder_config=={boolean}")
    @staticmethod
    def encoder_config(request: Any, mocker: MockerFixture) -> CBOREncoderConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return CBOREncoderConfig(
            datetime_as_timestamp=mocker.sentinel.datetime_as_timestamp,
            timezone=mocker.sentinel.timezone,
            value_sharing=mocker.sentinel.value_sharing,
            default=mocker.sentinel.object_default,
            canonical=mocker.sentinel.canonical,
            date_as_datetime=mocker.sentinel.date_as_datetime,
            string_referencing=mocker.sentinel.string_referencing,
        )

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_decoder_config=={boolean}")
    @staticmethod
    def decoder_config(request: Any, mocker: MockerFixture) -> CBORDecoderConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return CBORDecoderConfig(
            object_hook=mocker.sentinel.object_hook,
            tag_hook=mocker.sentinel.tag_hook,
            str_errors=mocker.sentinel.str_errors,
        )

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
        from easynetwork.serializers.base_stream import FileBasedPacketSerializer

        # Act & Assert
        assert getattr(CBORSerializer, method) is getattr(FileBasedPacketSerializer, method)

    @pytest.mark.parametrize("limit", [147258369, None], ids=lambda p: f"limit=={p}")
    def test____properties____right_values(self, debug_mode: bool, limit: int | None) -> None:
        # Arrange

        # Act
        if limit is None:
            serializer = CBORSerializer(debug=debug_mode)
        else:
            serializer = CBORSerializer(debug=debug_mode, limit=limit)

        # Assert
        assert serializer.debug is debug_mode
        if limit is None:
            assert serializer.buffer_limit == DEFAULT_SERIALIZER_LIMIT
        else:
            assert serializer.buffer_limit == limit

    @pytest.mark.parametrize("limit", [0, -42], ids=lambda p: f"limit=={p}")
    def test____dunder_init____invalid_limit(self, limit: int) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^limit must be a positive integer$"):
            CBORSerializer(limit=limit)

    def test____dump_to_file____with_config(
        self,
        encoder_config: CBOREncoderConfig | None,
        mock_encoder_cls: MagicMock,
        mock_encoder: MagicMock,
        mock_file: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: CBORSerializer = CBORSerializer(encoder_config=encoder_config)
        mock_encoder.encode.return_value = None

        # Act
        serializer.dump_to_file(mocker.sentinel.packet, mock_file)

        # Assert
        mock_encoder_cls.assert_called_once_with(
            mock_file,
            datetime_as_timestamp=mocker.sentinel.datetime_as_timestamp if encoder_config is not None else False,
            timezone=mocker.sentinel.timezone if encoder_config is not None else None,
            value_sharing=mocker.sentinel.value_sharing if encoder_config is not None else False,
            default=mocker.sentinel.object_default if encoder_config is not None else None,
            canonical=mocker.sentinel.canonical if encoder_config is not None else False,
            date_as_datetime=mocker.sentinel.date_as_datetime if encoder_config is not None else False,
            string_referencing=mocker.sentinel.string_referencing if encoder_config is not None else False,
        )
        mock_encoder.encode.assert_called_once_with(mocker.sentinel.packet)

    def test____load_from_file____with_config(
        self,
        decoder_config: CBORDecoderConfig | None,
        mock_decoder_cls: MagicMock,
        mock_decoder: MagicMock,
        mock_file: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: CBORSerializer = CBORSerializer(decoder_config=decoder_config)
        mock_decoder.decode.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.load_from_file(mock_file)

        # Assert
        mock_decoder_cls.assert_called_once_with(
            mock_file,
            object_hook=mocker.sentinel.object_hook if decoder_config is not None else None,
            tag_hook=mocker.sentinel.tag_hook if decoder_config is not None else None,
            str_errors=mocker.sentinel.str_errors if decoder_config is not None else "strict",
        )
        mock_decoder.decode.assert_called_once_with()
        assert packet is mocker.sentinel.packet


class TestCBORSerializerDependencies:
    def test____dunder_init____cbor2_missing(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_import: MagicMock = mock_import_module_not_found({"cbor2"}, mocker)

        # Act
        with pytest.raises(ModuleNotFoundError) as exc_info:
            try:
                _ = CBORSerializer()
            finally:
                mocker.stop(mock_import)

        # Assert
        mock_import.assert_any_call("cbor2", mocker.ANY, mocker.ANY, None, 0)
        assert exc_info.value.args[0] == "cbor dependencies are missing. Consider adding 'cbor' extra"
        assert exc_info.value.__notes__ == ['example: pip install "easynetwork[cbor]"']
        assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)
