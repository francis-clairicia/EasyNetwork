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
"""Data compressor serializer module."""

from __future__ import annotations

__all__ = [
    "AbstractCompressorSerializer",
    "BZ2CompressorSerializer",
    "CompressorInterface",
    "DecompressorInterface",
    "ZlibCompressorSerializer",
]

import abc
from collections import deque
from collections.abc import Generator
from typing import TYPE_CHECKING, Protocol, final

from ..._typevars import _T_ReceivedDTOPacket, _T_SentDTOPacket
from ...exceptions import DeserializeError, IncrementalDeserializeError
from ..abc import AbstractPacketSerializer, BufferedIncrementalPacketSerializer
from ..base_stream import _wrap_generic_buffered_incremental_deserialize, _wrap_generic_incremental_deserialize

if TYPE_CHECKING:
    from bz2 import BZ2Compressor, BZ2Decompressor
    from zlib import _Compress as ZLibCompress, _Decompress as ZLibDecompress

    from _typeshed import ReadableBuffer


class CompressorInterface(Protocol, metaclass=abc.ABCMeta):
    """A compressor object."""

    @abc.abstractmethod
    def compress(self, data: ReadableBuffer, /) -> bytes:
        """
        Provide data to the compressor object.

        Returns:
            a chunk of compressed data if possible, or an empty byte string otherwise.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def flush(self) -> bytes:
        """
        Finish the compression process.

        The compressor object may not be used after this method has been called.

        Returns:
            the compressed data left in internal buffers.
        """
        raise NotImplementedError


class DecompressorInterface(Protocol, metaclass=abc.ABCMeta):
    """A decompressor object."""

    @abc.abstractmethod
    def decompress(self, data: ReadableBuffer, /) -> bytes:
        """
        Decompress `data` (a :term:`bytes-like object`).

        Some of data may be buffered internally, for use in later calls to :meth:`decompress`.
        The returned data should be concatenated with the output of any previous calls to :meth:`decompress`.

        Returns:
            uncompressed data as bytes.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def eof(self) -> bool:
        """:data:`True` if the end-of-stream marker has been reached."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def unused_data(self) -> bytes:
        """
        Data found after the end of the compressed stream.

        If this attribute is accessed before the end of the stream has been reached, its value will be ``b''``.
        """
        raise NotImplementedError


class AbstractCompressorSerializer(BufferedIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket, memoryview]):
    """
    A :term:`serializer wrapper` base class for compressors.
    """

    __slots__ = ("__serializer", "__expected_error", "__debug")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],
        expected_decompress_error: type[Exception] | tuple[type[Exception], ...],
        *,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            expected_decompress_error: Errors that can be raised by :meth:`DecompressorInterface.decompress` implementation,
                                       which must be considered as deserialization errors.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        super().__init__()
        if not isinstance(serializer, AbstractPacketSerializer):
            raise TypeError(f"Expected a serializer instance, got {serializer!r}")
        if not isinstance(expected_decompress_error, tuple):
            expected_decompress_error = (expected_decompress_error,)
        assert all(issubclass(e, Exception) for e in expected_decompress_error)  # nosec assert_used
        self.__serializer: AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket] = serializer
        self.__expected_error: tuple[type[Exception], ...] = expected_decompress_error

        self.__debug: bool = bool(debug)

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
    def serialize(self, packet: _T_SentDTOPacket) -> bytes:
        """
        Serializes `packet` and returns the compressed data parts.

        See :meth:`.AbstractPacketSerializer.serialize` documentation for details.
        """
        compressor: CompressorInterface = self.new_compressor_stream()
        return compressor.compress(self.__serializer.serialize(packet)) + compressor.flush()

    @final
    def incremental_serialize(self, packet: _T_SentDTOPacket) -> Generator[bytes]:
        """
        Serializes `packet` and yields the compressed data parts.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_serialize` documentation for details.
        """
        compressor: CompressorInterface = self.new_compressor_stream()
        yield compressor.compress(self.__serializer.serialize(packet))
        yield compressor.flush()

    @final
    def deserialize(self, data: bytes) -> _T_ReceivedDTOPacket:
        """
        Decompresses `data` and returns the deserialized packet.

        See :meth:`.AbstractPacketSerializer.deserialize` documentation for details.

        Raises:
            DeserializeError: :meth:`DecompressorInterface.decompress` does not read until EOF (unused trailing data).
            DeserializeError: :meth:`DecompressorInterface.decompress` raised an error that matches `expected_decompress_error`.
            Exception: Any other error raised by :meth:`DecompressorInterface.decompress` or the underlying serializer.
        """
        decompressor: DecompressorInterface = self.new_decompressor_stream()
        try:
            data = decompressor.decompress(data)
        except self.__expected_error as exc:
            msg = str(exc)
            if self.debug:
                raise DeserializeError(msg, error_info={"data": data}) from exc
            raise DeserializeError(msg) from exc
        if not decompressor.eof:
            msg = "Compressed data ended before the end-of-stream marker was reached"
            if self.debug:
                raise DeserializeError(msg, error_info={"already_decompressed_data": data})
            raise DeserializeError(msg)
        if decompressor.unused_data:
            msg = "Trailing data error"
            if self.debug:
                raise DeserializeError(msg, error_info={"decompressed_data": data, "extra": decompressor.unused_data})
            raise DeserializeError(msg)
        del decompressor
        return self.__serializer.deserialize(data)

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
        """
        Yields until data decompression is finished and deserializes the decompressed data using the underlying serializer.

        See :meth:`.AbstractIncrementalPacketSerializer.incremental_deserialize` documentation for details.

        Raises:
            IncrementalDeserializeError: :meth:`DecompressorInterface.decompress` raised an error
                                         that matches `expected_decompress_error`.
            Exception: Any other error raised by :meth:`DecompressorInterface.decompress` or the underlying serializer.
        """
        return (yield from _wrap_generic_incremental_deserialize(self.__generic_incremental_deserialize))

    @final
    def create_deserializer_buffer(self, sizehint: int) -> memoryview:
        """
        See :meth:`.BufferedIncrementalPacketSerializer.create_deserializer_buffer` documentation for details.
        """
        return memoryview(bytearray(sizehint))

    @final
    def buffered_incremental_deserialize(
        self,
        buffer: memoryview,
    ) -> Generator[None, int, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
        """
        Yields until data decompression is finished and deserializes the decompressed data using the underlying serializer.

        See :meth:`.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` documentation for details.

        Raises:
            IncrementalDeserializeError: :meth:`DecompressorInterface.decompress` raised an error
                                         that matches `expected_decompress_error`.
            Exception: Any other error raised by :meth:`DecompressorInterface.decompress` or the underlying serializer.
        """
        return (yield from _wrap_generic_buffered_incremental_deserialize(buffer, self.__generic_incremental_deserialize))

    def __generic_incremental_deserialize(self) -> Generator[None, ReadableBuffer, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
        results: deque[bytes] = deque()
        decompressor: DecompressorInterface = self.new_decompressor_stream()
        while not decompressor.eof:
            chunk: ReadableBuffer = yield
            try:
                chunk = decompressor.decompress(chunk)
            except self.__expected_error as exc:
                msg = f"Decompression error: {exc}"
                if self.debug:
                    raise IncrementalDeserializeError(
                        message=msg,
                        remaining_data=b"",
                        error_info={
                            "already_decompressed_chunks": results,
                            "invalid_chunk": bytes(chunk),
                        },
                    ) from exc
                raise IncrementalDeserializeError(msg, remaining_data=b"") from exc
            if chunk:
                results.append(chunk)
            del chunk

        if len(results) == 1:
            data = results[0]
        else:
            data = b"".join(results)
        unused_data: bytes = decompressor.unused_data
        del results, decompressor

        try:
            packet: _T_ReceivedDTOPacket = self.__serializer.deserialize(data)
        except DeserializeError as exc:
            raise IncrementalDeserializeError(
                f"Error while deserializing decompressed data: {exc}",
                remaining_data=unused_data,
                error_info=exc.error_info,
            ) from exc

        return packet, unused_data

    @property
    @final
    def debug(self) -> bool:
        """
        The debug mode flag. Read-only attribute.
        """
        return self.__debug


class BZ2CompressorSerializer(AbstractCompressorSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]):
    """
    A :term:`serializer wrapper` to handle bzip2 compressed data, built on top of :mod:`bz2` module.
    """

    __slots__ = ("__compresslevel", "__compressor_factory", "__decompressor_factory")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],
        *,
        compress_level: int | None = None,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            compress_level: bzip2 compression level. Defaults to ``9``.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        import bz2

        super().__init__(serializer=serializer, expected_decompress_error=OSError, debug=debug)
        self.__compresslevel: int = compress_level if compress_level is not None else 9
        self.__compressor_factory = bz2.BZ2Compressor
        self.__decompressor_factory = bz2.BZ2Decompressor

    @final
    def new_compressor_stream(self) -> BZ2Compressor:
        """
        See :meth:`.AbstractCompressorSerializer.new_compressor_stream` documentation for details.
        """
        return self.__compressor_factory(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> BZ2Decompressor:
        """
        See :meth:`.AbstractCompressorSerializer.new_decompressor_stream` documentation for details.
        """
        return self.__decompressor_factory()


class ZlibCompressorSerializer(AbstractCompressorSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]):
    """
    A :term:`serializer wrapper` to handle zlib compressed data, built on top of :mod:`zlib` module.
    """

    __slots__ = ("__compresslevel", "__compressor_factory", "__decompressor_factory")

    def __init__(
        self,
        serializer: AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],
        *,
        compress_level: int | None = None,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            serializer: The serializer to wrap.
            compress_level: bzip2 compression level. Defaults to :data:`zlib.Z_BEST_COMPRESSION`.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        import zlib

        super().__init__(serializer=serializer, expected_decompress_error=zlib.error, debug=debug)
        self.__compresslevel: int = compress_level if compress_level is not None else zlib.Z_BEST_COMPRESSION
        self.__compressor_factory = zlib.compressobj
        self.__decompressor_factory = zlib.decompressobj

    @final
    def new_compressor_stream(self) -> ZLibCompress:
        """
        See :meth:`.AbstractCompressorSerializer.new_compressor_stream` documentation for details.
        """
        return self.__compressor_factory(self.__compresslevel)

    @final
    def new_decompressor_stream(self) -> ZLibDecompress:
        """
        See :meth:`.AbstractCompressorSerializer.new_decompressor_stream` documentation for details.
        """
        return self.__decompressor_factory()
