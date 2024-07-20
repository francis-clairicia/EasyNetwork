# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Packet serializer composite module."""

from __future__ import annotations

__all__ = [
    "StapledIncrementalPacketSerializer",
    "StapledPacketSerializer",
]

from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Generic, Self, final, overload

from .._typevars import _T_Buffer, _T_ReceivedDTOPacket, _T_SentDTOPacket
from ..lowlevel._final import runtime_final_class
from .abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer, BufferedIncrementalPacketSerializer

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


@final
class StapledPacketSerializer(AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]):
    """
    A :term:`composite serializer` that merges two serializers.
    """

    __slots__ = ("__sent_packet_serializer", "__received_packet_serializer")

    __sent_packet_serializer: AbstractPacketSerializer[_T_SentDTOPacket, Any]
    __received_packet_serializer: AbstractPacketSerializer[Any, _T_ReceivedDTOPacket]

    @overload
    def __new__(
        cls,
        sent_packet_serializer: AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any],
        received_packet_serializer: BufferedIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket, _T_Buffer],
    ) -> StapledBufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, _T_Buffer]: ...

    @overload
    def __new__(
        cls,
        sent_packet_serializer: AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any],
        received_packet_serializer: AbstractIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket],
    ) -> StapledIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]: ...

    @overload
    def __new__(
        cls,
        sent_packet_serializer: AbstractPacketSerializer[_T_SentDTOPacket, Any],
        received_packet_serializer: AbstractPacketSerializer[Any, _T_ReceivedDTOPacket],
    ) -> Self: ...

    def __new__(
        cls,
        sent_packet_serializer: AbstractPacketSerializer[_T_SentDTOPacket, Any],
        received_packet_serializer: AbstractPacketSerializer[Any, _T_ReceivedDTOPacket],
    ) -> Self:
        self: StapledPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]
        match (sent_packet_serializer, received_packet_serializer):
            case (
                AbstractIncrementalPacketSerializer(),
                BufferedIncrementalPacketSerializer(),
            ) if cls is StapledPacketSerializer or cls is StapledIncrementalPacketSerializer:
                self = super().__new__(StapledBufferedIncrementalPacketSerializer)
            case (
                AbstractIncrementalPacketSerializer(),
                AbstractIncrementalPacketSerializer(),
            ) if cls is StapledPacketSerializer:
                self = super().__new__(StapledIncrementalPacketSerializer)
            case _:
                self = super().__new__(cls)

        self.__sent_packet_serializer = sent_packet_serializer
        self.__received_packet_serializer = received_packet_serializer
        return self

    def serialize(self, packet: _T_SentDTOPacket) -> bytes:
        return self.sent_packet_serializer.serialize(packet)

    def deserialize(self, data: bytes) -> _T_ReceivedDTOPacket:
        return self.received_packet_serializer.deserialize(data)

    @property
    def sent_packet_serializer(self) -> AbstractPacketSerializer[_T_SentDTOPacket, Any]:
        return self.__sent_packet_serializer

    @property
    def received_packet_serializer(self) -> AbstractPacketSerializer[Any, _T_ReceivedDTOPacket]:
        return self.__received_packet_serializer


@final
class StapledIncrementalPacketSerializer(  # type: ignore[misc]
    StapledPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],  # type: ignore[misc]
    AbstractIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],
    Generic[_T_SentDTOPacket, _T_ReceivedDTOPacket],
):
    __slots__ = ()

    if TYPE_CHECKING:

        @overload
        def __new__(
            cls,
            sent_packet_serializer: AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any],
            received_packet_serializer: BufferedIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket, _T_Buffer],
        ) -> StapledBufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, _T_Buffer]: ...

        @overload
        def __new__(
            cls,
            sent_packet_serializer: AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any],
            received_packet_serializer: AbstractIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket],
        ) -> Self: ...

        def __new__(
            cls,
            sent_packet_serializer: AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any],
            received_packet_serializer: AbstractIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket],
        ) -> Self: ...

    def incremental_serialize(self, packet: _T_SentDTOPacket) -> Generator[bytes, None, None]:
        return self.sent_packet_serializer.incremental_serialize(packet)

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
        return self.received_packet_serializer.incremental_deserialize()

    if TYPE_CHECKING:

        @property
        def sent_packet_serializer(self) -> AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any]: ...

        @property
        def received_packet_serializer(self) -> AbstractIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket]: ...


@final
class StapledBufferedIncrementalPacketSerializer(  # type: ignore[misc]
    StapledIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],  # type: ignore[misc]
    BufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, _T_Buffer],
    Generic[_T_SentDTOPacket, _T_ReceivedDTOPacket, _T_Buffer],
):
    __slots__ = ()

    if TYPE_CHECKING:

        def __new__(
            cls,
            sent_packet_serializer: AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any],
            received_packet_serializer: BufferedIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket, _T_Buffer],
        ) -> Self: ...

    def create_deserializer_buffer(self, sizehint: int) -> _T_Buffer:
        return self.received_packet_serializer.create_deserializer_buffer(sizehint)

    def buffered_incremental_deserialize(
        self,
        buffer: _T_Buffer,
    ) -> Generator[int | None, int, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
        return self.received_packet_serializer.buffered_incremental_deserialize(buffer)

    if TYPE_CHECKING:

        @property
        def received_packet_serializer(self) -> BufferedIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket, _T_Buffer]: ...


runtime_final_class(StapledPacketSerializer)
runtime_final_class(StapledIncrementalPacketSerializer)
runtime_final_class(StapledBufferedIncrementalPacketSerializer)
