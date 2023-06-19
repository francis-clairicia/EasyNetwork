# -*- coding: utf-8 -*-
# mypy: disable_error_code=override

from __future__ import annotations

from typing import Any, Callable, final

from easynetwork.serializers.wrapper.encryptor import EncryptorSerializer

import pytest

from .base import BaseTestIncrementalSerializer, NoSerialization
from .test_base64 import SAMPLES, generate_key_from_string


@final
@pytest.mark.feature_encryption
class TestEncryptorSerializer(BaseTestIncrementalSerializer):
    #### Serializers

    KEY = generate_key_from_string("key")

    @pytest.fixture(scope="class")
    @classmethod
    def serializer(cls) -> EncryptorSerializer[bytes, bytes]:
        return EncryptorSerializer(NoSerialization(), key=cls.KEY)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(serializer: EncryptorSerializer[bytes, bytes]) -> EncryptorSerializer[bytes, bytes]:
        return serializer

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization(serializer: EncryptorSerializer[bytes, bytes]) -> EncryptorSerializer[bytes, bytes]:
        return serializer

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(cls, packet_to_serialize: bytes) -> Callable[[bytes], None]:
        from cryptography.fernet import Fernet

        fernet = Fernet(cls.KEY)

        def assert_encrypted(data: bytes) -> None:
            assert fernet.decrypt(data) == packet_to_serialize

        return assert_encrypted

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_joined_data(cls, packet_to_serialize: bytes) -> Callable[[bytes], None]:
        from cryptography.fernet import Fernet

        fernet = Fernet(cls.KEY)

        def assert_encrypted(data: bytes) -> None:
            assert data.endswith(b"\r\n")
            assert fernet.decrypt(data.removesuffix(b"\r\n")) == packet_to_serialize

        return assert_encrypted

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @classmethod
    def complete_data(cls, packet_to_serialize: bytes) -> bytes:
        from cryptography.fernet import Fernet

        return Fernet(cls.KEY).encrypt_at_time(packet_to_serialize, 0)

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes) -> bytes:
        return complete_data + b"\r\n"

    #### Invalid data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data(complete_data: bytes) -> bytes:
        if not complete_data:
            pytest.skip("empty bytes")
        return complete_data[:-1]  # Remove one byte at last will break the padding

    @pytest.fixture
    @staticmethod
    def invalid_partial_data() -> bytes:
        pytest.skip("Cannot be tested")

    #### Other

    @pytest.fixture(scope="class")
    @staticmethod
    def oneshot_extra_data() -> bytes:
        pytest.skip("Does not recognize extra data")

    def test____generate_key____create_url_safe_base64_encoded_bytes(self) -> None:
        # Arrange
        from base64 import urlsafe_b64decode

        # Act
        key = EncryptorSerializer.generate_key()

        # Assert
        assert isinstance(key, bytes)
        assert len(urlsafe_b64decode(key)) == 32
