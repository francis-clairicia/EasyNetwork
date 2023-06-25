# -*- coding: utf-8 -*

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.wrapper.base64 import Base64EncodedSerializer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestBase64EncodedSerializer:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_b64encode(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("base64.urlsafe_b64encode", autospec=True)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_b64decode(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("base64.urlsafe_b64decode", autospec=True)

    @pytest.mark.parametrize("method", ["incremental_serialize", "incremental_deserialize"])
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange
        from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer

        # Act & Assert
        assert getattr(Base64EncodedSerializer, method) is getattr(AutoSeparatedPacketSerializer, method)

    def test____serialize____encode_previously_serialized_data(
        self,
        mock_serializer: MagicMock,
        mock_b64encode: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: Base64EncodedSerializer[Any, Any] = Base64EncodedSerializer(mock_serializer)
        mock_serializer.serialize.return_value = mocker.sentinel.data_not_encoded
        mock_b64encode.return_value = mocker.sentinel.data_encoded

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_serializer.serialize.assert_called_once_with(mocker.sentinel.packet)
        mock_b64encode.assert_called_once_with(mocker.sentinel.data_not_encoded)
        assert data is mocker.sentinel.data_encoded

    def test____deserialize____decode_token_then_call_subsequent_deserialize(
        self,
        mock_serializer: MagicMock,
        mock_b64decode: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: Base64EncodedSerializer[Any, Any] = Base64EncodedSerializer(mock_serializer)
        mock_b64decode.return_value = mocker.sentinel.data_not_encoded
        mock_serializer.deserialize.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(mocker.sentinel.data_encoded)

        # Assert
        mock_b64decode.assert_called_once_with(mocker.sentinel.data_encoded)
        mock_serializer.deserialize.assert_called_once_with(mocker.sentinel.data_not_encoded)
        assert packet is mocker.sentinel.packet

    def test____deserialize____translate_binascii_errors(
        self,
        mock_serializer: MagicMock,
        mock_b64decode: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import binascii

        serializer: Base64EncodedSerializer[Any, Any] = Base64EncodedSerializer(mock_serializer)
        mock_b64decode.side_effect = binascii.Error()

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(mocker.sentinel.data_encoded)
        exception = exc_info.value

        # Assert
        mock_b64decode.assert_called_once_with(mocker.sentinel.data_encoded)
        mock_serializer.deserialize.assert_not_called()
        assert exception.__context__ is mock_b64decode.side_effect
        assert exception.__cause__ is None
