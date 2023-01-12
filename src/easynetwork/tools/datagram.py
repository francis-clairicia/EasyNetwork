# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Datagram network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "DatagramConsumer",
    "DatagramConsumerError",
    "DatagramProducer",
    "DatagramProducerError",
]

from collections import deque
from threading import Lock
from typing import Any, Generic, Iterator, Literal, TypeVar, final

from ..converter import PacketConversionError
from ..protocol import DatagramProtocol
from ..serializers.exceptions import DeserializeError
from .socket import SocketAddress

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")

_AddressT = TypeVar("_AddressT", bound=tuple[Any, ...])


class DatagramProducerError(Exception):
    def __init__(self, sender: tuple[Any, ...], exception: Exception) -> None:
        super().__init__(f"Error while serializing data: {exception}")
        self.sender: tuple[Any, ...] = sender
        self.exception: Exception = exception


@final
@Iterator.register
class DatagramProducer(Generic[_SentPacketT, _AddressT]):
    __slots__ = ("__p", "__q", "__lock")

    def __init__(self, protocol: DatagramProtocol[_SentPacketT, Any]) -> None:
        super().__init__()
        assert isinstance(protocol, DatagramProtocol)
        self.__p: DatagramProtocol[_SentPacketT, Any] = protocol
        self.__q: deque[tuple[Any, _AddressT]] = deque()
        self.__lock = Lock()

    def __iter__(self) -> Iterator[tuple[bytes, _AddressT]]:
        return self

    def __next__(self) -> tuple[bytes, _AddressT]:
        with self.__lock:
            queue = self.__q
            if not queue:
                raise StopIteration
            packet, address = queue.popleft()
            serializer = self.__p.serializer
            try:
                return (serializer.serialize(packet), address)
            except Exception as exc:
                raise DatagramProducerError(address, exc) from exc

    def queue(self, address: _AddressT, *packets: _SentPacketT) -> None:
        if not packets:
            return
        with self.__lock:
            convert = self.__p.converter.convert_to_dto_packet
            self.__q.extend((convert(packet), address) for packet in packets)


class DatagramConsumerError(Exception):
    def __init__(self, sender: SocketAddress, exception: DeserializeError | PacketConversionError) -> None:
        super().__init__(f"Error while deserializing data: {exception}")
        self.sender: SocketAddress = sender
        self.exception: DeserializeError | PacketConversionError = exception


@final
@Iterator.register
class DatagramConsumer(Generic[_ReceivedPacketT]):
    __slots__ = ("__p", "__q", "__lock", "__on_error")

    def __init__(
        self,
        protocol: DatagramProtocol[Any, _ReceivedPacketT],
        *,
        on_error: Literal["raise", "ignore"] = "raise",
    ) -> None:
        if on_error not in ("raise", "ignore"):
            raise ValueError("Invalid on_error value")
        super().__init__()
        assert isinstance(protocol, DatagramProtocol)
        self.__p: DatagramProtocol[Any, _ReceivedPacketT] = protocol
        self.__q: deque[tuple[bytes, SocketAddress]] = deque()
        self.__lock = Lock()
        self.__on_error: Literal["raise", "ignore"] = on_error

    def __iter__(self) -> Iterator[tuple[_ReceivedPacketT, SocketAddress]]:
        return self

    def __next__(self) -> tuple[_ReceivedPacketT, SocketAddress]:
        with self.__lock:
            serializer = self.__p.serializer
            converter = self.__p.converter
            queue = self.__q
            while queue:
                data, sender = queue.popleft()
                try:
                    dto_packet = serializer.deserialize(data)
                except DeserializeError as exc:
                    if self.__on_error == "raise":
                        raise DatagramConsumerError(sender, exc) from exc
                    continue
                try:
                    return (converter.create_from_dto_packet(dto_packet), sender)
                except PacketConversionError as exc:
                    if self.__on_error == "raise":
                        raise DatagramConsumerError(sender, exc) from exc
                    continue
            raise StopIteration

    def queue(self, data: bytes, address: SocketAddress) -> None:
        assert isinstance(data, bytes)
        with self.__lock:
            self.__q.append((data, address))
