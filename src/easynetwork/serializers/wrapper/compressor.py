# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Data compressor serializer module"""

from __future__ import annotations

__all__ = [
    "AbstractCompressorSerializer",
    "BZ2CompressorSerializer",
    "ZlibCompressorSerializer",
]

import abc
import bz2
import zlib
from collections import deque
from typing import Generator, Protocol, TypeVar, final

from ..abc import AbstractPacketSerializer
from ..exceptions import DeserializeError
from ..stream.abc import AbstractIncrementalPacketSerializer
from ..stream.exceptions import IncrementalDeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class Compressor(Protocol, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def compress(self, __data: bytes, /) -> bytes:
        raise NotImplementedError

    @abc.abstractmethod
    def flush(self) -> bytes:
        raise NotImplementedError


class Decompressor(Protocol, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def decompress(self, __data: bytes, /) -> bytes:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def eof(self) -> bool:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def unused_data(self) -> bytes:
        raise NotImplementedError


class AbstractCompressorSerializer(AbstractIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__serializer", "__trailing_error")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_ST_contra, _DT_co],
        trailing_error: type[Exception] | tuple[type[Exception], ...],
    ) -> None:
        assert isinstance(serializer, AbstractPacketSerializer)
        super().__init__()
        self.__serializer: AbstractPacketSerializer[_ST_contra, _DT_co] = serializer
        self.__trailing_error: type[Exception] | tuple[type[Exception], ...] = trailing_error

    @abc.abstractmethod
    def new_compressor_stream(self) -> Compressor:
        raise NotImplementedError

    @abc.abstractmethod
    def new_decompressor_stream(self) -> Decompressor:
        raise NotImplementedError

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        compressor = self.new_compressor_stream()
        return compressor.compress(self.__serializer.serialize(packet)) + compressor.flush()

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        compressor = self.new_compressor_stream()
        yield compressor.compress(self.__serializer.serialize(packet)) + compressor.flush()

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        if not data:
            raise DeserializeError("Empty bytes")
        decompressor = self.new_decompressor_stream()
        try:
            data = decompressor.decompress(data)
        except self.__trailing_error as exc:
            raise DeserializeError("Trailing data error") from exc
        if not decompressor.eof:
            raise DeserializeError("Compressed data ended before the end-of-stream marker was reached")
        if decompressor.unused_data:
            raise DeserializeError("Trailing data error")
        return self.__serializer.deserialize(data)

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        serializer = self.__serializer
        results: deque[bytes] = deque()
        decompressor = self.new_decompressor_stream()
        while not decompressor.eof:
            while not (chunk := (yield)):
                continue
            try:
                chunk = decompressor.decompress(chunk)
            except self.__trailing_error as exc:
                raise IncrementalDeserializeError(
                    message=f"Decompression error: {exc}",
                    remaining_data=b"",
                ) from exc
            if chunk:
                results.append(chunk)

        data = b"".join(results)
        unused_data: bytes = decompressor.unused_data
        del results, decompressor

        try:
            packet: _DT_co = serializer.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error while deserializing decompressed data: {exc}",
                remaining_data=unused_data,
            ) from exc

        return packet, unused_data


class BZ2CompressorSerializer(AbstractCompressorSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__compresslevel",)

    def __init__(self, serializer: AbstractPacketSerializer[_ST_contra, _DT_co], *, compresslevel: int = 9) -> None:
        super().__init__(serializer=serializer, trailing_error=OSError)
        self.__compresslevel: int = int(compresslevel)

    @final
    def new_compressor_stream(self) -> bz2.BZ2Compressor:
        return bz2.BZ2Compressor(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> bz2.BZ2Decompressor:
        return bz2.BZ2Decompressor()


class ZlibCompressorSerializer(AbstractCompressorSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__compresslevel",)

    def __init__(
        self, serializer: AbstractPacketSerializer[_ST_contra, _DT_co], *, compresslevel: int = zlib.Z_BEST_COMPRESSION
    ) -> None:
        assert isinstance(serializer, AbstractPacketSerializer)
        super().__init__(serializer=serializer, trailing_error=zlib.error)
        self.__compresslevel: int = int(compresslevel)

    @final
    def new_compressor_stream(self) -> zlib._Compress:
        return zlib.compressobj(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> zlib._Decompress:
        return zlib.decompressobj()
