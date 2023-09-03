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
    "AutoSeparatedPacketSerializer",
    "FileBasedPacketSerializer",
    "FixedSizePacketSerializer",
]

from abc import abstractmethod
from collections.abc import Generator
from io import BytesIO
from typing import IO, Any, final

from .._typevars import _DeserializedPacketT_co, _SerializedPacketT_contra
from ..exceptions import DeserializeError, IncrementalDeserializeError
from .abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer


class AutoSeparatedPacketSerializer(AbstractIncrementalPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    """
    Base class for stream protocols that separates sent information by a byte sequence.
    """

    __slots__ = ("__separator", "__incremental_serialize_check_separator")

    def __init__(self, separator: bytes, *, incremental_serialize_check_separator: bool = True, **kwargs: Any) -> None:
        """
        Parameters:
            separator: Byte sequence that indicates the end of the token.
            incremental_serialize_check_separator: If `True` (the default), checks that the data returned by
                                                   :meth:`serialize` does not contain `separator`,
                                                   and removes superfluous `separator` added at the end.
            kwargs: Extra options given to ``super().__init__()``.

        Raises:
            TypeError: Invalid arguments.
            ValueError: Empty separator sequence.
        """
        super().__init__(**kwargs)
        separator = bytes(separator)
        if len(separator) < 1:
            raise ValueError("Empty separator")
        self.__separator: bytes = separator
        self.__incremental_serialize_check_separator = bool(incremental_serialize_check_separator)

    @abstractmethod
    def serialize(self, packet: _SerializedPacketT_contra, /) -> bytes:
        """
        See :meth:`AbstractPacketSerializer.serialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_serialize(self, packet: _SerializedPacketT_contra, /) -> Generator[bytes, None, None]:
        """
        Yields the data returned by :meth:`serialize` and appends `separator`.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.

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
        yield data
        del data
        yield separator

    @abstractmethod
    def deserialize(self, data: bytes, /) -> _DeserializedPacketT_co:
        """
        See :meth:`AbstractPacketSerializer.deserialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DeserializedPacketT_co, bytes]]:
        """
        Yields until `separator` is found and calls :meth:`deserialize` **without** `separator`.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Raises:
            IncrementalDeserializeError: :meth:`deserialize` raised :exc:`.DeserializeError`.
            Exception: Any error raised by :meth:`deserialize`.
        """
        buffer: bytes = yield
        separator: bytes = self.__separator
        separator_length: int = len(separator)
        while True:
            data, found_separator, buffer = buffer.partition(separator)
            if found_separator:
                del found_separator
                if not data:  # There was successive separators
                    continue
                break
            assert not buffer  # nosec assert_used
            buffer = data + (yield)
        while buffer.startswith(separator):  # Remove successive separators which can already be eliminated
            buffer = buffer[separator_length:]
        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=buffer,
                error_info=exc.error_info,
            ) from exc
        finally:
            del data
        return packet, buffer

    @property
    @final
    def separator(self) -> bytes:
        """
        Byte sequence that indicates the end of the token. Read-only attribute.
        """
        return self.__separator


class FixedSizePacketSerializer(AbstractIncrementalPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    """
    A base class for stream protocols in which the packets are of a fixed size.
    """

    __slots__ = ("__size",)

    def __init__(self, size: int, **kwargs: Any) -> None:
        """
        Parameters:
            size: The expected data size.
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

    @abstractmethod
    def serialize(self, packet: _SerializedPacketT_contra, /) -> bytes:
        """
        See :meth:`AbstractPacketSerializer.serialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_serialize(self, packet: _SerializedPacketT_contra, /) -> Generator[bytes, None, None]:
        """
        Yields the data returned by :meth:`serialize`.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.

        Raises:
            ValueError: If the returned data size is not equal to `packet_size`.
            Exception: Any error raised by :meth:`serialize`.
        """
        data = self.serialize(packet)
        if len(data) != self.__size:
            raise ValueError("serialized data size does not meet expectation")
        yield data

    @abstractmethod
    def deserialize(self, data: bytes, /) -> _DeserializedPacketT_co:
        """
        See :meth:`AbstractPacketSerializer.deserialize` documentation.
        """
        raise NotImplementedError

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DeserializedPacketT_co, bytes]]:
        """
        Yields until there is enough data and calls :meth:`deserialize`.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Raises:
            IncrementalDeserializeError: :meth:`deserialize` raised :exc:`.DeserializeError`.
            Exception: Any error raised by :meth:`deserialize`.
        """
        buffer: bytes = yield
        packet_size: int = self.__size
        while (buffer_size := len(buffer)) < packet_size:
            buffer += yield

        # Do not copy if the size is *exactly* as expected
        if buffer_size == packet_size:
            data = buffer
            buffer = b""
        else:
            data = buffer[:packet_size]
            buffer = buffer[packet_size:]
        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=buffer,
                error_info=exc.error_info,
            ) from exc
        finally:
            del data
        return packet, buffer

    @property
    @final
    def packet_size(self) -> int:
        """
        The expected data size. Read-only attribute.
        """
        return self.__size


class FileBasedPacketSerializer(AbstractPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    """
    Base class for APIs requiring a :std:term:`file object` for serialization/deserialization.
    """

    __slots__ = ("__expected_errors",)

    def __init__(self, expected_load_error: type[Exception] | tuple[type[Exception], ...], **kwargs: Any) -> None:
        """
        Parameters:
            expected_load_error: Errors that can be raised by :meth:`load_from_file` implementation,
                                 which must be considered as deserialization errors.
            kwargs: Extra options given to ``super().__init__()``.
        """
        super().__init__(**kwargs)
        if not isinstance(expected_load_error, tuple):
            expected_load_error = (expected_load_error,)
        assert all(issubclass(e, Exception) for e in expected_load_error)  # nosec assert_used
        self.__expected_errors: tuple[type[Exception], ...] = expected_load_error

    @abstractmethod
    def dump_to_file(self, packet: _SerializedPacketT_contra, file: IO[bytes], /) -> None:
        """
        Write the serialized `packet` to `file`.

        Parameters:
            packet: The Python object to serialize.
            file: The :std:term:`binary file` to write to.
        """
        raise NotImplementedError

    @abstractmethod
    def load_from_file(self, file: IO[bytes], /) -> _DeserializedPacketT_co:
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

    @final
    def serialize(self, packet: _SerializedPacketT_contra, /) -> bytes:
        """
        Calls :meth:`dump_to_file` and returns the result.

        See :meth:`AbstractPacketSerializer.serialize` documentation for details.

        Raises:
            Exception: Any error raised by :meth:`dump_to_file`.
        """
        with BytesIO() as buffer:
            self.dump_to_file(packet, buffer)
            return buffer.getvalue()

    @final
    def deserialize(self, data: bytes, /) -> _DeserializedPacketT_co:
        """
        Calls :meth:`load_from_file` and returns the result.

        See :meth:`AbstractPacketSerializer.deserialize` documentation for details.

        Raises:
            DeserializeError: :meth:`load_from_file` raised :class:`EOFError`.
            DeserializeError: :meth:`load_from_file` does not read until EOF (unused trailing data).
            DeserializeError: :meth:`load_from_file` raised an error that matches `expected_load_error`.
            Exception: Any other error raised by :meth:`load_from_file`.
        """
        with BytesIO(data) as buffer:
            try:
                packet: _DeserializedPacketT_co = self.load_from_file(buffer)
            except EOFError as exc:
                raise DeserializeError("Missing data to create packet", error_info={"data": data}) from exc
            except self.__expected_errors as exc:
                raise DeserializeError(str(exc), error_info={"data": data}) from exc
            finally:
                del data
            if extra := buffer.read():  # There is still data after deserialization
                raise DeserializeError("Extra data caught", error_info={"packet": packet, "extra": extra})
        return packet

    @final
    def incremental_serialize(self, packet: _SerializedPacketT_contra, /) -> Generator[bytes, None, None]:
        """
        Calls :meth:`dump_to_file` and yields the result.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.

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
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DeserializedPacketT_co, bytes]]:
        """
        Calls :meth:`load_from_file` and returns the result.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Note:
            The generator will always :keyword:`yield` if :meth:`load_from_file` raises :class:`EOFError`.

        Raises:
            IncrementalDeserializeError: :meth:`load_from_file` raised an error that matches `expected_load_error`.
            Exception: Any other error raised by :meth:`load_from_file`.
        """
        with BytesIO((yield)) as buffer:
            initial: bool = True
            while True:
                if not initial:
                    buffer.write((yield))
                    buffer.seek(0)
                try:
                    packet: _DeserializedPacketT_co = self.load_from_file(buffer)
                except EOFError:
                    continue
                except self.__expected_errors as exc:
                    remaining_data: bytes = buffer.read()
                    if not remaining_data:  # Possibly an EOF error, give it a chance
                        continue
                    raise IncrementalDeserializeError(
                        f"Deserialize error: {exc}",
                        remaining_data=remaining_data,
                        error_info={"data": buffer.getvalue()},
                    ) from exc
                else:
                    return packet, buffer.read()
                finally:
                    initial = False
