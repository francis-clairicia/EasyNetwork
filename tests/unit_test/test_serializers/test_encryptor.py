# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.wrapper.encryptor import EncryptorSerializer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.feature_encryption
class TestEncryptorSerializer:
    @pytest.fixture
    @staticmethod
    def mock_fernet(mocker: MockerFixture) -> MagicMock:
        from cryptography.fernet import Fernet

        return mocker.NonCallableMagicMock(spec=Fernet)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_fernet_cls(mocker: MockerFixture, mock_fernet: MagicMock) -> MagicMock:
        return mocker.patch("cryptography.fernet.Fernet", return_value=mock_fernet)

    @pytest.mark.parametrize("method", ["incremental_serialize", "incremental_deserialize"])
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange
        from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer

        # Act & Assert
        assert getattr(EncryptorSerializer, method) is getattr(AutoSeparatedPacketSerializer, method)

    def test____dunder_init____fernet_creation(
        self,
        mock_serializer: MagicMock,
        mock_fernet_cls: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = EncryptorSerializer(mock_serializer, key=mocker.sentinel.key)

        # Assert
        mock_fernet_cls.assert_called_once_with(mocker.sentinel.key)

    def test____serialize____encrypt_data(
        self,
        mock_serializer: MagicMock,
        mock_fernet: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: EncryptorSerializer[Any, Any] = EncryptorSerializer(mock_serializer, key=mocker.sentinel.key)
        mock_serializer.serialize.return_value = mocker.sentinel.data_before_encryption
        mock_fernet.encrypt.return_value = mocker.sentinel.encrypted_data

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_serializer.serialize.assert_called_once_with(mocker.sentinel.packet)
        mock_fernet.encrypt.assert_called_once_with(mocker.sentinel.data_before_encryption)
        assert data is mocker.sentinel.encrypted_data

    def test____deserialize____decrypt_data(
        self,
        mock_serializer: MagicMock,
        mock_fernet: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: EncryptorSerializer[Any, Any] = EncryptorSerializer(
            mock_serializer,
            key=mocker.sentinel.key,
            token_ttl=mocker.sentinel.token_ttl,
        )
        mock_fernet.decrypt.return_value = mocker.sentinel.data_after_decryption
        mock_serializer.deserialize.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(mocker.sentinel.encrypted_data)

        # Assert
        mock_fernet.decrypt.assert_called_once_with(mocker.sentinel.encrypted_data, ttl=mocker.sentinel.token_ttl)
        mock_serializer.deserialize.assert_called_once_with(mocker.sentinel.data_after_decryption)
        assert packet is mocker.sentinel.packet

    def test____deserialize____translate_fernet_errors(
        self,
        mock_serializer: MagicMock,
        mock_fernet: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from cryptography.fernet import InvalidToken

        serializer: EncryptorSerializer[Any, Any] = EncryptorSerializer(
            mock_serializer,
            key=mocker.sentinel.key,
            token_ttl=mocker.sentinel.token_ttl,
        )
        mock_fernet.decrypt.side_effect = InvalidToken()

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(mocker.sentinel.encrypted_data)
        exception = exc_info.value

        # Assert
        mock_fernet.decrypt.assert_called_once_with(mocker.sentinel.encrypted_data, ttl=mocker.sentinel.token_ttl)
        mock_serializer.deserialize.assert_not_called()
        assert exception.__context__ is mock_fernet.decrypt.side_effect
        assert exception.__cause__ is None
        assert exception.error_info is None
