from __future__ import annotations

from typing import Generator

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer


class StringSerializer(AbstractIncrementalPacketSerializer[str, str]):
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
        buffer: bytearray = bytearray()
        while True:
            buffer.extend((yield))
            if b"\n" not in buffer:
                continue
            data, buffer = buffer.split(b"\n", 1)
            if not data:
                continue
            try:
                return data.decode(encoding=self.encoding), buffer
            except UnicodeError as exc:
                raise IncrementalDeserializeError(str(exc), buffer) from exc
