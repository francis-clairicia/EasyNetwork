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
"""Stream network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "StreamDataConsumer",
    "StreamDataProducer",
]

from collections import deque
from collections.abc import Generator, Iterator
from typing import Any, Generic, final

from .._typevars import _ReceivedPacketT, _SentPacketT
from ..exceptions import StreamProtocolParseError
from ..protocol import StreamProtocol


@final
@Iterator.register
class StreamDataProducer(Generic[_SentPacketT]):
    __slots__ = ("__p", "__g", "__q")

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("StreamDataProducer cannot be subclassed")

    def __init__(self, protocol: StreamProtocol[_SentPacketT, Any]) -> None:
        super().__init__()
        _check_protocol(protocol)
        self.__p: StreamProtocol[_SentPacketT, Any] = protocol
        self.__g: Generator[bytes, None, None] | None = None
        self.__q: deque[_SentPacketT] = deque()

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
        protocol = self.__p
        queue: deque[_SentPacketT] = self.__q
        generator: Generator[bytes, None, None] | None
        while (generator := self.__g) is not None or queue:
            if generator is None:
                generator = protocol.generate_chunks(queue.popleft())
            else:
                self.__g = None
            try:
                chunk = next(filter(None, map(bytes, generator)))
            except StopIteration:
                pass
            else:
                self.__g = generator
                return chunk
            finally:
                del generator
        raise StopIteration

    def pending_packets(self) -> bool:
        return self.__g is not None or bool(self.__q)

    def enqueue(self, *packets: _SentPacketT) -> None:
        self.__q.extend(packets)

    def clear(self) -> None:
        self.__q.clear()
        generator, self.__g = self.__g, None
        if generator is not None:
            generator.close()


@final
@Iterator.register
class StreamDataConsumer(Generic[_ReceivedPacketT]):
    __slots__ = ("__p", "__b", "__c")

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("StreamDataConsumer cannot be subclassed")

    def __init__(self, protocol: StreamProtocol[Any, _ReceivedPacketT]) -> None:
        super().__init__()
        _check_protocol(protocol)
        self.__p: StreamProtocol[Any, _ReceivedPacketT] = protocol
        self.__c: Generator[None, bytes, tuple[_ReceivedPacketT, bytes]] | None = None
        self.__b: bytes = b""

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
            except Exception as exc:
                raise RuntimeError("protocol.build_packet_from_chunks() crashed") from exc
        self.__b = b""
        packet: _ReceivedPacketT
        remaining: bytes
        try:
            consumer.send(chunk)
        except StopIteration as exc:
            packet, remaining = exc.value
            remaining = bytes(remaining)
        except StreamProtocolParseError as exc:
            self.__b = bytes(exc.remaining_data)
            raise
        except Exception as exc:
            raise RuntimeError("protocol.build_packet_from_chunks() crashed") from exc
        else:
            self.__c = consumer
            raise StopIteration
        finally:
            del consumer, chunk
        self.__b = remaining
        return packet

    def feed(self, chunk: bytes) -> None:
        chunk = bytes(chunk)
        if not chunk:
            return
        if self.__b:
            self.__b += chunk
        else:
            self.__b = chunk

    def get_buffer(self) -> memoryview:
        return memoryview(self.__b)

    def clear(self) -> None:
        self.__b = b""
        consumer, self.__c = self.__c, None
        if consumer is not None:
            consumer.close()


def _check_protocol(p: StreamProtocol[Any, Any]) -> None:
    if not isinstance(p, StreamProtocol):
        raise TypeError(f"Expected a StreamProtocol object, got {p!r}")
