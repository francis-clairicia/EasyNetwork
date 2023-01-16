# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network protocol module"""

from __future__ import annotations

__all__ = ["DatagramProtocol", "DatagramProtocolParseError", "StreamProtocol", "StreamProtocolParseError"]

from typing import Any, Generator, Generic, Literal, TypeAlias, TypeVar, final, overload

from .converter import AbstractPacketConverter, PacketConversionError
from .serializers.abc import AbstractPacketSerializer
from .serializers.exceptions import DeserializeError
from .serializers.stream.abc import AbstractIncrementalPacketSerializer
from .serializers.stream.exceptions import IncrementalDeserializeError
from .tools.socket import SocketAddress

_SentDTOPacketT = TypeVar("_SentDTOPacketT")
_ReceivedDTOPacketT = TypeVar("_ReceivedDTOPacketT")

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


ParseErrorType: TypeAlias = Literal["deserialization", "conversion"]


class DatagramProtocolParseError(Exception):
    def __init__(self, sender: SocketAddress, error_type: ParseErrorType, message: str) -> None:
        super().__init__(f"Error while parsing datagram: {message}")
        self.sender: SocketAddress = sender
        self.error_type: ParseErrorType = error_type
        self.message: str = message


class DatagramProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SentPacketT, _ReceivedPacketT],
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SentDTOPacketT, _ReceivedDTOPacketT],
        converter: AbstractPacketConverter[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT],
    ) -> None:
        ...

    def __init__(
        self,
        serializer: AbstractPacketSerializer[Any, Any],
        converter: AbstractPacketConverter[_SentPacketT, Any, _ReceivedPacketT, Any] | None = None,
    ) -> None:
        assert isinstance(serializer, AbstractPacketSerializer)
        assert converter is None or isinstance(converter, AbstractPacketConverter)
        self.__serializer: AbstractPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverter[_SentPacketT, Any, _ReceivedPacketT, Any] | None = converter

    @final
    def make_datagram(self, packet: _SentPacketT) -> bytes:
        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return self.__serializer.serialize(packet)

    @final
    def build_packet_from_datagram(self, datagram: bytes, sender: SocketAddress) -> _ReceivedPacketT:
        try:
            packet: _ReceivedPacketT = self.__serializer.deserialize(datagram)
        except DeserializeError as exc:
            raise DatagramProtocolParseError(sender, "deserialization", str(exc)) from exc
        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise DatagramProtocolParseError(sender, "conversion", str(exc)) from exc
        return packet


class StreamProtocolParseError(Exception):
    def __init__(self, remaining_data: bytes, error_type: ParseErrorType, message: str) -> None:
        super().__init__(f"Error while parsing datagram: {message}")
        self.remaining_data: bytes = remaining_data
        self.error_type: ParseErrorType = error_type
        self.message: str = message


class StreamProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    __slots__ = ("__serializer", "__converter", "__weakref__")

    @overload
    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[_SentPacketT, _ReceivedPacketT],
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[_SentDTOPacketT, _ReceivedDTOPacketT],
        converter: AbstractPacketConverter[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT],
    ) -> None:
        ...

    def __init__(
        self,
        serializer: AbstractIncrementalPacketSerializer[Any, Any],
        converter: AbstractPacketConverter[_SentPacketT, Any, _ReceivedPacketT, Any] | None = None,
    ) -> None:
        assert isinstance(serializer, AbstractIncrementalPacketSerializer)
        assert converter is None or isinstance(converter, AbstractPacketConverter)
        self.__serializer: AbstractIncrementalPacketSerializer[Any, Any] = serializer
        self.__converter: AbstractPacketConverter[_SentPacketT, Any, _ReceivedPacketT, Any] | None = converter

    @final
    def generate_chunks(self, packet: _SentPacketT) -> Generator[bytes, None, None]:
        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return self.__serializer.incremental_serialize(packet)

    @final
    def build_packet_from_chunks(self) -> Generator[None, bytes, tuple[_ReceivedPacketT, bytes]]:
        packet: _ReceivedPacketT
        try:
            packet, remaining_data = yield from self.__serializer.incremental_deserialize()
        except IncrementalDeserializeError as exc:
            raise StreamProtocolParseError(exc.remaining_data, "deserialization", str(exc)) from exc

        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise StreamProtocolParseError(remaining_data, "conversion", str(exc)) from exc

        return packet, remaining_data
