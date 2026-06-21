# Copyright 2021-2026, Francis Clairicia-Rose-Claire-Josephine
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
"""Communication protocol objects module."""

from __future__ import annotations

__all__ = [
    "AnyStreamProtocolType",
    "BufferedStreamProtocol",
    "DatagramProtocol",
    "StreamProtocol",
]

from collections.abc import Buffer, Generator
from typing import Any, overload

from .converter import AbstractPacketConverterComposite
from .exceptions import (
    DatagramProtocolParseError,
    DeserializeError,
    IncrementalDeserializeError,
    PacketConversionError,
    StreamProtocolParseError,
)
from .serializers.abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer, BufferedIncrementalPacketSerializer


class DatagramProtocol[SentPacket, ReceivedPacket]:
    """A :term:`protocol object` class for datagram communication."""

    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractPacketSerializer[SentPacket, ReceivedPacket],
        converter: None = ...,
    ) -> None: ...

    @overload
    def __init__[SentDTOPacket, ReceivedDTOPacket](
        self,
        serializer: AbstractPacketSerializer[SentDTOPacket, ReceivedDTOPacket],
        converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, SentDTOPacket, ReceivedDTOPacket],
    ) -> None: ...

    def __init__(
        self,
        serializer: AbstractPacketSerializer[Any, Any],
        converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, Any, Any] | None = None,
    ) -> None:
        """
        Parameters:
            serializer: The :term:`serializer` to use.
            converter: The :term:`converter` to use.
        """

        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        if converter is not None and not isinstance(converter, AbstractPacketConverterComposite):
            raise TypeError(f"Expected a converter instance, got {converter!r}")
        self.__serializer: AbstractPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, Any, Any] | None = converter

    def make_datagram(self, packet: SentPacket) -> bytes:
        """
        Serializes a Python object to a raw datagram :term:`packet`.

        Parameters:
            packet: The :term:`packet` as a Python object to serialize.

        Returns:
            the serialized :term:`packet`.
        """

        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return self.__serializer.serialize(packet)

    def build_packet_from_datagram(self, datagram: bytes) -> ReceivedPacket:
        """
        Creates a Python object representing the raw datagram :term:`packet`.

        Parameters:
            datagram: The datagram :term:`packet` to deserialize.

        Raises:
            DatagramProtocolParseError: in case of deserialization error.
            DatagramProtocolParseError: in case of conversion error (if there is a :term:`converter`).

        Returns:
            the deserialized :term:`packet`.
        """

        try:
            packet: ReceivedPacket = self.__serializer.deserialize(datagram)
        except DeserializeError as exc:
            raise DatagramProtocolParseError(exc) from exc
        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise DatagramProtocolParseError(exc) from exc
        return packet


class BufferedStreamProtocol[SentPacket, ReceivedPacket, BufferType: Buffer]:
    """A specialization of :class:`StreamProtocol` in order to use a buffered :term:`incremental serializer`."""

    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: BufferedIncrementalPacketSerializer[SentPacket, ReceivedPacket, BufferType],
        converter: None = ...,
    ) -> None: ...

    @overload
    def __init__[SentDTOPacket, ReceivedDTOPacket](
        self,
        serializer: BufferedIncrementalPacketSerializer[SentDTOPacket, ReceivedDTOPacket, BufferType],
        converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, SentDTOPacket, ReceivedDTOPacket],
    ) -> None: ...

    def __init__(
        self,
        serializer: BufferedIncrementalPacketSerializer[Any, Any, BufferType],
        converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, Any, Any] | None = None,
    ) -> None:
        """
        Parameters:
            serializer: The buffered :term:`incremental serializer` to use.
            converter: The :term:`converter` to use.
        """

        if not isinstance(serializer, BufferedIncrementalPacketSerializer):
            raise TypeError(f"Expected a buffered incremental serializer instance, got {serializer!r}")
        if converter is not None and not isinstance(converter, AbstractPacketConverterComposite):
            raise TypeError(f"Expected a converter instance, got {converter!r}")
        self.__serializer: BufferedIncrementalPacketSerializer[Any, Any, BufferType] = serializer
        self.__converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, Any, Any] | None = converter

    def create_buffer(self, sizehint: int) -> BufferType:
        """
        Called to allocate a new receive buffer.

        See :meth:`.BufferedIncrementalPacketSerializer.create_deserializer_buffer` for details.
        """
        return self.__serializer.create_deserializer_buffer(sizehint)

    def generate_chunks(self, packet: SentPacket) -> Generator[bytes]:
        """
        Serializes a Python object to a raw :term:`packet` part by part.

        Parameters:
            packet: The :term:`packet` as a Python object to serialize.

        Yields:
            all the parts of the :term:`packet`.
        """

        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return (yield from self.__serializer.incremental_serialize(packet))

    def build_packet_from_buffer(self, buffer: BufferType) -> Generator[int | None, int, tuple[ReceivedPacket, Buffer]]:
        """
        Creates a Python object representing the raw :term:`packet`.

        Parameters:
            buffer: The buffer allocated by :meth:`create_buffer`.

        Raises:
            StreamProtocolParseError: in case of deserialization error.
            StreamProtocolParseError: in case of conversion error (if there is a :term:`converter`).
            RuntimeError: The :term:`serializer` raised :exc:`.DeserializeError` instead of :exc:`.IncrementalDeserializeError`.

        Yields:
            until the whole :term:`packet` has been deserialized.

            See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` for details.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.

            See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` for details.
        """
        packet: ReceivedPacket
        try:
            packet, remaining_data = yield from self.__serializer.buffered_incremental_deserialize(buffer)
        except IncrementalDeserializeError as exc:
            raise StreamProtocolParseError(exc.remaining_data, exc) from exc
        except DeserializeError as exc:
            raise RuntimeError("DeserializeError raised instead of IncrementalDeserializeError") from exc

        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise StreamProtocolParseError(remaining_data, exc) from exc

        return packet, remaining_data


