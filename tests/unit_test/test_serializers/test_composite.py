from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, assert_type

from easynetwork.serializers.composite import (
    StapledBufferedIncrementalPacketSerializer,
    StapledIncrementalPacketSerializer,
    StapledPacketSerializer,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStapledPacketSerializer:
    def test____init_subclass____cannot_be_subclassed(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^StapledPacketSerializer cannot be subclassed$"):

            class Subclass(StapledPacketSerializer[Any, Any]):  # type: ignore[misc]
                ...

    def test____dunder_new____instance_and_type_hint(self) -> None:
        # Arrange
        from easynetwork.serializers import JSONSerializer, PickleSerializer, StringLineSerializer

        ### PickleSerializer is a one-shot serializer
        ### JSONSerializer is an incremental serializer
        ### StringLineSerializer is a buffered incremental serializer
        #
        # Act
        stapled_serializer = StapledPacketSerializer(
            PickleSerializer(),
            PickleSerializer(),
        )
        stapled_incremental_serializer = StapledPacketSerializer(
            JSONSerializer(),
            JSONSerializer(),
        )
        stapled_buffered_incremental_serializer = StapledPacketSerializer(
            StringLineSerializer(),
            StringLineSerializer(),
        )

        # Assert
        #
        ## These statements are only understandable by mypy
        ## assert_type() is a no-op at runtime
        assert_type(stapled_serializer, StapledPacketSerializer[Any, Any])
        assert_type(stapled_incremental_serializer, StapledIncrementalPacketSerializer[Any, Any])
        assert_type(stapled_buffered_incremental_serializer, StapledBufferedIncrementalPacketSerializer[str, str, bytearray])

        assert type(stapled_serializer) is StapledPacketSerializer
        assert type(stapled_incremental_serializer) is StapledIncrementalPacketSerializer
        assert type(stapled_buffered_incremental_serializer) is StapledBufferedIncrementalPacketSerializer

    def test____serialize____use_sent_packet_serializer(
        self,
        mock_serializer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sent_packet_serializer = mock_serializer_factory()
        mock_received_packet_serializer = mock_serializer_factory()

        mock_sent_packet_serializer.configure_mock(**{"serialize.return_value": mocker.sentinel.serialized_packet_data})
        stapled_serializer: StapledPacketSerializer[Any, Any] = StapledPacketSerializer(
            sent_packet_serializer=mock_sent_packet_serializer,
            received_packet_serializer=mock_received_packet_serializer,
        )
        assert stapled_serializer.sent_packet_serializer is mock_sent_packet_serializer

        # Act
        data = stapled_serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_sent_packet_serializer.serialize.assert_called_once_with(mocker.sentinel.packet)
        mock_received_packet_serializer.serialize.assert_not_called()
        assert data is mocker.sentinel.serialized_packet_data

    def test____deserialize____use_received_packet_serializer(
        self,
        mock_serializer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sent_packet_serializer = mock_serializer_factory()
        mock_received_packet_serializer = mock_serializer_factory()

        mock_received_packet_serializer.configure_mock(**{"deserialize.return_value": mocker.sentinel.packet})
        stapled_serializer: StapledPacketSerializer[Any, Any] = StapledPacketSerializer(
            sent_packet_serializer=mock_sent_packet_serializer,
            received_packet_serializer=mock_received_packet_serializer,
        )
        assert stapled_serializer.received_packet_serializer is mock_received_packet_serializer

        # Act
        packet = stapled_serializer.deserialize(mocker.sentinel.serialized_packet_data)

        # Assert
        mock_received_packet_serializer.deserialize.assert_called_once_with(mocker.sentinel.serialized_packet_data)
        mock_sent_packet_serializer.deserialize.assert_not_called()
        assert packet is mocker.sentinel.packet


class TestStapledIncrementalPacketSerializer:
    def test____init_subclass____cannot_be_subclassed(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^StapledIncrementalPacketSerializer cannot be subclassed$"):

            class Subclass(StapledIncrementalPacketSerializer[Any, Any]):  # type: ignore[misc]
                ...

    @pytest.mark.parametrize(
        "method",
        [
            "serialize",
            "deserialize",
        ],
    )
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange

        # Act & Assert
        assert getattr(StapledIncrementalPacketSerializer, method) is getattr(StapledPacketSerializer, method)

    def test____dunder_new____instance_and_type_hint(self) -> None:
        # Arrange
        from easynetwork.serializers import JSONSerializer, StringLineSerializer

        ### JSONSerializer is an incremental serializer
        ### StringLineSerializer is a buffered incremental serializer
        #
        # Act
        stapled_incremental_serializer = StapledIncrementalPacketSerializer(
            JSONSerializer(),
            JSONSerializer(),
        )
        stapled_buffered_incremental_serializer = StapledIncrementalPacketSerializer(
            StringLineSerializer(),
            StringLineSerializer(),
        )

        # Assert
        #
        ## These statements are only understandable by mypy
        ## assert_type() is a no-op at runtime
        assert_type(stapled_incremental_serializer, StapledIncrementalPacketSerializer[Any, Any])
        assert_type(stapled_buffered_incremental_serializer, StapledBufferedIncrementalPacketSerializer[str, str, bytearray])

        assert type(stapled_incremental_serializer) is StapledIncrementalPacketSerializer
        assert type(stapled_buffered_incremental_serializer) is StapledBufferedIncrementalPacketSerializer

    def test____incremental_serialize____use_sent_packet_serializer(
        self,
        mock_incremental_serializer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sent_packet_serializer = mock_incremental_serializer_factory()
        mock_received_packet_serializer = mock_incremental_serializer_factory()

        mock_sent_packet_serializer.configure_mock(
            **{"incremental_serialize.return_value": mocker.sentinel.serialized_packet_generator}
        )
        stapled_serializer: StapledIncrementalPacketSerializer[Any, Any] = StapledIncrementalPacketSerializer(
            sent_packet_serializer=mock_sent_packet_serializer,
            received_packet_serializer=mock_received_packet_serializer,
        )
        assert stapled_serializer.sent_packet_serializer is mock_sent_packet_serializer

        # Act
        generator = stapled_serializer.incremental_serialize(mocker.sentinel.packet)

        # Assert
        mock_sent_packet_serializer.incremental_serialize.assert_called_once_with(mocker.sentinel.packet)
        mock_received_packet_serializer.incremental_serialize.assert_not_called()
        assert generator is mocker.sentinel.serialized_packet_generator

    def test____incremental_deserialize____use_received_packet_serializer(
        self,
        mock_incremental_serializer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sent_packet_serializer = mock_incremental_serializer_factory()
        mock_received_packet_serializer = mock_incremental_serializer_factory()

        mock_received_packet_serializer.configure_mock(
            **{"incremental_deserialize.return_value": mocker.sentinel.received_data_generator}
        )
        stapled_serializer: StapledIncrementalPacketSerializer[Any, Any] = StapledIncrementalPacketSerializer(
            sent_packet_serializer=mock_sent_packet_serializer,
            received_packet_serializer=mock_received_packet_serializer,
        )
        assert stapled_serializer.received_packet_serializer is mock_received_packet_serializer

        # Act
        generator = stapled_serializer.incremental_deserialize()

        # Assert
        mock_received_packet_serializer.incremental_deserialize.assert_called_once_with()
        mock_sent_packet_serializer.incremental_deserialize.assert_not_called()
        assert generator is mocker.sentinel.received_data_generator


class TestStapledBufferedIncrementalPacketSerializer:
    def test____init_subclass____cannot_be_subclassed(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^StapledBufferedIncrementalPacketSerializer cannot be subclassed$"):

            class Subclass(StapledBufferedIncrementalPacketSerializer[Any, Any, Any]):  # type: ignore[misc]
                ...

    @pytest.mark.parametrize(
        "method",
        [
            "serialize",
            "deserialize",
            "incremental_serialize",
            "incremental_deserialize",
        ],
    )
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange

        # Act & Assert
        assert getattr(StapledBufferedIncrementalPacketSerializer, method) is getattr(StapledIncrementalPacketSerializer, method)

    def test____dunder_new____instance_and_type_hint(self) -> None:
        # Arrange
        from easynetwork.serializers import StringLineSerializer

        ### StringLineSerializer is a buffered incremental serializer
        #
        # Act
        stapled_buffered_incremental_serializer = StapledBufferedIncrementalPacketSerializer(
            StringLineSerializer(),
            StringLineSerializer(),
        )

        # Assert
        #
        ## These statements are only understandable by mypy
        ## assert_type() is a no-op at runtime
        assert_type(stapled_buffered_incremental_serializer, StapledBufferedIncrementalPacketSerializer[str, str, bytearray])

        assert type(stapled_buffered_incremental_serializer) is StapledBufferedIncrementalPacketSerializer

    def test____create_deserializer_buffer____use_received_packet_serializer(
        self,
        mock_buffered_incremental_serializer_factory: Callable[[], MagicMock],
        mock_incremental_serializer_factory: Callable[[], MagicMock],
    ) -> None:
        # Arrange
        mock_received_packet_serializer = mock_buffered_incremental_serializer_factory()

        stapled_serializer: StapledBufferedIncrementalPacketSerializer[Any, Any, memoryview] = (
            StapledBufferedIncrementalPacketSerializer(
                sent_packet_serializer=mock_incremental_serializer_factory(),
                received_packet_serializer=mock_received_packet_serializer,
            )
        )
        assert stapled_serializer.received_packet_serializer is mock_received_packet_serializer

        # Act
        buffer = stapled_serializer.create_deserializer_buffer(1024)

        # Assert
        mock_received_packet_serializer.create_deserializer_buffer.assert_called_once_with(1024)
        assert len(buffer) == 1024

    def test____buffered_incremental_deserialize____use_received_packet_serializer(
        self,
        mock_buffered_incremental_serializer_factory: Callable[[], MagicMock],
        mock_incremental_serializer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_received_packet_serializer = mock_buffered_incremental_serializer_factory()

        mock_received_packet_serializer.configure_mock(
            **{"buffered_incremental_deserialize.return_value": mocker.sentinel.received_data_generator}
        )
        stapled_serializer: StapledBufferedIncrementalPacketSerializer[Any, Any, memoryview] = (
            StapledBufferedIncrementalPacketSerializer(
                sent_packet_serializer=mock_incremental_serializer_factory(),
                received_packet_serializer=mock_received_packet_serializer,
            )
        )
        assert stapled_serializer.received_packet_serializer is mock_received_packet_serializer
        buffer = memoryview(bytearray(1024))

        # Act
        generator = stapled_serializer.buffered_incremental_deserialize(buffer)

        # Assert
        mock_received_packet_serializer.buffered_incremental_deserialize.assert_called_once_with(buffer)
        assert generator is mocker.sentinel.received_data_generator
