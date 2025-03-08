# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
    "StapledBufferedIncrementalPacketSerializer",
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
            ) if (
                cls is StapledPacketSerializer or cls is StapledIncrementalPacketSerializer
            ):
                self = super().__new__(StapledBufferedIncrementalPacketSerializer)
            case (
                AbstractIncrementalPacketSerializer(),
                AbstractIncrementalPacketSerializer(),
            ) if (
                cls is StapledPacketSerializer
            ):
                self = super().__new__(StapledIncrementalPacketSerializer)
            case _:
                self = super().__new__(cls)

        self.__sent_packet_serializer = sent_packet_serializer
        self.__received_packet_serializer = received_packet_serializer
        return self

    @property
    def sent_packet_serializer(self) -> AbstractPacketSerializer[_T_SentDTOPacket, Any]:
        """Sent packet serializer."""
        return self.__sent_packet_serializer

    @property
    def received_packet_serializer(self) -> AbstractPacketSerializer[Any, _T_ReceivedDTOPacket]:
        """Received packet serializer."""
        return self.__received_packet_serializer

    def __repr__(self) -> str:
        sent_packet_serializer = self.sent_packet_serializer
        received_packet_serializer = self.received_packet_serializer
        return f"{self.__class__.__name__}({sent_packet_serializer=!r}, {received_packet_serializer=!r})"

    def serialize(self, packet: _T_SentDTOPacket) -> bytes:
        """
        Calls ``self.sent_packet_serializer.serialize(packet)``.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return self.sent_packet_serializer.serialize(packet)

    def deserialize(self, data: bytes) -> _T_ReceivedDTOPacket:
        """
        Calls ``self.received_packet_serializer.deserialize(data)``.

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: An unrelated deserialization error occurred.

        Returns:
            the deserialized Python object.
        """
        return self.received_packet_serializer.deserialize(data)


@final
class StapledIncrementalPacketSerializer(  # type: ignore[misc]
    StapledPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],  # pyright: ignore
    AbstractIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],
    Generic[_T_SentDTOPacket, _T_ReceivedDTOPacket],
):
    """
    A :term:`composite serializer` that merges two incremental serializers.
    """

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

        @property
        def sent_packet_serializer(self) -> AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any]: ...

        @property
        def received_packet_serializer(self) -> AbstractIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket]: ...

    def incremental_serialize(self, packet: _T_SentDTOPacket) -> Generator[bytes]:
        """
        Calls ``self.sent_packet_serializer.incremental_serialize(packet)``.

        Parameters:
            packet: The Python object to serialize.

        Yields:
            all the parts of the :term:`packet`.
        """
        return self.sent_packet_serializer.incremental_serialize(packet)

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
        """
        Calls ``self.received_packet_serializer.incremental_deserialize()``.

        Raises:
            IncrementalDeserializeError: An unrelated deserialization error occurred.

        Yields:
            :data:`None` until the whole :term:`packet` has been deserialized.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.
        """
        return self.received_packet_serializer.incremental_deserialize()


@final
class StapledBufferedIncrementalPacketSerializer(  # type: ignore[misc]
    StapledIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],  # pyright: ignore
    BufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, _T_Buffer],
    Generic[_T_SentDTOPacket, _T_ReceivedDTOPacket, _T_Buffer],
):
    """
    A :term:`composite serializer` that merges two incremental serializers with manual control of the receive buffer.
    """

    __slots__ = ()

    if TYPE_CHECKING:

        def __new__(
            cls,
            sent_packet_serializer: AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any],
            received_packet_serializer: BufferedIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket, _T_Buffer],
        ) -> Self: ...

        @property
        def sent_packet_serializer(self) -> AbstractIncrementalPacketSerializer[_T_SentDTOPacket, Any]: ...

        @property
        def received_packet_serializer(self) -> BufferedIncrementalPacketSerializer[Any, _T_ReceivedDTOPacket, _T_Buffer]: ...

    def create_deserializer_buffer(self, sizehint: int) -> _T_Buffer:
        """
        Calls ``self.received_packet_serializer.create_deserializer_buffer(sizehint)``.

        Parameters:
            sizehint: the recommended size (in bytes) for the returned buffer.
                      It is acceptable to return smaller or larger buffers than what `sizehint` suggests.

        Returns:
            an object implementing the :ref:`buffer protocol <bufferobjects>`. It is an error to return a buffer with a zero size.
        """
        return self.received_packet_serializer.create_deserializer_buffer(sizehint)

    def buffered_incremental_deserialize(
        self,
        buffer: _T_Buffer,
    ) -> Generator[int | None, int, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
        """
        Calls ``self.received_packet_serializer.buffered_incremental_deserialize(buffer)``.

        Parameters:
            buffer: The buffer allocated by :meth:`create_deserializer_buffer`.

        Raises:
            IncrementalDeserializeError: An unrelated deserialization error occurred.

        Yields:
            until the whole :term:`packet` has been deserialized.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.

            The remainder can be a :class:`memoryview` pointing to `buffer` or an external :term:`bytes-like object`.
        """
        return self.received_packet_serializer.buffered_incremental_deserialize(buffer)


runtime_final_class(StapledPacketSerializer)
runtime_final_class(StapledIncrementalPacketSerializer)
runtime_final_class(StapledBufferedIncrementalPacketSerializer)
