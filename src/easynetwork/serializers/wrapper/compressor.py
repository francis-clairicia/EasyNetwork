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
from typing import TYPE_CHECKING, Protocol, final

from ..._typevars import _DeserializedPacketT_co, _SerializedPacketT_contra
from ...exceptions import DeserializeError, IncrementalDeserializeError
from ..abc import AbstractIncrementalPacketSerializer, AbstractPacketSerializer

if TYPE_CHECKING:
    import bz2 as _typing_bz2
    import zlib as _typing_zlib


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


class AbstractCompressorSerializer(AbstractIncrementalPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    """
    A :term:`serializer wrapper` base class for compressors.
    """

    __slots__ = ("__serializer", "__expected_error")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co],
        expected_decompress_error: type[Exception] | tuple[type[Exception], ...],
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            expected_decompress_error: Errors that can be raised by :meth:`DecompressorInterface.decompress` implementation,
                                       which must be considered as deserialization errors.
        """
        super().__init__()
        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        if not isinstance(expected_decompress_error, tuple):
            expected_decompress_error = (expected_decompress_error,)
        assert all(issubclass(e, Exception) for e in expected_decompress_error)  # nosec assert_used
        self.__serializer: AbstractPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co] = serializer
        self.__expected_error: tuple[type[Exception], ...] = expected_decompress_error

    @abc.abstractmethod
    def new_compressor_stream(self) -> CompressorInterface:
        """
        Returns:
            an object suitable for data compression.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def new_decompressor_stream(self) -> DecompressorInterface:
        """
        Returns:
            an object suitable for data decompression.
        """
        raise NotImplementedError

    @final
    def serialize(self, packet: _SerializedPacketT_contra) -> bytes:
        """
        Serializes `packet` and returns the compressed data parts.

        See :meth:`AbstractPacketSerializer.serialize` documentation for details.
        """
        compressor: CompressorInterface = self.new_compressor_stream()
        return compressor.compress(self.__serializer.serialize(packet)) + compressor.flush()

    @final
    def incremental_serialize(self, packet: _SerializedPacketT_contra) -> Generator[bytes, None, None]:
        """
        Serializes `packet` and yields the compressed data parts.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.
        """
        compressor: CompressorInterface = self.new_compressor_stream()
        yield compressor.compress(self.__serializer.serialize(packet))
        yield compressor.flush()

    @final
    def deserialize(self, data: bytes) -> _DeserializedPacketT_co:
        """
        Decompresses `data` and returns the deserialized packet.

        See :meth:`AbstractPacketSerializer.deserialize` documentation for details.

        Raises:
            DeserializeError: :meth:`DecompressorInterface.decompress` does not read until EOF (unused trailing data).
            DeserializeError: :meth:`DecompressorInterface.decompress` raised an error that matches `expected_decompress_error`.
            Exception: Any other error raised by :meth:`DecompressorInterface.decompress` or the underlying serializer.
        """
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
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DeserializedPacketT_co, bytes]]:
        """
        Yields until data decompression is finished and deserializes the decompressed data using the underlying serializer.

        See :meth:`AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Raises:
            IncrementalDeserializeError: :meth:`DecompressorInterface.decompress` raised an error
                                         that matches `expected_decompress_error`.
            Exception: Any other error raised by :meth:`DecompressorInterface.decompress` or the underlying serializer.
        """
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
            packet: _DeserializedPacketT_co = self.__serializer.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error while deserializing decompressed data: {exc}",
                remaining_data=unused_data,
                error_info=exc.error_info,
            ) from exc

        return packet, unused_data


class BZ2CompressorSerializer(AbstractCompressorSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    """
    A :term:`serializer wrapper` to handle bzip2 compressed data, built on top of :mod:`bz2` module.
    """

    __slots__ = ("__compresslevel", "__compressor_factory", "__decompressor_factory")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co],
        *,
        compress_level: int | None = None,
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            compress_level: bzip2 compression level. Defaults to ``9``.
        """
        import bz2

        super().__init__(serializer=serializer, expected_decompress_error=OSError)
        self.__compresslevel: int = compress_level if compress_level is not None else 9
        self.__compressor_factory = bz2.BZ2Compressor
        self.__decompressor_factory = bz2.BZ2Decompressor

    @final
    def new_compressor_stream(self) -> _typing_bz2.BZ2Compressor:
        """
        See :meth:`AbstractCompressorSerializer.new_compressor_stream` documentation for details.
        """
        return self.__compressor_factory(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> _typing_bz2.BZ2Decompressor:
        """
        See :meth:`AbstractCompressorSerializer.new_decompressor_stream` documentation for details.
        """
        return self.__decompressor_factory()


class ZlibCompressorSerializer(AbstractCompressorSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    """
    A :term:`serializer wrapper` to handle zlib compressed data, built on top of :mod:`zlib` module.
    """

    __slots__ = ("__compresslevel", "__compressor_factory", "__decompressor_factory")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co],
        *,
        compress_level: int | None = None,
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            compress_level: bzip2 compression level. Defaults to :data:`zlib.Z_BEST_COMPRESSION`.
        """
        import zlib

        super().__init__(serializer=serializer, expected_decompress_error=zlib.error)
        self.__compresslevel: int = compress_level if compress_level is not None else zlib.Z_BEST_COMPRESSION
        self.__compressor_factory = zlib.compressobj
        self.__decompressor_factory = zlib.decompressobj

    @final
    def new_compressor_stream(self) -> _typing_zlib._Compress:
        """
        See :meth:`AbstractCompressorSerializer.new_compressor_stream` documentation for details.
        """
        return self.__compressor_factory(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> _typing_zlib._Decompress:
        """
        See :meth:`AbstractCompressorSerializer.new_decompressor_stream` documentation for details.
        """
        return self.__decompressor_factory()
