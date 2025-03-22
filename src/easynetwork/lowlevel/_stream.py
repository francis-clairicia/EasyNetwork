# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Stream network packet serializer handler module."""

from __future__ import annotations

__all__ = [
    "BufferedStreamDataConsumer",
    "StreamDataConsumer",
    "StreamDataProducer",
]

import dataclasses
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Generic, final

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..exceptions import StreamProtocolParseError
from ..protocol import AnyStreamProtocolType, BufferedStreamProtocol, StreamProtocol
from ._final import runtime_final_class

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer, WriteableBuffer


@final
@runtime_final_class
class StreamDataProducer(Generic[_T_SentPacket]):
    __slots__ = ("__protocol",)

    def __init__(self, protocol: AnyStreamProtocolType[_T_SentPacket, Any]) -> None:
        super().__init__()
        _check_any_protocol(protocol)
        self.__protocol: AnyStreamProtocolType[_T_SentPacket, Any] = protocol

    def generate(self, packet: _T_SentPacket) -> Generator[bytes]:
        try:
            yield from self.__protocol.generate_chunks(packet)
        except Exception as exc:
            raise RuntimeError("protocol.generate_chunks() crashed") from exc


@final
@runtime_final_class
class StreamDataConsumer(Generic[_T_ReceivedPacket]):
    __slots__ = ("__protocol", "__buffer", "__consumer")

    def __init__(self, protocol: StreamProtocol[Any, _T_ReceivedPacket]) -> None:
        super().__init__()
        _check_protocol(protocol)
        self.__protocol: StreamProtocol[Any, _T_ReceivedPacket] = protocol
        self.__consumer: Generator[None, bytes, tuple[_T_ReceivedPacket, bytes]] | None = None
        self.__buffer: bytes = b""

    def __del__(self) -> None:
        try:
            self.clear()
        except AttributeError:
            return

    def next(self, received_chunk: bytes | None) -> _T_ReceivedPacket:
        if not received_chunk:
            if not (received_chunk := self.__buffer):
                raise StopIteration
        elif self.__buffer:
            received_chunk = self.__buffer + received_chunk
        if (consumer := self.__consumer) is None:
            consumer = self.__protocol.build_packet_from_chunks()
            try:
                next(consumer)
            except StopIteration:
                self.__buffer = bytes(received_chunk)
                raise RuntimeError("protocol.build_packet_from_chunks() did not yield") from None
            except Exception as exc:
                raise RuntimeError("protocol.build_packet_from_chunks() crashed") from exc
        else:
            # Reset consumer
            # Will be re-assigned if needed
            self.__consumer = None
        self.__buffer = b""
        packet: _T_ReceivedPacket
        remaining: bytes
        try:
            consumer.send(received_chunk)
        except StopIteration as exc:
            packet, remaining = exc.value
            self.__buffer = bytes(remaining)
            return packet
        except StreamProtocolParseError as exc:
            self.__buffer = bytes(exc.remaining_data)
            raise
        except Exception as exc:
            raise RuntimeError("protocol.build_packet_from_chunks() crashed") from exc
        else:
            self.__consumer = consumer
            raise StopIteration

    def get_buffer(self) -> memoryview:
        return memoryview(self.__buffer)

    def clear(self) -> None:
        self.__buffer = b""
        consumer, self.__consumer = self.__consumer, None
        if consumer is not None:
            consumer.close()


