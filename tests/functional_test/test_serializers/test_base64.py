# mypy: disable_error_code=override

from __future__ import annotations

import random
from typing import Any, Literal, final

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.wrapper.base64 import Base64EncoderSerializer

import pytest

from .base import BaseTestIncrementalSerializer, NoSerialization


def generate_key_from_string(s: str) -> bytes:
    import base64
    import hashlib

    return base64.urlsafe_b64encode(hashlib.sha256(s.encode("utf-8")).digest())


SAMPLES = [
    (b"a", "one ascii byte"),
    (b"\xcc", "one unicode byte"),
    (random.randbytes(255), "255 random generated bytes"),
]


class BaseTestBase64EncoderSerializer(BaseTestIncrementalSerializer):
    #### Serializers

    @pytest.fixture(scope="class", params=["standard", "urlsafe"])
    @staticmethod
    def alphabet(request: pytest.FixtureRequest) -> Literal["standard", "urlsafe"]:
        return getattr(request, "param")

    @pytest.fixture(scope="class")
    @classmethod
    def serializer(
        cls,
        checksum: bool | bytes,
        alphabet: Literal["standard", "urlsafe"],
    ) -> Base64EncoderSerializer[bytes]:
        return Base64EncoderSerializer(NoSerialization(), alphabet=alphabet, checksum=checksum)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(serializer: Base64EncoderSerializer[bytes]) -> Base64EncoderSerializer[bytes]:
        return serializer

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization(serializer: Base64EncoderSerializer[bytes]) -> Base64EncoderSerializer[bytes]:
        return serializer

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @classmethod
    def expected_complete_data(
        cls,
        packet_to_serialize: bytes,
        checksum: bool | bytes,
        alphabet: Literal["standard", "urlsafe"],
    ) -> bytes:
        import base64
        import hashlib
        import hmac

        if checksum:
            if isinstance(checksum, bytes):
                key = base64.urlsafe_b64decode(checksum)
                packet_to_serialize += hmac.digest(key, packet_to_serialize, "sha256")
            else:
                packet_to_serialize += hashlib.sha256(packet_to_serialize).digest()

        if alphabet == "standard":
            return base64.standard_b64encode(packet_to_serialize)
        return base64.urlsafe_b64encode(packet_to_serialize)

    #### Incremental Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_joined_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data + b"\r\n"

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(expected_complete_data: bytes) -> bytes:
        return expected_complete_data

    #### Incremental Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data_for_incremental_deserialize(complete_data: bytes) -> bytes:
        return complete_data + b"\r\n"

    #### Invalid data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data(complete_data: bytes) -> bytes:
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


@final
class TestBase64EncoderSerializerChecksum(BaseTestBase64EncoderSerializer):
    @pytest.fixture(scope="class", params=[False, True], ids=lambda boolean: f"checksum=={boolean}")
    @staticmethod
    def checksum(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param")


@final
class TestBase64EncoderSerializerWithKey(BaseTestBase64EncoderSerializer):
    @classmethod
    def get_signing_key(cls) -> bytes:
        return generate_key_from_string("key")

    @pytest.fixture(scope="class")
    @classmethod
    def checksum(cls) -> bytes:
        return cls.get_signing_key()

    def test____generate_key____create_url_safe_base64_encoded_bytes(self) -> None:
        # Arrange
        from base64 import urlsafe_b64decode

        # Act
        key = Base64EncoderSerializer.generate_key()

        # Assert
        assert isinstance(key, bytes)
        assert len(urlsafe_b64decode(key)) == 32

    def test____dunder_init____invalid_key____not_base64_encoded(self) -> None:
        # Arrange
        import base64
        import binascii

        key: bytes = base64.urlsafe_b64encode(random.randbytes(32))[5:12]  # Removed a lot of data :)

        # Act
        with pytest.raises(ValueError, match=r"^signing key must be 32 url-safe base64-encoded bytes\.$") as exc_info:
            _ = Base64EncoderSerializer(NoSerialization(), checksum=key)
        exception = exc_info.value

        # Assert
        assert isinstance(exception.__cause__, binascii.Error)

    def test____dunder_init____invalid_key____invalid_base64_encoded_byte_length(self) -> None:
        # Arrange
        import base64
        import binascii

        key: bytes = base64.urlsafe_b64encode(random.randbytes(4))

        # Act
        with pytest.raises(ValueError, match=r"^signing key must be 32 url-safe base64-encoded bytes\.$") as exc_info:
            _ = Base64EncoderSerializer(NoSerialization(), checksum=key)
        exception = exc_info.value

        # Assert
        assert not isinstance(exception.__cause__, binascii.Error)

    def test____deserialize____invalid_signature(
        self,
        serializer: Base64EncoderSerializer[bytes],
        packet_to_serialize: bytes,
        expected_complete_data: bytes,
    ) -> None:
        # Arrange
        import base64
        import hmac

        assert generate_key_from_string("another_key") != self.get_signing_key()
        data_with_another_signature = base64.urlsafe_b64encode(
            packet_to_serialize + hmac.digest(b"another_key", packet_to_serialize, "sha256")
        )
        assert data_with_another_signature != expected_complete_data

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(data_with_another_signature)
        exception = exc_info.value

        # Assert
        assert exception.__cause__ is None
