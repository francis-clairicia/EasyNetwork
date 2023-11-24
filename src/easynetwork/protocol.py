# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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
"""Communication protocol objects module"""

from __future__ import annotations

__all__ = [
    "BufferedStreamReceiver",
    "DatagramProtocol",
    "StreamProtocol",
]

from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Generic, Never, overload

from ._typevars import _BufferT, _DTOPacketT, _ReceivedPacketT, _SentPacketT
from .converter import AbstractPacketConverterComposite
from .exceptions import (
    DatagramProtocolParseError,
    DeserializeError,
    IncrementalDeserializeError,
    PacketConversionError,
    StreamProtocolParseError,
    UnsupportedOperation,
)
from .serializers.abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer, BufferedIncrementalPacketSerializer

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer, WriteableBuffer


class DatagramProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    """A :term:`protocol object` class for datagram communication."""

    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SentPacketT | _ReceivedPacketT],
        converter: None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        serializer: AbstractPacketSerializer[_DTOPacketT],
        converter: AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, _DTOPacketT],
    ) -> None:
        ...

    def __init__(
        self,
        serializer: AbstractPacketSerializer[Any],
        converter: AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, Any] | None = None,
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
        self.__serializer: AbstractPacketSerializer[Any] = serializer
        self.__converter: AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, Any] | None = converter

    def make_datagram(self, packet: _SentPacketT) -> bytes:
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

    def build_packet_from_datagram(self, datagram: bytes) -> _ReceivedPacketT:
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
            packet: _ReceivedPacketT = self.__serializer.deserialize(datagram)
        except DeserializeError as exc:
            raise DatagramProtocolParseError(exc) from exc
        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise DatagramProtocolParseError(exc) from exc
        return packet


class BufferedStreamReceiver(Generic[_ReceivedPacketT, _BufferT]):
    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: BufferedIncrementalPacketSerializer[_ReceivedPacketT, _BufferT],
        converter: None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        serializer: BufferedIncrementalPacketSerializer[_DTOPacketT, _BufferT],
        converter: AbstractPacketConverterComposite[Any, _ReceivedPacketT, _DTOPacketT],
    ) -> None:
        ...

    def __init__(
        self,
        serializer: BufferedIncrementalPacketSerializer[Any, _BufferT],
        converter: AbstractPacketConverterComposite[Any, _ReceivedPacketT, Any] | None = None,
    ) -> None:
        """
        Parameters:
            serializer: The :term:`incremental serializer` to use.
            converter: The :term:`converter` to use.
        """

        if not isinstance(serializer, BufferedIncrementalPacketSerializer):
            raise TypeError(f"Expected a buffered incremental serializer instance, got {serializer!r}")
        if converter is not None and not isinstance(converter, AbstractPacketConverterComposite):
            raise TypeError(f"Expected a converter instance, got {converter!r}")
        self.__serializer: BufferedIncrementalPacketSerializer[Any, _BufferT] = serializer
        self.__converter: AbstractPacketConverterComposite[Never, _ReceivedPacketT, Any] | None = converter

    def create_buffer(self, sizehint: int) -> _BufferT:
        return self.__serializer.create_deserializer_buffer(sizehint)

    def build_packet_from_buffer(self, buffer: _BufferT) -> Generator[int | None, int, tuple[_ReceivedPacketT, ReadableBuffer]]:
        packet: _ReceivedPacketT
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


class StreamProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    """A :term:`protocol object` class for connection-oriented stream communication."""

    __slots__ = ("__serializer", "__converter", "__buffered_receiver", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[_SentPacketT | _ReceivedPacketT],
        converter: None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[_DTOPacketT],
        converter: AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, _DTOPacketT],
    ) -> None:
        ...

    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any],
        converter: AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, Any] | None = None,
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
        self.__serializer: AbstractIncrementalPacketSerializer[Any] = serializer
        self.__converter: AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, Any] | None = converter

        self.__buffered_receiver: BufferedStreamReceiver[_ReceivedPacketT, WriteableBuffer] | None
        if isinstance(serializer, BufferedIncrementalPacketSerializer):
            self.__buffered_receiver = BufferedStreamReceiver(serializer, converter=converter)
        else:
            self.__buffered_receiver = None

    def generate_chunks(self, packet: _SentPacketT) -> Generator[bytes, None, None]:
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

    def buffered_receiver(self) -> BufferedStreamReceiver[_ReceivedPacketT, WriteableBuffer]:
        buffered_receiver = self.__buffered_receiver
        if buffered_receiver is None:
            raise UnsupportedOperation("This protocol does not support the buffer API")
        return buffered_receiver

    def build_packet_from_chunks(self) -> Generator[None, bytes, tuple[_ReceivedPacketT, bytes]]:
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

        packet: _ReceivedPacketT
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