@final
@runtime_final_class
class BufferedStreamDataConsumer(Generic[_T_ReceivedPacket]):
    __slots__ = (
        "__protocol",
        "__buffer",
        "__exported_write_buffer_view",
        "__buffer_start",
        "__already_written",
        "__sizehint",
        "__consumer",
    )

    def __init__(self, protocol: BufferedStreamProtocol[Any, _T_ReceivedPacket, Any], buffer_size_hint: int) -> None:
        super().__init__()
        _check_buffered_protocol(protocol)
        if not isinstance(buffer_size_hint, int) or buffer_size_hint <= 0:
            raise ValueError(f"{buffer_size_hint=!r}")
        self.__protocol: BufferedStreamProtocol[Any, _T_ReceivedPacket, WriteableBuffer] = protocol
        self.__consumer: Generator[int | None, int, tuple[_T_ReceivedPacket, ReadableBuffer]] | None = None
        self.__buffer: _BufferRef | None = None
        self.__exported_write_buffer_view: memoryview | None = None
        self.__buffer_start: int = 0
        self.__already_written: int = 0
        self.__sizehint: int = buffer_size_hint

    def __del__(self) -> None:
        try:
            self.clear()
        except AttributeError:
            return

    def next(self, nb_updated_bytes: int | None) -> _T_ReceivedPacket:
        if nb_updated_bytes is None:
            nb_updated_bytes = 0
        else:
            if (buffer_view := self.__exported_write_buffer_view) is None:
                raise RuntimeError("next() has been called whilst get_write_buffer() was never called")
            if not (0 <= nb_updated_bytes <= buffer_view.nbytes):
                raise RuntimeError("Invalid value given")
            del buffer_view

        if (consumer := self.__consumer) is None:
            raise StopIteration

        nb_updated_bytes += self.__already_written
        self.__already_written = 0

        if not nb_updated_bytes:
            raise StopIteration

        self.__release_write_buffer_view()

        # Reset consumer
        # Will be re-assigned if needed
        self.__consumer = None

        packet: _T_ReceivedPacket
        remaining: ReadableBuffer
        try:
            self.__buffer_start = consumer.send(nb_updated_bytes) or 0
        except StopIteration as exc:
            packet, remaining = exc.value
            self.__save_remainder_in_buffer(remaining)
            return packet
        except StreamProtocolParseError as exc:
            self.__save_remainder_in_buffer(exc.remaining_data)
            raise
        except Exception as exc:
            # Reset buffer, since we do not know if the buffer state is still valid
            self.__buffer = None
            raise RuntimeError("protocol.build_packet_from_buffer() crashed") from exc
        else:
            self.__consumer = consumer
            raise StopIteration

    def get_write_buffer(self) -> memoryview:
        if self.__exported_write_buffer_view is not None:
            return self.__exported_write_buffer_view[:]
        buffer = self.__new_write_buffer()
        self.__exported_write_buffer_view = buffer[:]
        return buffer

    def __new_write_buffer(self) -> memoryview:
        if self.__buffer is None:
            whole_buffer = self.__protocol.create_buffer(self.__sizehint)
            self.__validate_created_buffer(whole_buffer)
            self.__buffer = _BufferRef(whole_buffer)

        if self.__consumer is None:
            consumer = self.__protocol.build_packet_from_buffer(self.__buffer.ref)
            try:
                self.__buffer_start = next(consumer) or 0
            except StopIteration:
                raise RuntimeError("protocol.build_packet_from_buffer() did not yield") from None
            except Exception as exc:
                # Reset buffer, since we do not know if the buffer state is still valid
                self.__buffer = None
                raise RuntimeError("protocol.build_packet_from_buffer() crashed") from exc
            self.__consumer = consumer

        buffer = self.__buffer.view[self.__buffer_start :]

        if self.__already_written:
            buffer = buffer[self.__already_written :]

        if not buffer:
            raise RuntimeError("The start position is set to the end of the buffer")

        return buffer

    def get_value(self, *, full: bool = False) -> bytes | None:
        if self.__buffer is None:
            return None
        if full:
            return bytes(self.__buffer.ref)
        buffer = self.__buffer.view
        if self.__buffer_start < 0:
            nbytes = self.__buffer_start + len(buffer) + self.__already_written
        else:
            nbytes = self.__buffer_start + self.__already_written
        return buffer[:nbytes].tobytes()

    def clear(self) -> None:
        self.__release_write_buffer_view()
        self.__buffer = None
        self.__buffer_start = 0
        self.__already_written = 0
        consumer, self.__consumer = self.__consumer, None
        if consumer is not None:
            consumer.close()

    def __save_remainder_in_buffer(self, remaining_data: ReadableBuffer) -> None:
        with memoryview(remaining_data) as remaining_data:
            nbytes = remaining_data.nbytes
            if not nbytes:
                # Nothing to save.
                return

            with remaining_data.cast("B") if remaining_data.itemsize != 1 else remaining_data as remaining_data:
                # Drop the current buffer so a new one is created because remaining_data can be a view to the wrapped buffer
                self.__buffer = None

                with self.__new_write_buffer() as buffer:
                    buffer[:nbytes] = remaining_data
                self.__already_written += nbytes

    def __release_write_buffer_view(self) -> None:
        buffer_view, self.__exported_write_buffer_view = self.__exported_write_buffer_view, None
        if buffer_view is not None:
            buffer_view.release()

    @staticmethod
    def __validate_created_buffer(buffer: WriteableBuffer) -> None:
        with memoryview(buffer) as buffer:
            if buffer.readonly:
                raise ValueError("protocol.create_buffer() returned a read-only buffer")
            if not buffer:
                raise ValueError("protocol.create_buffer() returned a null buffer")

    @property
    def buffer_size(self) -> int:
        match self.__buffer:
            case None:
                return 0
            case buffer:
                return buffer.view.nbytes


@dataclasses.dataclass(frozen=True, slots=True)
class _BufferRef:
    ref: WriteableBuffer
    view: memoryview = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "view", memoryview(self.ref).cast("B"))

    def __del__(self) -> None:
        self.view.release()


def _check_protocol(p: StreamProtocol[Any, Any]) -> None:
    if not isinstance(p, StreamProtocol):
        raise TypeError(f"Expected a StreamProtocol object, got {p!r}")


def _check_buffered_protocol(p: BufferedStreamProtocol[Any, Any, Any]) -> None:
    if not isinstance(p, BufferedStreamProtocol):
        raise TypeError(f"Expected a BufferedStreamProtocol object, got {p!r}")


def _check_any_protocol(p: AnyStreamProtocolType[Any, Any]) -> None:
    if not isinstance(p, (StreamProtocol, BufferedStreamProtocol)):
        raise TypeError(f"Expected a StreamProtocol or a BufferedStreamProtocol object, got {p!r}")
