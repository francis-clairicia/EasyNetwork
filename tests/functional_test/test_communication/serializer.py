from __future__ import annotations

from collections.abc import Generator
from typing import Final

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.abc import BufferedIncrementalPacketSerializer


class StringSerializer(BufferedIncrementalPacketSerializer[str, str, bytearray]):
    """
    Serializer to use in order to test clients and servers
    """

    __slots__ = ()

    MIN_SIZE: Final[int] = 8 * 1024

    encoding: str = "ascii"

    def serialize(self, packet: str) -> bytes:
        if not isinstance(packet, str):
            raise TypeError("is not a string")
        return packet.encode(encoding=self.encoding)

    def incremental_serialize(self, packet: str) -> Generator[bytes]:
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
        data = yield
        newline = b"\n"
        while (index := data.find(newline)) < 0:
            data += yield

        remainder = data[index + len(newline) :]
        data = data[:index]

        try:
            return data.decode(encoding=self.encoding), remainder
        except UnicodeError as exc:
            raise IncrementalDeserializeError(str(exc), remainder) from exc

    def create_deserializer_buffer(self, sizehint: int) -> bytearray:
        return bytearray(max(sizehint, self.MIN_SIZE))

    def buffered_incremental_deserialize(self, buffer: bytearray) -> Generator[int | None, int, tuple[str, bytearray]]:
        buffer_size = len(buffer)
        newline = b"\n"
        separator_length = len(newline)

        nb_written_bytes: int = yield None

        while (index := buffer.find(newline, 0, nb_written_bytes)) < 0:
            start_idx: int = nb_written_bytes
            if start_idx > buffer_size - separator_length:
                raise IncrementalDeserializeError("Too long line", remaining_data=b"")
            nb_written_bytes += yield start_idx

        remainder: bytearray = buffer[index + separator_length : nb_written_bytes]
        data: bytearray = buffer[:index]
        try:
            return data.decode(encoding=self.encoding), remainder
        except UnicodeError as exc:
            raise IncrementalDeserializeError(str(exc), remainder) from exc


class NotGoodStringSerializer(StringSerializer):
    __slots__ = ()

    def deserialize(self, data: bytes) -> str:
        raise SystemError("CRASH")

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[str, bytes]]:
        yield
        raise SystemError("CRASH")

    def buffered_incremental_deserialize(self, write_buffer: bytearray) -> Generator[int, int, tuple[str, bytearray]]:
        yield 0
        raise SystemError("CRASH")


class BadSerializeStringSerializer(StringSerializer):
    __slots__ = ()

    def serialize(self, packet: str) -> bytes:
        raise SystemError("CRASH")

    def incremental_serialize(self, packet: str) -> Generator[bytes]:
        raise SystemError("CRASH")
        yield b"chunk"  # type: ignore[unreachable]
