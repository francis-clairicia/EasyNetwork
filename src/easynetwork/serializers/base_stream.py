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
"""Stream network packet serializer handler module.

Here are abstract classes that implement common stream protocol patterns.
"""

from __future__ import annotations

__all__ = [
    "AutoSeparatedPacketSerializer",
    "FileBasedPacketSerializer",
    "FixedSizePacketSerializer",
]

import contextlib
from abc import abstractmethod
from collections.abc import Callable, Generator
from io import BytesIO
from typing import IO, TYPE_CHECKING, Any, final

from .._typevars import _T_ReceivedDTOPacket, _T_SentDTOPacket
from ..exceptions import DeserializeError, IncrementalDeserializeError, LimitOverrunError
from ..lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from .abc import BufferedIncrementalPacketSerializer
from .tools import GeneratorStreamReader

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class AutoSeparatedPacketSerializer(BufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, bytearray]):
    """
    Base class for stream protocols that separates sent information by a byte sequence.
    """

    __slots__ = ("__separator", "__limit", "__incremental_serialize_check_separator", "__debug")

    def __init__(
        self,
        separator: bytes,
        *,
        incremental_serialize_check_separator: bool = True,
        limit: int = DEFAULT_SERIALIZER_LIMIT,
        debug: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Parameters:
            separator: Byte sequence that indicates the end of the token.
            incremental_serialize_check_separator: If :data:`True` (the default), checks that the data returned by
                                                   :meth:`serialize` does not contain `separator`,
                                                   and removes superfluous `separator` added at the end.
            limit: Maximum buffer size.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
            kwargs: Extra options given to ``super().__init__()``.

        Raises:
            TypeError: Invalid arguments.
            ValueError: Empty `separator` sequence.
            ValueError: `limit` must be a positive integer.
        """
        super().__init__(**kwargs)
        separator = bytes(separator)
        if len(separator) < 1:
            raise ValueError("Empty separator")
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        self.__separator: bytes = separator
        self.__limit: int = limit
        self.__incremental_serialize_check_separator = bool(incremental_serialize_check_separator)
        self.__debug: bool = bool(debug)

    @abstractmethod
    def serialize(self, packet: _T_SentDTOPacket, /) -> bytes:
        """
        See :meth:`.AbstractPacketSerializer.serialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_serialize(self, packet: _T_SentDTOPacket, /) -> Generator[bytes]:
        """
        Yields the data returned by :meth:`serialize` and appends `separator`.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.

        Raises:
            ValueError: If `incremental_serialize_check_separator` is `True` and `separator` is in the returned data.
            Exception: Any error raised by :meth:`serialize`.
        """
        data: bytes = self.serialize(packet)
        separator: bytes = self.__separator
        if self.__incremental_serialize_check_separator:
            while data.endswith(separator):
                data = data.removesuffix(separator)
            if separator in data:
                raise ValueError(f"{separator!r} separator found in serialized packet {packet!r} which was not at the end")
        elif data.endswith(separator):
            yield data
            return
        if not data:
            return
        data += separator
        yield data

    @abstractmethod
    def deserialize(self, data: bytes, /) -> _T_ReceivedDTOPacket:
        """
        See :meth:`.AbstractPacketSerializer.deserialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
        """
        Yields until `separator` is found and calls :meth:`deserialize` **without** `separator`.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Raises:
            LimitOverrunError: Reached buffer size limit.
            IncrementalDeserializeError: :meth:`deserialize` raised :exc:`.DeserializeError`.
            Exception: Any error raised by :meth:`deserialize`.
        """
        reader = GeneratorStreamReader()
        data = yield from reader.read_until(self.__separator, limit=self.__limit, keep_end=False)
        remainder = reader.read_all()

        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=remainder,
                error_info=exc.error_info,
            ) from exc
        finally:
            del data
        return packet, remainder

    @final
    def create_deserializer_buffer(self, sizehint: int) -> bytearray:
        """
        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.
        """

        # Ignore sizehint, we have our own limit
        return bytearray(self.__limit)

    @final
    def buffered_incremental_deserialize(self, buffer: bytearray) -> Generator[int, int, tuple[_T_ReceivedDTOPacket, memoryview]]:
        """
        Yields until `separator` is found and calls :meth:`deserialize` **without** `separator`.

        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.

        Raises:
            LimitOverrunError: Reached buffer size limit.
            IncrementalDeserializeError: :meth:`deserialize` raised :exc:`.DeserializeError`.
            Exception: Any error raised by :meth:`deserialize`.
        """
        with memoryview(buffer) as buffer_view:
            sepidx, offset, buflen = yield from _buffered_readuntil(buffer, self.__separator)
            del buffer

            data = bytes(buffer_view[:sepidx])
            remainder: memoryview = buffer_view[offset:buflen]
            try:
                packet = self.deserialize(data)
            except DeserializeError as exc:
                raise IncrementalDeserializeError(
                    f"Error when deserializing data: {exc}",
                    remaining_data=remainder,
                    error_info=exc.error_info,
                ) from exc
            return packet, remainder

    @property
    @final
    def separator(self) -> bytes:
        """
        Byte sequence that indicates the end of the token. Read-only attribute.
        """
        return self.__separator

    @property
    @final
    def debug(self) -> bool:
        """
        The debug mode flag. Read-only attribute.
        """
        return self.__debug

    @property
    @final
    def buffer_limit(self) -> int:
        """
        Maximum buffer size. Read-only attribute.
        """
        return self.__limit


