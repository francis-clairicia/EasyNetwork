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
from typing import TYPE_CHECKING, Any, Generic, final

from .._typevars import _ReceivedPacketT, _SentPacketT
from ..exceptions import StreamProtocolParseError
from ..protocol import BufferedStreamReceiver, StreamProtocol

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer, WriteableBuffer


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
            self.__b = bytes(remaining)
            return packet
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


@final
@Iterator.register
class BufferedStreamDataConsumer(Generic[_ReceivedPacketT]):
    __slots__ = (
        "__buffered_receiver",
        "__buffer",
        "__buffer_view",
        "__buffer_start",
        "__already_written",
        "__sizehint",
        "__consumer",
    )

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("BufferedStreamDataConsumer cannot be subclassed")

    def __init__(self, protocol: StreamProtocol[Any, _ReceivedPacketT], buffer_size_hint: int) -> None:
        super().__init__()
        _check_protocol(protocol)
        if not isinstance(buffer_size_hint, int) or buffer_size_hint <= 0:
            raise ValueError(f"{buffer_size_hint=!r}")
        self.__buffered_receiver: BufferedStreamReceiver[_ReceivedPacketT, WriteableBuffer] = protocol.buffered_receiver()
        self.__consumer: Generator[int | None, int, tuple[_ReceivedPacketT, ReadableBuffer]] | None = None
        self.__buffer: WriteableBuffer | None = None
        self.__buffer_view: memoryview | None = None
        self.__buffer_start: int | None = None
        self.__already_written: int = 0
        self.__sizehint: int = buffer_size_hint

    def __del__(self) -> None:  # pragma: no cover
        self.__buffer = None
        try:
            consumer, self.__consumer = self.__consumer, None
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
        consumer = self.__consumer
        if consumer is None:
            raise StopIteration

        nb_updated_bytes, self.__already_written = self.__already_written, 0
        if nb_updated_bytes == 0:
            raise StopIteration

        # Forcibly reset buffer view
        self.__buffer_view = None

        # Reset consumer
        # Will be re-assigned if needed
        self.__consumer = None

        packet: _ReceivedPacketT
        remaining: ReadableBuffer
        try:
            self.__buffer_start = consumer.send(nb_updated_bytes)
        except StopIteration as exc:
            packet, remaining = exc.value
            self.__save_remainder_in_buffer(remaining)
            return packet
        except StreamProtocolParseError as exc:
            self.__save_remainder_in_buffer(exc.remaining_data)
            raise
        except Exception as exc:
            raise RuntimeError("protocol.build_packet_from_buffer() crashed") from exc
        else:
            self.__consumer = consumer
            raise StopIteration
        finally:
            del consumer

    def get_write_buffer(self) -> WriteableBuffer:
        if self.__buffer_view is not None:
            return self.__buffer_view

        if self.__buffer is None:
            self.__buffer = self.__buffered_receiver.create_buffer(self.__sizehint)
            self.__validate_created_buffer(self.__buffer)

        if self.__consumer is None:
            consumer = self.__buffered_receiver.build_packet_from_buffer(self.__buffer)
            try:
                self.__buffer_start = next(consumer)
            except StopIteration:
                raise RuntimeError("protocol.build_packet_from_buffer() did not yield") from None
            except Exception as exc:
                raise RuntimeError("protocol.build_packet_from_buffer() crashed") from exc
            self.__consumer = consumer

        buffer: memoryview = memoryview(self.__buffer)

        match self.__buffer_start:
            case None | 0:
                pass
            case start_idx:
                buffer = buffer[start_idx:]

        if self.__already_written:
            buffer = buffer[self.__already_written :]

        if not buffer:
            raise RuntimeError("The start position is set to the end of the buffer")

        self.__buffer_view = buffer
        return buffer

    def buffer_updated(self, nbytes: int) -> None:
        if nbytes < 0:
            raise ValueError("Negative value given")
        if self.__buffer_view is None:
            raise RuntimeError("buffer_updated() has been called whilst get_buffer() was never called")
        if nbytes > self.__buffer_view.nbytes:
            raise RuntimeError("nbytes > buffer_view.nbytes")
        self.__update_write_count(nbytes)

    def get_value(self, *, full: bool = False) -> bytes | None:
        if self.__buffer is None:
            return None
        if full:
            return bytes(self.__buffer)
        buffer = memoryview(self.__buffer)
        if self.__buffer_start is None:
            nbytes = self.__already_written
        elif self.__buffer_start < 0:
            nbytes = self.__buffer_start + len(buffer) + self.__already_written
        else:
            nbytes = self.__buffer_start + self.__already_written
        return buffer[:nbytes].tobytes()

    def clear(self) -> None:
        self.__buffer = self.__buffer_view = self.__buffer_start = None
        self.__already_written = 0
        consumer, self.__consumer = self.__consumer, None
        if consumer is not None:
            consumer.close()

    def __save_remainder_in_buffer(self, remaining_data: ReadableBuffer) -> None:
        remaining_data = bytes(remaining_data)
        nbytes = len(remaining_data)
        if nbytes == 0:
            # Nothing to save.
            return
        with memoryview(self.get_write_buffer()) as buffer:
            buffer[:nbytes] = remaining_data
        self.__update_write_count(nbytes)

    def __update_write_count(self, nbytes: int) -> None:
        self.__already_written += nbytes
        self.__buffer_view = None

    @staticmethod
    def __validate_created_buffer(buffer: WriteableBuffer) -> None:
        with memoryview(buffer) as buffer:
            if buffer.readonly:
                raise ValueError("protocol.create_buffer() returned a read-only buffer")
            if buffer.itemsize != 1:
                raise ValueError("protocol.create_buffer() must return a byte buffer")
            if not len(buffer):
                raise ValueError("protocol.create_buffer() returned a null buffer")

    @property
    def buffer_size(self) -> int:
        if self.__buffer is None:
            return 0
        with memoryview(self.__buffer) as buffer:
            return len(buffer)


def _check_protocol(p: StreamProtocol[Any, Any]) -> None:
    if not isinstance(p, StreamProtocol):
        raise TypeError(f"Expected a StreamProtocol object, got {p!r}")
