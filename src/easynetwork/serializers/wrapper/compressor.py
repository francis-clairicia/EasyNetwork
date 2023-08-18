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
"""Data compressor serializer module"""

from __future__ import annotations

__all__ = [
    "AbstractCompressorSerializer",
    "BZ2CompressorSerializer",
    "ZlibCompressorSerializer",
]

import abc
from collections import deque
from collections.abc import Generator
from typing import Protocol, final

from ...exceptions import DeserializeError, IncrementalDeserializeError
from .._typevars import DeserializedPacketT_co, SerializedPacketT_contra
from ..abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer


class CompressorInterface(Protocol, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def compress(self, data: bytes, /) -> bytes:
        raise NotImplementedError

    @abc.abstractmethod
    def flush(self) -> bytes:
        raise NotImplementedError


class DecompressorInterface(Protocol, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def decompress(self, data: bytes, /) -> bytes:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def eof(self) -> bool:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def unused_data(self) -> bytes:
        raise NotImplementedError


class AbstractCompressorSerializer(AbstractIncrementalPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
    __slots__ = ("__serializer", "__expected_error")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co],
        expected_decompress_error: type[Exception] | tuple[type[Exception], ...],
    ) -> None:
        super().__init__()
        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        if not isinstance(expected_decompress_error, tuple):
            expected_decompress_error = (expected_decompress_error,)
        assert all(issubclass(e, Exception) for e in expected_decompress_error)  # nosec assert_used
        self.__serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co] = serializer
        self.__expected_error: tuple[type[Exception], ...] = expected_decompress_error

    @abc.abstractmethod
    def new_compressor_stream(self) -> CompressorInterface:
        raise NotImplementedError

    @abc.abstractmethod
    def new_decompressor_stream(self) -> DecompressorInterface:
        raise NotImplementedError

    @final
    def serialize(self, packet: SerializedPacketT_contra) -> bytes:
        compressor: CompressorInterface = self.new_compressor_stream()
        return compressor.compress(self.__serializer.serialize(packet)) + compressor.flush()

    @final
    def incremental_serialize(self, packet: SerializedPacketT_contra) -> Generator[bytes, None, None]:
        compressor: CompressorInterface = self.new_compressor_stream()
        yield compressor.compress(self.__serializer.serialize(packet))
        yield compressor.flush()

    @final
    def deserialize(self, data: bytes) -> DeserializedPacketT_co:
        decompressor: DecompressorInterface = self.new_decompressor_stream()
        try:
            data = decompressor.decompress(data)
        except self.__expected_error as exc:
            raise DeserializeError(str(exc), error_info={"data": data}) from exc
        if not decompressor.eof:
            raise DeserializeError(
                "Compressed data ended before the end-of-stream marker was reached",
                error_info={"already_decompressed_data": data},
            )
        if decompressor.unused_data:
            raise DeserializeError(
                "Trailing data error",
                error_info={"decompressed_data": data, "extra": decompressor.unused_data},
            )
        del decompressor
        return self.__serializer.deserialize(data)

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[DeserializedPacketT_co, bytes]]:
        results: deque[bytes] = deque()
        decompressor: DecompressorInterface = self.new_decompressor_stream()
        while not decompressor.eof:
            chunk: bytes = yield
            try:
                chunk = decompressor.decompress(chunk)
            except self.__expected_error as exc:
                raise IncrementalDeserializeError(
                    message=f"Decompression error: {exc}",
                    remaining_data=b"",
                    error_info={
                        "already_decompressed_chunks": results,
                        "invalid_chunk": chunk,
                    },
                ) from exc
            if chunk:
                results.append(chunk)
            del chunk

        data = b"".join(results)
        unused_data: bytes = decompressor.unused_data
        del results, decompressor

        try:
            packet: DeserializedPacketT_co = self.__serializer.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error while deserializing decompressed data: {exc}",
                remaining_data=unused_data,
                error_info=exc.error_info,
            ) from exc

        return packet, unused_data


class BZ2CompressorSerializer(AbstractCompressorSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
    __slots__ = ("__compresslevel", "__compressor_factory", "__decompressor_factory")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co],
        *,
        compress_level: int | None = None,
    ) -> None:
        import bz2

        super().__init__(serializer=serializer, expected_decompress_error=OSError)
        self.__compresslevel: int = compress_level if compress_level is not None else 9
        self.__compressor_factory = bz2.BZ2Compressor
        self.__decompressor_factory = bz2.BZ2Decompressor

    @final
    def new_compressor_stream(self) -> CompressorInterface:
        return self.__compressor_factory(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> DecompressorInterface:
        return self.__decompressor_factory()


class ZlibCompressorSerializer(AbstractCompressorSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
    __slots__ = ("__compresslevel", "__compressor_factory", "__decompressor_factory")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co],
        *,
        compress_level: int | None = None,
    ) -> None:
        import zlib

        super().__init__(serializer=serializer, expected_decompress_error=zlib.error)
        self.__compresslevel: int = compress_level if compress_level is not None else zlib.Z_BEST_COMPRESSION
        self.__compressor_factory = zlib.compressobj
        self.__decompressor_factory = zlib.decompressobj

    @final
    def new_compressor_stream(self) -> CompressorInterface:
        return self.__compressor_factory(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> DecompressorInterface:
        return self.__decompressor_factory()
