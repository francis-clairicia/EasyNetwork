# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Stream network packet serializer handler module"""

from __future__ import annotations

__all__ = [
    "AutoSeparatedPacketSerializer",
    "FileBasedIncrementalPacketSerializer",
    "FixedSizePacketSerializer",
]

from abc import abstractmethod
from io import BytesIO
from typing import IO, Any, Generator, TypeVar, final

from .abc import AbstractIncrementalPacketSerializer
from .exceptions import DeserializeError, IncrementalDeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


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
        while data.endswith(separator):
            data = data.removesuffix(separator)
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
            if found_separator:
                if not data:  # There was successive separators
                    continue
                break
            assert not buffer
            buffer = data + (yield)
        if self.__keepends:
            data += separator
        while buffer.startswith(separator):  # Remove successive separators which can already be eliminated
            buffer = buffer.removeprefix(separator)
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

    @property
    @final
    def keepends(self) -> bool:
        return self.__keepends


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
        while len(buffer) < packet_size:
            buffer += yield
        data, buffer = buffer[:packet_size], buffer[packet_size:]
        try:
            packet = self.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error when deserializing data: {exc}",
                remaining_data=buffer,
                error_info=exc.error_info,
            ) from exc
        return packet, buffer

    @property
    @final
    def packet_size(self) -> int:
        return self.__size


class FileBasedIncrementalPacketSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__expected_error",)

    def __init__(self, expected_load_error: type[Exception] | tuple[type[Exception], ...], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not isinstance(expected_load_error, tuple):
            expected_load_error = (expected_load_error,)
        assert all(issubclass(e, Exception) for e in expected_load_error)
        self.__expected_error: tuple[type[Exception], ...] = expected_load_error

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
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        with BytesIO() as buffer:
            self.dump_to_file(packet, buffer)
            data = buffer.getvalue()
        if data:
            yield data

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        with BytesIO(data) as buffer:
            del data
            try:
                packet: _DT_co = self.load_from_file(buffer)
            except EOFError as exc:
                raise DeserializeError("Missing data to create packet") from exc
            except self.__expected_error as exc:
                raise DeserializeError(str(exc)) from exc
            if buffer.read():  # There is still data after deserialization
                raise DeserializeError("Extra data caught")
        return packet

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        with BytesIO() as buffer:
            while True:
                while not (chunk := (yield)):
                    continue
                buffer.write(chunk)
                del chunk
                buffer.seek(0)
                try:
                    packet: _DT_co = self.load_from_file(buffer)
                except EOFError:
                    continue
                except self.__expected_error as exc:
                    remaining_data: bytes = buffer.read()
                    if not remaining_data:  # Possibly an EOF error, give it a chance
                        continue
                    raise IncrementalDeserializeError(
                        f"Deserialize error: {exc}",
                        remaining_data=remaining_data,
                    ) from exc
                else:
                    return packet, buffer.read()
