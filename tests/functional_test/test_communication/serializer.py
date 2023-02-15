from __future__ import annotations

from typing import Generator

from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer
from easynetwork.serializers.exceptions import DeserializeError, IncrementalDeserializeError


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
        yield packet.encode(encoding=self.encoding) + b"\n"

    def deserialize(self, data: bytes) -> str:
        try:
            return data.decode(encoding=self.encoding)
        except UnicodeDecodeError as exc:
            raise DeserializeError(str(exc)) from exc

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[str, bytes]]:
        data: bytes = b""
        while True:
            data += yield
            if b"\n" not in data:
                continue
            packet, data = data.split(b"\n", 1)
            if not packet:
                continue
            try:
                return packet.decode(encoding=self.encoding), data
            except UnicodeDecodeError as exc:
                raise IncrementalDeserializeError(str(exc), data) from exc
