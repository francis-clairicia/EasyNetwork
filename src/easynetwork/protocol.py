# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network protocol module"""

from __future__ import annotations

__all__ = [
    "BaseProtocolParseError",
    "DatagramProtocol",
    "DatagramProtocolParseError",
    "StreamProtocol",
    "StreamProtocolParseError",
]

from typing import Any, Generator, Generic, Literal, TypeAlias, TypeVar, overload

from .converter import AbstractPacketConverter, PacketConversionError
from .serializers.abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer
from .serializers.exceptions import DeserializeError, IncrementalDeserializeError

_SentDTOPacketT = TypeVar("_SentDTOPacketT")
_ReceivedDTOPacketT = TypeVar("_ReceivedDTOPacketT")

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


ParseErrorType: TypeAlias = Literal["deserialization", "conversion"]


class BaseProtocolParseError(Exception):
    def __init__(self, error_type: ParseErrorType, message: str, error_info: Any = None) -> None:
        super().__init__(f"Error while parsing data: {message}")
        self.error_type: ParseErrorType = error_type
        self.error_info: Any = error_info
        self.message: str = message


class DatagramProtocolParseError(BaseProtocolParseError):
    pass


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


class StreamProtocolParseError(BaseProtocolParseError):
    def __init__(self, remaining_data: bytes, error_type: ParseErrorType, message: str, error_info: Any = None) -> None:
        super().__init__(
            error_type=error_type,
            message=message,
            error_info=error_info,
        )
        self.remaining_data: bytes = remaining_data


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

    def generate_chunks(self, packet: _SentPacketT) -> Generator[bytes, None, None]:
        if (converter := self.__converter) is not None:
            packet = converter.convert_to_dto_packet(packet)
        return (yield from self.__serializer.incremental_serialize(packet))

    def build_packet_from_chunks(self) -> Generator[None, bytes, tuple[_ReceivedPacketT, bytes]]:
        packet: _ReceivedPacketT
        try:
            packet, remaining_data = yield from self.__serializer.incremental_deserialize()
        except IncrementalDeserializeError as exc:
            raise StreamProtocolParseError(exc.remaining_data, "deserialization", str(exc), error_info=exc.error_info) from exc
        except DeserializeError as exc:
            raise RuntimeError(str(exc)) from exc

        if (converter := self.__converter) is not None:
            try:
                packet = converter.create_from_dto_packet(packet)
            except PacketConversionError as exc:
                raise StreamProtocolParseError(remaining_data, "conversion", str(exc), error_info=exc.error_info) from exc

        return packet, remaining_data
