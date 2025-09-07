from __future__ import annotations

__all__ = ["TrioStreamLineReader"]

import dataclasses
from collections.abc import Generator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import trio


# https://stackoverflow.com/a/53576829
@dataclasses.dataclass(eq=False, slots=True, match_args=True)
class TrioStreamLineReader:
    stream: trio.abc.ReceiveStream
    _line_generator: Generator[bytes | None, bytes | bytearray | None] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self._line_generator = self.generate_lines()

    @staticmethod
    def generate_lines(max_line_length: int = 65536) -> Generator[bytes | None, bytes | bytearray | None]:
        buf = bytearray()
        find_start = 0
        while True:
            newline_idx = buf.find(b"\n", find_start)
            if newline_idx < 0:
                # no b'\n' found in buf
                if len(buf) > max_line_length:
                    raise ValueError("line too long")
                # next time, start the search where this one left off
                find_start = len(buf)
                more_data = yield None
            else:
                # b'\n' found in buf so return the line and move up buf
                line = bytes(buf[: newline_idx + 1])
                # Update the buffer in place, to take advantage of bytearray's
                # optimized delete-from-beginning feature.
                del buf[: newline_idx + 1]
                # next time, start the search from the beginning
                find_start = 0
                more_data = yield line

            if more_data is not None:
                buf.extend(more_data)

    async def readline(self) -> bytes:
        line = next(self._line_generator)
        while line is None:
            more_data = await self.stream.receive_some(1024)
            if not more_data:
                return b""  # this is the EOF indication expected by my caller
            line = self._line_generator.send(more_data)
        return line
