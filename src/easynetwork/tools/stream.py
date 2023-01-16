# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Stream network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "StreamDataConsumer",
    "StreamDataProducer",
]

from collections import deque
from threading import Lock
from typing import Any, Generator, Generic, Iterator, Literal, TypeVar, final

from ..protocol import StreamProtocol, StreamProtocolParseError

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


@final
@Iterator.register
class StreamDataProducer(Generic[_SentPacketT]):
    __slots__ = ("__p", "__q", "__lock")

    def __init__(self, protocol: StreamProtocol[_SentPacketT, Any]) -> None:
        super().__init__()
        assert isinstance(protocol, StreamProtocol)
        self.__p: StreamProtocol[_SentPacketT, Any] = protocol
        self.__q: deque[Generator[bytes, None, None]] = deque()
        self.__lock = Lock()

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        with self.__lock:
            queue: deque[Generator[bytes, None, None]] = self.__q
            while queue:
                generator = queue[0]
                try:
                    return next(generator)
                except StopIteration:
                    del queue[0]
                except Exception as exc:
                    del queue[0]
                    raise RuntimeError(str(exc)) from exc
                except BaseException:
                    del queue[0]
                    raise
                finally:
                    del generator
        raise StopIteration

    def pending_packets(self) -> bool:
        with self.__lock:
            return bool(self.__q)

    def queue(self, *packets: _SentPacketT) -> None:
        if not packets:
            return
        with self.__lock:
            self.__q.extend(map(self.__p.generate_chunks, packets))


@final
@Iterator.register
class StreamDataConsumer(Generic[_ReceivedPacketT]):
    __slots__ = ("__p", "__b", "__c", "__u", "__lock", "__on_error")

    def __init__(
        self,
        protocol: StreamProtocol[Any, _ReceivedPacketT],
        *,
        on_error: Literal["raise", "ignore"] = "raise",
    ) -> None:
        if on_error not in ("raise", "ignore"):
            raise ValueError("Invalid on_error value")
        super().__init__()
        assert isinstance(protocol, StreamProtocol)
        self.__p: StreamProtocol[Any, _ReceivedPacketT] = protocol
        self.__c: Generator[None, bytes, tuple[_ReceivedPacketT, bytes]] | None = None
        self.__b: bytes = b""
        self.__u: bytes = b""
        self.__lock = Lock()
        self.__on_error: Literal["raise", "ignore"] = on_error

    def __iter__(self) -> Iterator[_ReceivedPacketT]:
        return self

    def __next__(self) -> _ReceivedPacketT:
        with self.__lock:
            protocol = self.__p
            while chunk := self.__b:
                self.__b = b""
                unconsumed_data, self.__u = self.__u, b""
                consumer, self.__c = self.__c, None
                if consumer is None:
                    consumer = protocol.build_packet_from_chunks()
                    next(consumer)
                packet: _ReceivedPacketT
                try:
                    consumer.send(chunk)
                except StopIteration as exc:
                    try:
                        packet, chunk = exc.value
                    finally:
                        del exc
                    self.__b = chunk
                    return packet
                except StreamProtocolParseError as exc:
                    self.__b = exc.remaining_data
                    if self.__on_error == "raise":
                        raise
                    continue
                except Exception as exc:
                    raise RuntimeError(str(exc)) from exc
                else:
                    self.__u = unconsumed_data + chunk
                    self.__c = consumer
                    continue

            raise StopIteration

    def feed(self, chunk: bytes) -> None:
        assert isinstance(chunk, bytes)
        if not chunk:
            return
        with self.__lock:
            self.__b += chunk

    def get_buffer(self) -> bytes:
        with self.__lock:
            return self.__b

    def get_unconsumed_data(self) -> bytes:
        with self.__lock:
            return self.__u + self.__b
