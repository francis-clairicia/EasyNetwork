# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Datagram network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "DatagramConsumer",
    "DatagramProducer",
]

from collections import deque
from threading import Lock
from typing import Any, Generic, Iterator, TypeVar, final

from ..protocol import DatagramProtocol
from .socket import SocketAddress

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")

_AddressT = TypeVar("_AddressT", bound=tuple[Any, ...])


@final
@Iterator.register
class DatagramProducer(Generic[_SentPacketT, _AddressT]):
    __slots__ = ("__p", "__q", "__lock")

    def __init__(self, protocol: DatagramProtocol[_SentPacketT, Any]) -> None:
        super().__init__()
        assert isinstance(protocol, DatagramProtocol)
        self.__p: DatagramProtocol[_SentPacketT, Any] = protocol
        self.__q: deque[tuple[_SentPacketT, _AddressT]] = deque()
        self.__lock = Lock()

    def __iter__(self) -> Iterator[tuple[bytes, _AddressT]]:
        return self

    def __next__(self) -> tuple[bytes, _AddressT]:
        with self.__lock:
            queue = self.__q
            if not queue:
                raise StopIteration
            packet, address = queue.popleft()
            return self.__p.make_datagram(packet), address

    def queue(self, address: _AddressT, *packets: _SentPacketT) -> None:
        if not packets:
            return
        with self.__lock:
            self.__q.extend((packet, address) for packet in packets)


@final
@Iterator.register
class DatagramConsumer(Generic[_ReceivedPacketT]):
    __slots__ = ("__p", "__q", "__lock")

    def __init__(self, protocol: DatagramProtocol[Any, _ReceivedPacketT]) -> None:
        super().__init__()
        assert isinstance(protocol, DatagramProtocol)
        self.__p: DatagramProtocol[Any, _ReceivedPacketT] = protocol
        self.__q: deque[tuple[bytes, SocketAddress]] = deque()
        self.__lock = Lock()

    def __iter__(self) -> Iterator[tuple[_ReceivedPacketT, SocketAddress]]:
        return self

    def __next__(self) -> tuple[_ReceivedPacketT, SocketAddress]:
        with self.__lock:
            queue = self.__q
            if not queue:
                raise StopIteration
            data, sender = queue.popleft()
            return self.__p.build_packet_from_datagram(data, sender), sender

    def queue(self, data: bytes, address: SocketAddress) -> None:
        assert isinstance(data, bytes)
        with self.__lock:
            self.__q.append((data, address))
