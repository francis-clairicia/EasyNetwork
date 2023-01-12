# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Stream network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "StreamDataConsumer",
    "StreamDataConsumerError",
    "StreamDataProducerIterator",
    "StreamDataProducerReader",
]

from collections import deque
from threading import Lock
from typing import Any, Generator, Generic, Iterator, Literal, TypeVar, final

from ..converter import PacketConversionError
from ..protocol import StreamProtocol
from ..serializers.stream.exceptions import IncrementalDeserializeError

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


@final
class StreamDataProducerReader(Generic[_SentPacketT]):
    __slots__ = ("__p", "__q", "__b", "__lock")

    def __init__(self, protocol: StreamProtocol[_SentPacketT, Any]) -> None:
        super().__init__()
        assert isinstance(protocol, StreamProtocol)
        self.__p: StreamProtocol[_SentPacketT, Any] = protocol
        self.__q: deque[Generator[bytes, None, None]] = deque()
        self.__b: bytes = b""
        self.__lock = Lock()

    def read(self, bufsize: int = -1) -> bytes:
        if bufsize == 0:
            return b""
        data: bytes = self.__b
        with self.__lock:
            queue: deque[Generator[bytes, None, None]] = self.__q

            if bufsize < 0:
                while queue:
                    generator = queue[0]
                    try:
                        for chunk in generator:
                            data += chunk
                    except Exception as exc:
                        self.__b = data
                        raise RuntimeError(str(exc)) from exc
                    except BaseException:
                        self.__b = data
                        raise
                    finally:
                        del queue[0], generator
                self.__b = b""
                return data

            while len(data) < bufsize and queue:
                generator = queue[0]
                try:
                    while not (chunk := next(generator)):  # Empty bytes are useless
                        continue
                    data += chunk
                except StopIteration:
                    del queue[0]
                except Exception as exc:
                    self.__b = data
                    del queue[0]
                    raise RuntimeError(str(exc)) from exc
                except BaseException:
                    self.__b = data
                    del queue[0]
                    raise
                finally:
                    del generator
            self.__b = data[bufsize:]
            return data[:bufsize]

    def queue(self, *packets: _SentPacketT) -> None:
        if not packets:
            return
        with self.__lock:
            serializer = self.__p.serializer
            converter = self.__p.converter
            self.__q.extend(map(serializer.incremental_serialize, map(converter.convert_to_dto_packet, packets)))


@final
@Iterator.register
class StreamDataProducerIterator(Generic[_SentPacketT]):
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

    def queue(self, *packets: _SentPacketT) -> None:
        if not packets:
            return
        with self.__lock:
            serializer = self.__p.serializer
            converter = self.__p.converter
            self.__q.extend(map(serializer.incremental_serialize, map(converter.convert_to_dto_packet, packets)))


class StreamDataConsumerError(Exception):
    def __init__(self, exception: IncrementalDeserializeError | PacketConversionError) -> None:
        super().__init__(f"Error while deserializing data: {exception}")
        self.exception: IncrementalDeserializeError | PacketConversionError = exception


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
        self.__c: Generator[None, bytes, tuple[Any, bytes]] | None = None
        self.__b: bytes = b""
        self.__u: bytes = b""
        self.__lock = Lock()
        self.__on_error: Literal["raise", "ignore"] = on_error

    def __iter__(self) -> Iterator[_ReceivedPacketT]:
        return self

    def __next__(self) -> _ReceivedPacketT:
        with self.__lock:
            serializer = self.__p.serializer
            converter = self.__p.converter
            while chunk := self.__b:
                self.__b = b""
                consumer, self.__c = self.__c, None
                if consumer is None:
                    consumer = serializer.incremental_deserialize()
                    next(consumer)
                packet: Any
                try:
                    consumer.send(chunk)
                except StopIteration as exc:
                    try:
                        packet, chunk = exc.value
                    finally:
                        del exc
                    self.__u = b""
                    self.__b = chunk
                except IncrementalDeserializeError as exc:
                    self.__u = b""
                    self.__b = exc.remaining_data
                    exc.remaining_data = b""
                    if self.__on_error == "raise":
                        raise StreamDataConsumerError(exc) from exc
                    continue
                except Exception as exc:
                    self.__u = b""
                    raise RuntimeError(str(exc)) from exc
                except BaseException:
                    self.__u = b""
                    raise
                else:
                    self.__u += chunk
                    self.__c = consumer
                    continue

                try:
                    return converter.create_from_dto_packet(packet)
                except PacketConversionError as exc:
                    if self.__on_error == "raise":
                        raise StreamDataConsumerError(exc) from exc
                    continue
                except Exception as exc:
                    raise RuntimeError(str(exc)) from exc
                finally:
                    del packet

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
