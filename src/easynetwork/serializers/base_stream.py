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
from typing import IO, Any, TypeVar, final

from ..exceptions import DeserializeError, IncrementalDeserializeError
from .abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class AutoSeparatedPacketSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__separator", "__incremental_serialize_check_separator")

    def __init__(self, separator: bytes, *, incremental_serialize_check_separator: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        assert isinstance(separator, bytes)
        if len(separator) < 1:
            raise ValueError("Empty separator")
        self.__separator: bytes = separator
        self.__incremental_serialize_check_separator = bool(incremental_serialize_check_separator)

    @abstractmethod
    def serialize(self, packet: _ST_contra) -> bytes:
        raise NotImplementedError

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
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
    def deserialize(self, data: bytes) -> _DT_co:
        raise NotImplementedError

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
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
            assert not buffer
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
        return self.__separator


class FixedSizePacketSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__size",)

    def __init__(self, size: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        size = int(size)
        if size <= 0:
            raise ValueError("size must be a positive integer")
        self.__size: int = size

    @abstractmethod
    def serialize(self, packet: _ST_contra) -> bytes:
        raise NotImplementedError

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        data = self.serialize(packet)
        if len(data) != self.__size:
            raise ValueError("serialized data size does not meet expectation")
        yield data

    @abstractmethod
    def deserialize(self, data: bytes) -> _DT_co:
        raise NotImplementedError

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
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
        return self.__size


class FileBasedPacketSerializer(AbstractPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__expected_errors",)

    def __init__(self, expected_load_error: type[Exception] | tuple[type[Exception], ...], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not isinstance(expected_load_error, tuple):
            expected_load_error = (expected_load_error,)
        assert all(issubclass(e, Exception) for e in expected_load_error)
        self.__expected_errors: tuple[type[Exception], ...] = expected_load_error

    @abstractmethod
    def dump_to_file(self, packet: _ST_contra, file: IO[bytes]) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_from_file(self, file: IO[bytes]) -> _DT_co:
        raise NotImplementedError

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        with BytesIO() as buffer:
            self.dump_to_file(packet, buffer)
            return buffer.getvalue()

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        with BytesIO(data) as buffer:
            try:
                packet: _DT_co = self.load_from_file(buffer)
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
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        with BytesIO() as buffer:
            self.dump_to_file(packet, buffer)
            if buffer.getbuffer().nbytes == 0:
                return
            data = buffer.getvalue()
        yield data

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        with BytesIO((yield)) as buffer:
            initial: bool = True
            while True:
                if not initial:
                    buffer.write((yield))
                    buffer.seek(0)
                try:
                    packet: _DT_co = self.load_from_file(buffer)
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
