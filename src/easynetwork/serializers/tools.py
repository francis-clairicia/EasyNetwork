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
"""Serializer implementation tools module"""

from __future__ import annotations

__all__ = [
    "GeneratorStreamReader",
    "_wrap_generic_buffered_incremental_deserialize",
    "_wrap_generic_incremental_deserialize",
]

import contextlib
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING

from .._typevars import _T_DTOPacket
from ..exceptions import LimitOverrunError

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class GeneratorStreamReader:
    """
    A binary stream-like object using an in-memory bytes buffer.

    The "blocking" operation is done with the generator's :keyword:`yield` statement. It is an helper for
    :term:`incremental serializer` implementations.
    """

    __slots__ = ("__buffer",)

    def __init__(self, initial_bytes: bytes = b"") -> None:
        """
        Parameters:
            initial_bytes: a :class:`bytes` object that contains initial data.
        """
        self.__buffer: bytes = bytes(initial_bytes)

    def read_all(self) -> bytes:
        """
        Read and return all the bytes currently in the reader.

        Returns:
            a :class:`bytes` object.
        """

        data, self.__buffer = self.__buffer, b""
        return data

    def read(self, size: int) -> Generator[None, bytes, bytes]:
        """
        Read and return up to `size` bytes.

        Example::

            def incremental_deserialize(self) -> Generator[None, bytes, tuple[Packet, bytes]]:
                reader = GeneratorStreamReader()

                data: bytes = yield from reader.read(1024)  # Get at most 1024 bytes.

                ...

        Yields:
            if there is no data in buffer.

        Returns:
            a :class:`bytes` object.
        """

        if size < 0:
            raise ValueError("size must not be < 0")
        if size == 0:
            return b""

        while not self.__buffer:
            self.__buffer = bytes((yield))

        data = self.__buffer[:size]
        self.__buffer = self.__buffer[size:]

        return data

    def read_exactly(self, n: int) -> Generator[None, bytes, bytes]:
        """
        Read exactly `n` bytes.

        Example::

            def incremental_deserialize(self) -> Generator[None, bytes, tuple[Packet, bytes]]:
                reader = GeneratorStreamReader()

                header: bytes = yield from reader.read_exactly(32)
                assert len(header) == 32

                ...

        Yields:
            until `n` bytes is in the buffer.

        Returns:
            a :class:`bytes` object.
        """

        if n < 0:
            raise ValueError("n must not be < 0")
        if n == 0:
            return b""

        while not self.__buffer:
            self.__buffer = bytes((yield))
        while len(self.__buffer) < n:
            self.__buffer += yield

        data = self.__buffer[:n]
        self.__buffer = self.__buffer[n:]

        return data

    def read_until(self, separator: bytes, limit: int, *, keep_end: bool = True) -> Generator[None, bytes, bytes]:
        r"""
        Read data from the stream until `separator` is found.

        On success, the data and separator will be removed from the internal buffer (consumed).

        If the amount of data read exceeds `limit`, a :exc:`.LimitOverrunError` exception is raised,
        and the data is left in the internal buffer and can be read again.

        Example::

            def incremental_deserialize(self) -> Generator[None, bytes, tuple[Packet, bytes]]:
                reader = GeneratorStreamReader()

                line: bytes = yield from reader.read_until(b"\r\n", limit=65535)
                assert line.endswith(b"\r\n")

                ...

        Parameters:
            separator: The byte sequence to find.
            limit: The maximum buffer size.
            keep_end: If :data:`True` (the default), returned data will include the separator at the end.

        Raises:
            LimitOverrunError: Reached buffer size limit.

        Yields:
            until `separator` is found in the buffer.

        Returns:
            a :class:`bytes` object.
        """

        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        seplen: int = len(separator)
        if seplen < 1:
            raise ValueError("Empty separator")

        while not self.__buffer:
            self.__buffer = bytes((yield))

        offset: int = 0
        sepidx: int = -1
        while True:
            buflen = len(self.__buffer)

            if buflen - offset >= seplen:
                sepidx = self.__buffer.find(separator, offset)

                if sepidx != -1:
                    break

                offset = buflen + 1 - seplen
                if offset > limit:
                    msg = "Separator is not found, and chunk exceed the limit"
                    raise LimitOverrunError(msg, self.__buffer, offset, separator)

            self.__buffer += yield

        if sepidx > limit:
            msg = "Separator is found, but chunk is longer than limit"
            raise LimitOverrunError(msg, self.__buffer, sepidx, separator)

        offset = sepidx + seplen
        if keep_end:
            data = self.__buffer[:offset]
        else:
            data = self.__buffer[:sepidx]
        self.__buffer = self.__buffer[offset:]

        return data


def _wrap_generic_incremental_deserialize(
    func: Callable[[], Generator[None, ReadableBuffer, tuple[_T_DTOPacket, ReadableBuffer]]],
) -> Generator[None, bytes, tuple[_T_DTOPacket, bytes]]:
    packet, remainder = yield from func()
    # remainder is not copied if it is already a "bytes" object
    remainder = bytes(remainder)
    return packet, remainder


def _wrap_generic_buffered_incremental_deserialize(
    buffer: memoryview,
    func: Callable[[], Generator[None, ReadableBuffer, tuple[_T_DTOPacket, ReadableBuffer]]],
) -> Generator[None, int, tuple[_T_DTOPacket, ReadableBuffer]]:
    next(gen := func())
    with contextlib.closing(gen):
        while True:
            nbytes: int = yield
            try:
                gen.send(buffer[:nbytes])
            except StopIteration as exc:
                return exc.value