class StreamProtocol[SentPacket, ReceivedPacket]:
    """A :term:`protocol object` class for connection-oriented stream communication."""

    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[SentPacket, ReceivedPacket],
        converter: None = ...,
    ) -> None: ...

    @overload
    def __init__[SentDTOPacket, ReceivedDTOPacket](
        self,
        serializer: AbstractIncrementalPacketSerializer[SentDTOPacket, ReceivedDTOPacket],
        converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, SentDTOPacket, ReceivedDTOPacket],
    ) -> None: ...

    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, Any, Any] | None = None,
    ) -> None:
        """
        Parameters:
            serializer: The :term:`incremental serializer` to use.
            converter: The :term:`converter` to use.
        """

        if not isinstance(serializer, AbstractIncrementalPacketSerializer):
            raise TypeError(f"Expected an incremental serializer instance, got {serializer!r}")
        if converter is not None and not isinstance(converter, AbstractPacketConverterComposite):
            raise TypeError(f"Expected a converter instance, got {converter!r}")
        self.__serializer: AbstractIncrementalPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverterComposite[SentPacket, ReceivedPacket, Any, Any] | None = converter

    def generate_chunks(self, packet: SentPacket) -> Generator[bytes]:
        """
        Serializes a Python object to a raw :term:`packet` part by part.

        Parameters:
            packet: The :term:`packet` as a Python object to serialize.

        Yields:
            all the parts of the :term:`packet`.
        """

        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return (yield from self.__serializer.incremental_serialize(packet))

    def build_packet_from_chunks(self) -> Generator[None, bytes, tuple[ReceivedPacket, bytes]]:
        """
        Creates a Python object representing the raw :term:`packet`.

        Raises:
            StreamProtocolParseError: in case of deserialization error.
            StreamProtocolParseError: in case of conversion error (if there is a :term:`converter`).
            RuntimeError: The :term:`serializer` raised :exc:`.DeserializeError` instead of :exc:`.IncrementalDeserializeError`.

        Yields:
            :data:`None` until the whole :term:`packet` has been deserialized.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.
        """

        packet: ReceivedPacket
        try:
            packet, remaining_data = yield from self.__serializer.incremental_deserialize()
        except IncrementalDeserializeError as exc:
            raise StreamProtocolParseError(exc.remaining_data, exc) from exc
        except DeserializeError as exc:
            raise RuntimeError("DeserializeError raised instead of IncrementalDeserializeError") from exc

        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise StreamProtocolParseError(remaining_data, exc) from exc

        return packet, remaining_data


type AnyStreamProtocolType[SentPacket, ReceivedPacket] = (
    StreamProtocol[SentPacket, ReceivedPacket] | BufferedStreamProtocol[SentPacket, ReceivedPacket, Any]
)
"""Type alias for any connection-oriented stream :term:`protocol object` classes."""
