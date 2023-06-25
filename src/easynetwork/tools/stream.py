# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Stream network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "StreamDataConsumer",
    "StreamDataProducer",
]

import threading
from collections import deque
from typing import Any, Generator, Generic, Iterator, TypeVar, final

from ..exceptions import StreamProtocolParseError
from ..protocol import StreamProtocol
from .lock import ForkSafeLock

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


@final
@Iterator.register
class StreamDataProducer(Generic[_SentPacketT]):
    __slots__ = ("__p", "__g", "__q", "__lock")

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("StreamDataProducer cannot be subclassed")

    def __init__(self, protocol: StreamProtocol[_SentPacketT, Any]) -> None:
        super().__init__()
        assert isinstance(protocol, StreamProtocol)
        self.__p: StreamProtocol[_SentPacketT, Any] = protocol
        self.__g: Generator[bytes, None, None] | None = None
        self.__q: deque[_SentPacketT] = deque()

        self.__lock = ForkSafeLock(threading.Lock)

    def __del__(self) -> None:  # pragma: no cover
        try:
            generator, self.__g = self.__g, None
        except AttributeError:
            return
        try:
            if generator is not None:
                generator.close()
        finally:
            del generator

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        with self.__lock.get():
            protocol = self.__p
            queue: deque[_SentPacketT] = self.__q
            generator: Generator[bytes, None, None] | None
            while (generator := self.__g) is not None or queue:
                if generator is None:
                    generator = protocol.generate_chunks(queue.popleft())
                else:
                    self.__g = None
                try:
                    chunk = next(filter(None, generator))
                except StopIteration:
                    pass
                else:
                    assert isinstance(chunk, (bytes, bytearray))
                    self.__g = generator
                    return chunk
                finally:
                    del generator
            raise StopIteration

    def pending_packets(self) -> bool:
        with self.__lock.get():
            return self.__g is not None or bool(self.__q)

    def queue(self, *packets: _SentPacketT) -> None:
        if not packets:
            return
        with self.__lock.get():
            self.__q.extend(packets)

    def clear(self) -> None:
        with self.__lock.get():
            self.__q.clear()
            generator, self.__g = self.__g, None
            if generator is not None:
                generator.close()


@final
@Iterator.register
class StreamDataConsumer(Generic[_ReceivedPacketT]):
    __slots__ = ("__p", "__b", "__c", "__lock")

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("StreamDataConsumer cannot be subclassed")

    def __init__(self, protocol: StreamProtocol[Any, _ReceivedPacketT]) -> None:
        super().__init__()
        assert isinstance(protocol, StreamProtocol)
        self.__p: StreamProtocol[Any, _ReceivedPacketT] = protocol
        self.__c: Generator[None, bytes, tuple[_ReceivedPacketT, bytes]] | None = None
        self.__b: bytes = b""

        self.__lock = ForkSafeLock(threading.Lock)

    def __del__(self) -> None:  # pragma: no cover
        try:
            consumer, self.__c = self.__c, None
        except AttributeError:
            return
        try:
            if consumer is not None:
                consumer.close()
        finally:
            del consumer

    def __iter__(self) -> Iterator[_ReceivedPacketT]:
        return self

    def __next__(self) -> _ReceivedPacketT:
        with self.__lock.get():
            chunk: bytes = self.__b
            if not chunk:
                raise StopIteration
            consumer, self.__c = self.__c, None
            if consumer is None:
                consumer = self.__p.build_packet_from_chunks()
                try:
                    next(consumer)
                except StopIteration:
                    raise RuntimeError("protocol.build_packet_from_chunks() did not yield") from None
            self.__b = b""
            packet: _ReceivedPacketT
            try:
                consumer.send(chunk)
            except StopIteration as exc:
                packet, chunk = exc.value
            except StreamProtocolParseError as exc:
                self.__b, exc.remaining_data = bytes(exc.remaining_data), b""
                raise
            else:
                self.__c = consumer
                raise StopIteration
            finally:
                del consumer
            self.__b = bytes(chunk)
            return packet

    def feed(self, chunk: bytes) -> None:
        assert isinstance(chunk, (bytes, bytearray))
        if not chunk:
            return
        with self.__lock.get():
            self.__b += chunk

    def get_buffer(self) -> bytes:
        with self.__lock.get():
            return self.__b

    def clear(self) -> None:
        with self.__lock.get():
            self.__b = b""
            consumer, self.__c = self.__c, None
            if consumer is not None:
                consumer.close()
