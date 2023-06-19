# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network protocol module"""

from __future__ import annotations

__all__ = [
    "DatagramProtocol",
    "StreamProtocol",
]

from typing import Any, Generator, Generic, TypeVar, overload

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
        assert isinstance(serializer, AbstractPacketSerializer)
        assert converter is None or isinstance(converter, AbstractPacketConverterComposite)
        self.__serializer: AbstractPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverterComposite[_SentPacketT, Any, _ReceivedPacketT, Any] | None = converter

    def make_datagram(self, packet: _SentPacketT) -> bytes:
        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return self.__serializer.serialize(packet)

    def build_packet_from_datagram(self, datagram: bytes) -> _ReceivedPacketT:
        try:
            packet: _ReceivedPacketT = self.__serializer.deserialize(datagram)
        except DeserializeError as exc:
            raise DatagramProtocolParseError("deserialization", str(exc), error_info=exc.error_info) from exc
        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise DatagramProtocolParseError("conversion", str(exc), error_info=exc.error_info) from exc
        return packet


class StreamProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
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
        assert isinstance(serializer, AbstractIncrementalPacketSerializer)
        assert converter is None or isinstance(converter, AbstractPacketConverterComposite)
        self.__serializer: AbstractIncrementalPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverterComposite[_SentPacketT, Any, _ReceivedPacketT, Any] | None = converter

    def generate_chunks(self, packet: _SentPacketT) -> Generator[bytes, None, None]:
        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return (yield from self.__serializer.incremental_serialize(packet))

    def build_packet_from_chunks(self) -> Generator[None, bytes, tuple[_ReceivedPacketT, bytes]]:
        packet: _ReceivedPacketT
        try:
            packet, remaining_data = yield from self.__serializer.incremental_deserialize()
        except IncrementalDeserializeError as exc:
            remaining_data, exc.remaining_data = exc.remaining_data, b""
            raise StreamProtocolParseError(remaining_data, "deserialization", str(exc), error_info=exc.error_info) from exc
        except DeserializeError as exc:
            raise RuntimeError("DeserializeError raised instead of IncrementalDeserializeError") from exc

        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise StreamProtocolParseError(remaining_data, "conversion", str(exc), error_info=exc.error_info) from exc

        return packet, remaining_data
