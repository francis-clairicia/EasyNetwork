from __future__ import annotations

import io
from collections.abc import Generator
from typing import Any, TypeAlias

from easynetwork.serializers.abc import BufferedIncrementalPacketSerializer

SentPacket: TypeAlias = Any
ReceivedPacket: TypeAlias = Any


class MySerializer(BufferedIncrementalPacketSerializer[SentPacket, ReceivedPacket, memoryview]):
    ...

    # It can receive either 'bytes' from endpoint or 'memoryviews' from buffered_incremental_deserialize()
    def incremental_deserialize(self) -> Generator[None, bytes | memoryview, tuple[ReceivedPacket, bytes]]:
        initial_bytes = yield
        with io.BytesIO(initial_bytes) as buffer:
            while True:
                try:
                    packet = self._load_from_file(buffer)
                except EOFError:
                    pass
                else:
                    break
                buffer.write((yield))
                buffer.seek(0)

            remainder = buffer.read()
            return packet, remainder

    def _load_from_file(self, file: io.IOBase) -> ReceivedPacket: ...

    def create_deserializer_buffer(self, sizehint: int) -> memoryview:
        # Don't care about buffer size
        buffer = bytearray(sizehint)
        return memoryview(buffer)

    def buffered_incremental_deserialize(self, buffer: memoryview) -> Generator[None, int, tuple[ReceivedPacket, bytes]]:
        incremental_deserialize = self.incremental_deserialize()
        # Start the generator
        next(incremental_deserialize)

        while True:
            nb_bytes_written: int = yield
            try:
                incremental_deserialize.send(buffer[:nb_bytes_written])
            except StopIteration as exc:
                # incremental_deserialize() returned
                return exc.value
