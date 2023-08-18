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
    "DatagramProtocol",
    "StreamProtocol",
]

from collections.abc import Generator
from typing import Any, Generic, TypeVar, overload

from .converter import AbstractPacketConverterComposite
from .exceptions import (
    DatagramProtocolParseError,
    DeserializeError,
    IncrementalDeserializeError,
    PacketConversionError,
    StreamProtocolParseError,
)
from .serializers.abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer

_SentDTOPacketT = TypeVar("_SentDTOPacketT")
_ReceivedDTOPacketT = TypeVar("_ReceivedDTOPacketT")

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


class DatagramProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    """A :term:`protocol object` class for datagram communication"""

    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SentPacketT, _ReceivedPacketT],
        converter: None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SentDTOPacketT, _ReceivedDTOPacketT],
        converter: AbstractPacketConverterComposite[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT],
    ) -> None:
        ...

    def __init__(
        self,
        serializer: AbstractPacketSerializer[Any, Any],
        converter: AbstractPacketConverterComposite[_SentPacketT, Any, _ReceivedPacketT, Any] | None = None,
    ) -> None:
        """
        :param serializer: The :term:`serializer` to use
        :param converter: The :term:`converter` to use
        """

        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        if converter is not None and not isinstance(converter, AbstractPacketConverterComposite):
            raise TypeError(f"Expected a converter instance, got {converter!r}")
        self.__serializer: AbstractPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverterComposite[_SentPacketT, Any, _ReceivedPacketT, Any] | None = converter

    def make_datagram(self, packet: _SentPacketT) -> bytes:
        """
        Serializes a Python object to a raw datagram :term:`packet`.

        :param packet: The :term:`packet` as a Python object to serialize
        :returns: The serialized :term:`packet`
        """

        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return self.__serializer.serialize(packet)

    def build_packet_from_datagram(self, datagram: bytes) -> _ReceivedPacketT:
        """
        Creates a Python object representing the raw datagram :term:`packet`.

        :param bytes datagram: The datagram :term:`packet` to deserialize
        :returns: The deserialized :term:`packet`
        :raises DatagramProtocolParseError: in case of deserialization error
        :raises DatagramProtocolParseError: in case of conversion error (if there is a :term:`converter`)
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


class StreamProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    """A :term:`protocol object` class for connection-oriented stream communication"""

    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[_SentPacketT, _ReceivedPacketT],
        converter: None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[_SentDTOPacketT, _ReceivedDTOPacketT],
        converter: AbstractPacketConverterComposite[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT],
    ) -> None:
        ...

    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        converter: AbstractPacketConverterComposite[_SentPacketT, Any, _ReceivedPacketT, Any] | None = None,
    ) -> None:
        """
        :param serializer: The :term:`incremental serializer` to use
        :param converter: The :term:`converter` to use
        """

        if not isinstance(serializer, AbstractIncrementalPacketSerializer):
            raise TypeError(f"Expected an incremental serializer instance, got {serializer!r}")
        if converter is not None and not isinstance(converter, AbstractPacketConverterComposite):
            raise TypeError(f"Expected a converter instance, got {converter!r}")
        self.__serializer: AbstractIncrementalPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverterComposite[_SentPacketT, Any, _ReceivedPacketT, Any] | None = converter

    def generate_chunks(self, packet: _SentPacketT) -> Generator[bytes, None, None]:
        """
        Serializes a Python object to a raw :term:`packet` part by part.

        :param packet: The :term:`packet` as a Python object to serialize
        :returns: A generator yielding all the parts of the :term:`packet`
        """

        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return (yield from self.__serializer.incremental_serialize(packet))

    def build_packet_from_chunks(self) -> Generator[None, bytes, tuple[_ReceivedPacketT, bytes]]:
        """
        Creates a Python object representing the raw :term:`packet`.

        :returns: A generator which yields until the whole :term:`packet` has been deserialized and returns a tuple with
                  the deserialized packet and the unused trailing data
        :raises StreamProtocolParseError: in case of deserialization error
        :raises StreamProtocolParseError: in case of conversion error (if there is a :term:`converter`)
        :raises RuntimeError: The :term:`serializer` raised :class:`.DeserializeError` instead of :class:`.IncrementalDeserializeError`
        """

        packet: _ReceivedPacketT
        try:
            packet, remaining_data = yield from self.__serializer.incremental_deserialize()
        except IncrementalDeserializeError as exc:
            remaining_data, exc.remaining_data = exc.remaining_data, b""
            raise StreamProtocolParseError(remaining_data, exc) from exc
        except DeserializeError as exc:
            raise RuntimeError("DeserializeError raised instead of IncrementalDeserializeError") from exc

        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise StreamProtocolParseError(remaining_data, exc) from exc

        return packet, remaining_data