class FixedSizePacketSerializer(BufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, memoryview]):
    """
    A base class for stream protocols in which the packets are of a fixed size.
    """

    __slots__ = ("__size", "__debug")

    def __init__(self, size: int, *, debug: bool = False, **kwargs: Any) -> None:
        """
        Parameters:
            size: The expected data size.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
            kwargs: Extra options given to ``super().__init__()``.

        Raises:
            TypeError: Invalid integer.
            ValueError: `size` is negative or null.
        """
        super().__init__(**kwargs)
        size = int(size)
        if size <= 0:
            raise ValueError("size must be a positive integer")
        self.__size: int = size
        self.__debug: bool = bool(debug)

    @abstractmethod
    def serialize(self, packet: _T_SentDTOPacket, /) -> bytes:
        """
        See :meth:`.AbstractPacketSerializer.serialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_serialize(self, packet: _T_SentDTOPacket, /) -> Generator[bytes]:
        """
        Yields the data returned by :meth:`serialize`.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.

        Raises:
            ValueError: If the returned data size is not equal to `packet_size`.
            Exception: Any error raised by :meth:`serialize`.
        """
        data = self.serialize(packet)
        if len(data) != self.__size:
            raise ValueError("serialized data size does not meet expectation")
        yield data

    @abstractmethod
    def deserialize(self, data: bytes, /) -> _T_ReceivedDTOPacket:
        """
        See :meth:`.AbstractPacketSerializer.deserialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
        """
        Yields until there is enough data and calls :meth:`deserialize`.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Raises:
            IncrementalDeserializeError: :meth:`deserialize` raised :exc:`.DeserializeError`.
            Exception: Any error raised by :meth:`deserialize`.
        """
        reader = GeneratorStreamReader()
        data = yield from reader.read_exactly(self.__size)
        remainder = reader.read_all()

        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=remainder,
                error_info=exc.error_info,
            ) from exc
        finally:
            del data
        return packet, remainder

    @final
    def create_deserializer_buffer(self, sizehint: int, /) -> memoryview:
        """
        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.
        """
        bufsize: int = max(self.__size, sizehint)
        return memoryview(bytearray(bufsize))

    @final
    def buffered_incremental_deserialize(
        self,
        buffer: memoryview,
        /,
    ) -> Generator[int, int, tuple[_T_ReceivedDTOPacket, memoryview]]:
        """
        Yields until there is enough data and calls :meth:`deserialize`.

        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.

        Raises:
            IncrementalDeserializeError: :meth:`deserialize` raised :exc:`.DeserializeError`.
            Exception: Any error raised by :meth:`deserialize`.
        """
        packet_size: int = self.__size
        assert len(buffer) >= packet_size  # nosec assert_used

        nread: int = 0
        while nread < packet_size:
            nread += yield nread

        data = bytes(buffer[:packet_size])
        remainder = buffer[packet_size:nread]
        del buffer

        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=remainder,
                error_info=exc.error_info,
            ) from exc
        return packet, remainder

    @property
    @final
    def packet_size(self) -> int:
        """
        The expected data size. Read-only attribute.
        """
        return self.__size

    @property
    @final
    def debug(self) -> bool:
        """
        The debug mode flag. Read-only attribute.
        """
        return self.__debug


class FileBasedPacketSerializer(BufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, memoryview]):
    """
    Base class for APIs requiring a :std:term:`file object` for serialization/deserialization.
    """

    __slots__ = ("__expected_errors", "__limit", "__debug")

    def __init__(
        self,
        expected_load_error: type[Exception] | tuple[type[Exception], ...],
        *,
        limit: int = DEFAULT_SERIALIZER_LIMIT,
        debug: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Parameters:
            expected_load_error: Errors that can be raised by :meth:`load_from_file` implementation,
                                 which must be considered as deserialization errors.
            limit: Maximum buffer size.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
            kwargs: Extra options given to ``super().__init__()``.
        """
        super().__init__(**kwargs)
        if not isinstance(expected_load_error, tuple):
            expected_load_error = (expected_load_error,)
        assert all(issubclass(e, Exception) for e in expected_load_error)  # nosec assert_used

        if limit <= 0:
            raise ValueError("limit must be a positive integer")

        self.__limit: int = limit
        self.__expected_errors: tuple[type[Exception], ...] = expected_load_error
        self.__debug: bool = bool(debug)

    @abstractmethod
    def dump_to_file(self, packet: _T_SentDTOPacket, file: IO[bytes], /) -> None:
        """
        Write the serialized `packet` to `file`.

        Parameters:
            packet: The Python object to serialize.
            file: The :std:term:`binary file` to write to.
        """
        raise NotImplementedError

    @abstractmethod
    def load_from_file(self, file: IO[bytes], /) -> _T_ReceivedDTOPacket:
        """
        Read from `file` to deserialize the raw :term:`packet`.

        Parameters:
            file: The :std:term:`binary file` to read from.

        Raises:
            EOFError: Missing data to create the :term:`packet`.
            Exception: Any error from the underlying API that is interpreted with the `expected_load_error` value.

        Returns:
            the deserialized Python object.
        """
        raise NotImplementedError

    def serialize(self, packet: _T_SentDTOPacket, /) -> bytes:
        """
        Returns the byte representation of the Python object `packet`.

        By default, this method uses :meth:`dump_to_file`, but it can be overriden for speicific usage.

        See :meth:`.AbstractPacketSerializer.serialize` documentation for details.

        Raises:
            Exception: Any error raised by :meth:`dump_to_bytes`.
        """
        with BytesIO() as buffer:
            self.dump_to_file(packet, buffer)
            return buffer.getvalue()

    def deserialize(self, data: bytes, /) -> _T_ReceivedDTOPacket:
        """
        Creates a Python object representing the raw :term:`packet` from `data`.

        By default, this method uses :meth:`load_from_file`, but it can be overriden for speicific usage.

        See :meth:`.AbstractPacketSerializer.deserialize` documentation for details.

        Raises:
            DeserializeError: :meth:`load_from_file` raised :class:`EOFError`.
            DeserializeError: :meth:`load_from_file` does not read until EOF (unused trailing data).
            DeserializeError: :meth:`load_from_file` raised an error that matches `expected_load_error`.
            Exception: Any other error raised by :meth:`load_from_file`.
        """
        with BytesIO(data) as buffer:
            try:
                packet: _T_ReceivedDTOPacket = self.load_from_file(buffer)
            except EOFError as exc:
                msg = "Missing data to create packet"
                if self.debug:
                    raise DeserializeError(msg, error_info={"data": data}) from exc
                raise DeserializeError(msg) from exc
            except self.__expected_errors as exc:
                msg = str(exc)
                if self.debug:
                    raise DeserializeError(msg, error_info={"data": data}) from exc
                raise DeserializeError(msg) from exc
            finally:
                del data
            if extra := buffer.read():  # There is still data after deserialization
                msg = "Extra data caught"
                if self.debug:
                    raise DeserializeError(msg, error_info={"packet": packet, "extra": extra})
                raise DeserializeError(msg)
        return packet

    @final
    def incremental_serialize(self, packet: _T_SentDTOPacket, /) -> Generator[bytes]:
        """
        Calls :meth:`dump_to_file` and yields the result.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.

        Raises:
            Exception: Any error raised by :meth:`dump_to_file`.
        """
        with BytesIO() as buffer:
            self.dump_to_file(packet, buffer)
            if buffer.getbuffer().nbytes == 0:
                return
            data = buffer.getvalue()
        yield data

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
        """
        Calls :meth:`load_from_file` and returns the result.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Note:
            The generator will always :keyword:`yield` if :meth:`load_from_file` raises :class:`EOFError`.

        Raises:
            IncrementalDeserializeError: :meth:`load_from_file` raised an error that matches `expected_load_error`.
            Exception: Any other error raised by :meth:`load_from_file`.
        """
        return (yield from _wrap_generic_incremental_deserialize(self.__generic_incremental_deserialize))

    @final
    def create_deserializer_buffer(self, sizehint: int, /) -> memoryview:
        """
        See :meth:`.BufferedIncrementalPacketSerializer.create_deserializer_buffer` documentation for details.
        """
        sizehint = min(sizehint, self.__limit)
        return memoryview(bytearray(sizehint))

    @final
    def buffered_incremental_deserialize(
        self,
        buffer: memoryview,
        /,
    ) -> Generator[None, int, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
        """
        Calls :meth:`load_from_file` and returns the result.

        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.

        Note:
            The generator will always :keyword:`yield` if :meth:`load_from_file` raises :class:`EOFError`.

        Raises:
            IncrementalDeserializeError: :meth:`load_from_file` raised an error that matches `expected_load_error`.
            Exception: Any other error raised by :meth:`load_from_file`.
        """
        return (yield from _wrap_generic_buffered_incremental_deserialize(buffer, self.__generic_incremental_deserialize))

    def __generic_incremental_deserialize(self) -> Generator[None, ReadableBuffer, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
        with BytesIO((yield)) as buffer:
            initial: bool = True
            while True:
                if not initial:
                    buffer.write((yield))
                    buffer.seek(0)
                self.__check_file_buffer_limit(buffer)
                try:
                    packet: _T_ReceivedDTOPacket = self.load_from_file(buffer)
                except EOFError:
                    pass
                except self.__expected_errors as exc:
                    msg = f"Deserialize error: {exc}"
                    if self.debug:
                        raise IncrementalDeserializeError(
                            msg,
                            remaining_data=buffer.read(),
                            error_info={"data": buffer.getvalue()},
                        ) from exc
                    raise IncrementalDeserializeError(msg, remaining_data=buffer.read()) from exc
                else:
                    return packet, buffer.read()
                finally:
                    initial = False

    def __check_file_buffer_limit(self, file: BytesIO) -> None:
        with file.getbuffer() as buffer_view:
            if buffer_view.nbytes > self.__limit:
                raise LimitOverrunError("chunk exceeded buffer limit", buffer_view, consumed=buffer_view.nbytes)

    @property
    @final
    def debug(self) -> bool:
        """
        The debug mode flag. Read-only attribute.
        """
        return self.__debug

    @property
    @final
    def buffer_limit(self) -> int:
        """
        Maximum buffer size. Read-only attribute.
        """
        return self.__limit


def _wrap_generic_incremental_deserialize(
    func: Callable[[], Generator[None, ReadableBuffer, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]],
) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
    packet, remainder = yield from func()
    # remainder is not copied if it is already a "bytes" object
    remainder = bytes(remainder)
    return packet, remainder


def _wrap_generic_buffered_incremental_deserialize(
    buffer: memoryview,
    func: Callable[[], Generator[None, ReadableBuffer, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]],
) -> Generator[None, int, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
    next(gen := func())
    with contextlib.closing(gen):
        while True:
            nbytes: int = yield
            try:
                gen.send(buffer[:nbytes])
            except StopIteration as exc:
                return exc.value


def _buffered_readuntil(
    buffer: bytearray,
    separator: bytes,
) -> Generator[int, int, tuple[int, int, int]]:
    last_idx = len(buffer) - 1
    seplen: int = len(separator)
    limit = last_idx - seplen
    buflen: int = yield 0

    offset: int = 0
    sepidx: int = -1
    while True:
        if buflen - offset >= seplen:
            sepidx = buffer.find(separator, offset, buflen)

            if sepidx != -1:
                offset = sepidx + seplen
                return sepidx, offset, buflen

            offset = buflen + 1 - seplen
            if offset > limit:
                msg = "Separator is not found, and chunk exceed the limit"
                raise LimitOverrunError(msg, buffer, offset, separator)

        buflen += yield buflen
