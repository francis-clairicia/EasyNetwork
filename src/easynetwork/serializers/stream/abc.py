# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Stream network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "AbstractIncrementalPacketSerializer",
    "AutoSeparatedPacketSerializer",
    "FileBasedIncrementalPacketSerializer",
    "FixedSizePacketSerializer",
]

from abc import abstractmethod
from io import BytesIO
from typing import IO, Any, Generator, TypeVar, final

from ..abc import AbstractPacketSerializer
from ..exceptions import DeserializeError
from .exceptions import IncrementalDeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class AbstractIncrementalPacketSerializer(AbstractPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ()

    def serialize(self, packet: _ST_contra) -> bytes:
        # The list call should be roughly
        # equivalent to the PySequence_Fast that ''.join() would do.
        return b"".join(list(self.incremental_serialize(packet)))

    @abstractmethod
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        raise NotImplementedError

    def deserialize(self, data: bytes) -> _DT_co:
        consumer: Generator[None, bytes, tuple[_DT_co, bytes]] = self.incremental_deserialize()
        try:
            next(consumer)
        except StopIteration:
            raise RuntimeError("self.incremental_deserialize() generator did not yield") from None
        packet: _DT_co
        remaining: bytes
        try:
            consumer.send(data)
        except StopIteration as exc:
            packet, remaining = exc.value
        else:
            consumer.close()
            raise DeserializeError("Missing data to create packet") from None
        if remaining:
            raise DeserializeError("Extra data caught")
        return packet

    @abstractmethod
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        raise NotImplementedError


class AutoSeparatedPacketSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__separator", "__keepends")

    def __init__(self, separator: bytes, *, keepends: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        assert isinstance(separator, bytes)
        if len(separator) < 1:
            raise ValueError("Empty separator")
        self.__separator: bytes = separator
        self.__keepends: bool = bool(keepends)

    @abstractmethod
    def serialize(self, packet: _ST_contra) -> bytes:
        raise NotImplementedError

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        data: bytes = self.serialize(packet)
        separator: bytes = self.__separator
        data = data.rstrip(separator)
        if separator in data:
            raise ValueError(f"{separator!r} separator found in serialized packet {packet!r} which was not at the end")
        yield data + separator

    @abstractmethod
    def deserialize(self, data: bytes) -> _DT_co:
        raise NotImplementedError

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        buffer: bytes = yield
        separator: bytes = self.__separator
        while True:
            data, found_separator, buffer = buffer.partition(separator)
            if not found_separator:
                buffer = data + (yield)
                continue
            break
        if self.__keepends:
            data += separator
        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=buffer,
            ) from exc
        finally:
            del data
        return packet, buffer

    @property
    @final
    def separator(self) -> bytes:
        return self.__separator

    @property
    @final
    def keepends(self) -> bool:
        return self.__keepends


class FixedSizePacketSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__size",)

    def __init__(self, size: int, **kwargs: Any) -> None:
        size = int(size)
        if size <= 0:
            raise ValueError("size must be a positive integer")
        super().__init__(**kwargs)
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
        while len(buffer) < packet_size:
            buffer += yield
        data, buffer = buffer[:packet_size], buffer[packet_size:]
        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=buffer,
            ) from exc
        return packet, buffer

    @property
    @final
    def packet_size(self) -> int:
        return self.__size


class FileBasedIncrementalPacketSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__unrelated_error",)

    def __init__(
        self,
        unrelated_deserialize_error: type[Exception] | tuple[type[Exception], ...],
    ) -> None:
        super().__init__()
        self.__unrelated_error: type[Exception] | tuple[type[Exception], ...] = unrelated_deserialize_error

    @abstractmethod
    def _serialize_to_file(self, packet: _ST_contra, file: IO[bytes]) -> None:
        raise NotImplementedError

    @abstractmethod
    def _deserialize_from_file(self, file: IO[bytes]) -> _DT_co:
        raise NotImplementedError

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        with BytesIO() as buffer:
            self._serialize_to_file(packet, buffer)
            return buffer.getvalue()

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        with BytesIO() as buffer:
            self._serialize_to_file(packet, buffer)
            data = buffer.getvalue()
        yield data  # 'incremental' :)

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        with BytesIO(data) as buffer:
            try:
                packet: _DT_co = self._deserialize_from_file(buffer)
            except EOFError as exc:
                raise DeserializeError("Missing data to create packet") from exc
            except self.__unrelated_error as exc:
                raise DeserializeError(f"Unrelated error: {exc}") from exc
            if buffer.read():  # There is still data after deserializing
                raise DeserializeError("Extra data caught")
        return packet

    def _wait_for_next_chunk(self, given_chunk: bytes) -> bool:
        return False

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        with BytesIO() as buffer:
            while True:
                chunk: bytes = b""
                wait_for_next_chunk = self._wait_for_next_chunk
                while not chunk or wait_for_next_chunk(chunk):
                    chunk = yield
                    buffer.write(chunk)
                del chunk
                buffer.seek(0)
                try:
                    packet: _DT_co = self._deserialize_from_file(buffer)
                except EOFError:
                    continue
                except self.__unrelated_error as exc:
                    remaining_data: bytes = buffer.read()
                    if not remaining_data:  # Possibly an EOF error, give it a chance
                        continue
                    raise IncrementalDeserializeError(
                        f"Unrelated error: {exc}",
                        remaining_data=remaining_data,
                    ) from exc
                else:
                    return packet, buffer.read()
