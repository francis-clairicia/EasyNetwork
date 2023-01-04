# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Stream network packet protocol handler module"""

from __future__ import annotations

__all__ = [
    "StreamNetworkDataConsumer",
    "StreamNetworkDataProducerReader",
]

from collections import deque
from threading import RLock
from typing import Generator, Generic, Iterator, Literal, TypeVar, final

from ..protocol.exceptions import DeserializeError
from ..protocol.stream.abc import NetworkPacketIncrementalDeserializer, NetworkPacketIncrementalSerializer
from ..protocol.stream.exceptions import IncrementalDeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


@final
class StreamNetworkDataProducerReader(Generic[_ST_contra]):
    __slots__ = ("__s", "__q", "__b", "__lock")

    def __init__(self, serializer: NetworkPacketIncrementalSerializer[_ST_contra], *, lock: RLock | None = None) -> None:
        super().__init__()
        assert isinstance(serializer, NetworkPacketIncrementalSerializer)
        self.__s: NetworkPacketIncrementalSerializer[_ST_contra] = serializer
        self.__q: deque[Generator[bytes, None, None]] = deque()
        self.__b: bytes = b""
        self.__lock: RLock = lock or RLock()

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
                    raise RuntimeError(str(exc)) from exc
                except BaseException:
                    self.__b = data
                    raise
                finally:
                    del generator
            self.__b = data[bufsize:]
            return data[:bufsize]

    def queue(self, *packets: _ST_contra) -> None:
        if not packets:
            return
        with self.__lock:
            self.__q.extend(map(self.__s.incremental_serialize, packets))


@final
class StreamNetworkDataProducerIterator(Generic[_ST_contra]):
    __slots__ = ("__s", "__q", "__lock")

    def __init__(self, serializer: NetworkPacketIncrementalSerializer[_ST_contra], *, lock: RLock | None = None) -> None:
        super().__init__()
        assert isinstance(serializer, NetworkPacketIncrementalSerializer)
        self.__s: NetworkPacketIncrementalSerializer[_ST_contra] = serializer
        self.__q: deque[Generator[bytes, None, None]] = deque()
        self.__lock: RLock = lock or RLock()

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
                    raise RuntimeError(str(exc)) from exc
                finally:
                    del generator
        raise StopIteration

    def queue(self, *packets: _ST_contra) -> None:
        if not packets:
            return
        with self.__lock:
            self.__q.extend(map(self.__s.incremental_serialize, packets))


@final
class StreamNetworkDataConsumer(Generic[_DT_co]):
    __slots__ = ("__d", "__b", "__c", "__u", "__lock", "__on_error")

    def __init__(
        self,
        deserializer: NetworkPacketIncrementalDeserializer[_DT_co],
        *,
        lock: RLock | None = None,
        on_error: Literal["raise", "ignore"] = "raise",
    ) -> None:
        if on_error not in ("raise", "ignore"):
            raise ValueError("Invalid on_error value")
        super().__init__()
        assert isinstance(deserializer, NetworkPacketIncrementalDeserializer)
        self.__d: NetworkPacketIncrementalDeserializer[_DT_co] = deserializer
        self.__c: Generator[None, bytes, tuple[_DT_co, bytes]] | None = None
        self.__b: bytes = b""
        self.__u: bytes = b""
        self.__lock: RLock = lock or RLock()
        self.__on_error: Literal["raise", "ignore"] = on_error

    def next(self, *, on_error: Literal["raise", "ignore"] | None = None) -> _DT_co:
        if on_error is None:
            on_error = self.__on_error
        elif on_error not in ("raise", "ignore"):
            raise ValueError("Invalid on_error value")
        with self.__lock:
            chunk, self.__b = self.__b, b""
            if chunk:
                consumer, self.__c = self.__c, None
                if consumer is None:
                    consumer = self.__d.incremental_deserialize()
                    next(consumer)
                packet: _DT_co
                try:
                    consumer.send(chunk)
                except StopIteration as exc:
                    try:
                        packet, chunk = exc.value
                    finally:
                        del exc
                    self.__u = b""
                    self.__b = chunk
                    return packet
                except IncrementalDeserializeError as exc:
                    self.__u = b""
                    self.__b = exc.remaining_data
                    try:
                        if on_error == "raise":
                            raise DeserializeError(str(exc)) from exc
                    finally:
                        del exc
                except DeserializeError:
                    self.__u = b""
                    if on_error == "raise":
                        raise
                except Exception as exc:
                    self.__u = b""
                    raise RuntimeError(str(exc)) from exc
                except BaseException:
                    self.__u = b""
                    raise
                else:
                    self.__u += chunk
                    self.__c = consumer
            raise EOFError

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
