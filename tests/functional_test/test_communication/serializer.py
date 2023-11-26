from __future__ import annotations

import itertools
from collections.abc import Generator

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer, BufferedIncrementalPacketSerializer


class StringSerializer(AbstractIncrementalPacketSerializer[str]):
    """
    Serializer to use in order to test clients and servers
    """

    __slots__ = ()

    encoding: str = "ascii"

    def serialize(self, packet: str) -> bytes:
        if not isinstance(packet, str):
            raise TypeError("is not a string")
        return packet.encode(encoding=self.encoding)

    def incremental_serialize(self, packet: str) -> Generator[bytes, None, None]:
        if not isinstance(packet, str):
            raise TypeError("is not a string")
        if "\n" in packet:
            raise ValueError(r"remove '\n' character")
        for idx, word in enumerate(packet.split()):
            if idx:
                yield b" "
            yield word.encode(encoding=self.encoding)
        yield b"\n"

    def deserialize(self, data: bytes) -> str:
        try:
            return data.decode(encoding=self.encoding)
        except UnicodeError as exc:
            raise DeserializeError(str(exc)) from exc

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[str, bytes]]:
        buffer = b""
        while True:
            buffer += yield
            if b"\n" not in buffer:
                continue
            data, buffer = buffer.split(b"\n", 1)
            if not data:
                continue
            try:
                return data.decode(encoding=self.encoding), buffer
            except UnicodeError as exc:
                raise IncrementalDeserializeError(str(exc), buffer) from exc


class BufferedStringSerializer(StringSerializer, BufferedIncrementalPacketSerializer[str, bytearray]):
    __slots__ = ()

    def create_deserializer_buffer(self, sizehint: int) -> bytearray:
        return bytearray(sizehint)

    def buffered_incremental_deserialize(self, write_buffer: bytearray) -> Generator[int, int, tuple[str, bytearray]]:
        buflen = len(write_buffer)
        read_buffer = memoryview(write_buffer).toreadonly()

        line_buffer = bytearray()

        LINE_FEED = ord(b"\n")

        while True:
            consumed: int = 0
            write_buffer[:] = itertools.repeat(0, buflen)

            while LINE_FEED not in read_buffer[:consumed]:
                if not read_buffer[consumed:].nbytes:
                    line_buffer.extend(read_buffer)
                    write_buffer[:] = itertools.repeat(0, buflen)
                    consumed = 0
                consumed += yield consumed

            line_buffer.extend(read_buffer[:consumed])
            data, line_buffer = line_buffer.split(b"\n", 1)
            if not data:
                continue
            try:
                return data.decode(encoding=self.encoding), line_buffer
            except UnicodeError as exc:
                raise IncrementalDeserializeError(str(exc), line_buffer) from exc


class NotGoodStringSerializer(StringSerializer):
    __slots__ = ()

    def deserialize(self, data: bytes) -> str:
        raise SystemError("CRASH")

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[str, bytes]]:
        yield
        raise SystemError("CRASH")


class NotGoodBufferedStringSerializer(NotGoodStringSerializer, BufferedStringSerializer):
    __slots__ = ()

    def buffered_incremental_deserialize(self, write_buffer: bytearray) -> Generator[int, int, tuple[str, bytearray]]:
        yield 0
        raise SystemError("CRASH")
