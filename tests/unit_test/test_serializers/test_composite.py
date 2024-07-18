from __future__ import annotations

from typing import Any, assert_type

from easynetwork.serializers.composite import (
    StapledBufferedIncrementalPacketSerializer,
    StapledIncrementalPacketSerializer,
    StapledPacketSerializer,
)


class TestStapledPacketSerializer:
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


class TestStapledIncrementalPacketSerializer:
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


class TestStapledBufferedIncrementalPacketSerializer:
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
