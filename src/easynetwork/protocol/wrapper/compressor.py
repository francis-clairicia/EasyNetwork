# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Data compressor protocol module"""

from __future__ import annotations

__all__ = [
    "BZ2CompressorNetworkProtocol",
    "ZlibCompressorNetworkProtocol",
]

import abc
import bz2
import zlib
from collections import deque
from typing import Generator, Protocol, TypeVar, final

from ..abc import NetworkProtocol
from ..exceptions import DeserializeError
from ..stream.abc import StreamNetworkProtocol
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


class AbstractCompressorNetworkProtocol(StreamNetworkProtocol[_ST_contra, _DT_co]):
    __slots__ = ("__protocol", "__trailing_error")

    def __init__(
        self,
        protocol: NetworkProtocol[_ST_contra, _DT_co],
        trailing_error: type[Exception] | tuple[type[Exception], ...],
    ) -> None:
        assert isinstance(protocol, NetworkProtocol)
        super().__init__()
        self.__protocol: NetworkProtocol[_ST_contra, _DT_co] = protocol
        self.__trailing_error: type[Exception] | tuple[type[Exception], ...] = trailing_error

    @abc.abstractmethod
    def get_compressor(self) -> Compressor:
        raise NotImplementedError

    @abc.abstractmethod
    def get_decompressor(self) -> Decompressor:
        raise NotImplementedError

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        compressor = self.get_compressor()
        return compressor.compress(self.__protocol.serialize(packet)) + compressor.flush()

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        protocol = self.__protocol
        compressor = self.get_compressor()
        if isinstance(protocol, StreamNetworkProtocol):
            yield from filter(bool, map(compressor.compress, protocol.incremental_serialize(packet)))
        elif data := compressor.compress(protocol.serialize(packet)):
            yield data
        yield compressor.flush()

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        if not data:
            raise DeserializeError("Empty bytes")
        decompressor = self.get_decompressor()
        try:
            data = decompressor.decompress(data)
        except self.__trailing_error as exc:
            raise DeserializeError("Trailing data error") from exc
        if not decompressor.eof:
            raise DeserializeError("Compressed data ended before the end-of-stream marker was reached")
        if decompressor.unused_data:
            raise DeserializeError("Trailing data error")
        return self.__protocol.deserialize(data)

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        protocol = self.__protocol

        if isinstance(protocol, StreamNetworkProtocol):
            _last_chunk: bytes | None = None

            _consumer = protocol.incremental_deserialize()
            next(_consumer)

            def add_chunk(chunk: bytes) -> None:
                nonlocal _last_chunk

                if _last_chunk is not None:
                    try:
                        _consumer.send(_last_chunk)
                    except DeserializeError as exc:
                        raise IncrementalDeserializeError(
                            f"Error while deserializing decompressed chunk: {exc}",
                            remaining_data=b"",
                        ) from exc
                    except StopIteration as exc:
                        raise IncrementalDeserializeError(
                            "Unexpected StopIteration",
                            remaining_data=b"",
                        ) from exc
                _last_chunk = chunk

            def finish(unused_data: bytes) -> tuple[_DT_co, bytes]:
                packet: _DT_co
                remaining: bytes
                try:
                    if _last_chunk is not None:
                        _consumer.send(_last_chunk)
                except DeserializeError as exc:
                    raise IncrementalDeserializeError(
                        f"Error while deserializing decompressed chunk: {exc}",
                        remaining_data=unused_data,
                    ) from exc
                except StopIteration as exc:
                    packet, remaining = exc.value
                    del exc
                else:
                    raise IncrementalDeserializeError(
                        "Missing data to create packet from compressed data stream",
                        remaining_data=unused_data,
                    )
                if remaining:
                    raise IncrementalDeserializeError(
                        "Extra data caught",
                        remaining_data=unused_data,
                    )
                return packet, unused_data

        else:
            _results: deque[bytes] = deque()

            def add_chunk(chunk: bytes) -> None:
                _results.append(chunk)

            def finish(unused_data: bytes) -> tuple[_DT_co, bytes]:
                data: bytes = b"".join(_results)
                try:
                    packet = protocol.deserialize(data)
                except DeserializeError as exc:
                    raise IncrementalDeserializeError(
                        f"Error while deserializing decompressed data: {exc}",
                        remaining_data=unused_data,
                    ) from exc
                return packet, unused_data

        decompressor = self.get_decompressor()
        while not decompressor.eof:
            while not (chunk := (yield)):
                continue
            try:
                chunk = decompressor.decompress(chunk)
            except self.__trailing_error as exc:
                raise IncrementalDeserializeError(
                    message=f"Decompression error: {exc}",
                    remaining_data=chunk[1:],
                ) from exc
            if chunk:
                add_chunk(chunk)
        return finish(decompressor.unused_data)


class BZ2CompressorNetworkProtocol(AbstractCompressorNetworkProtocol[_ST_contra, _DT_co]):
    __slots__ = ("__compresslevel",)

    def __init__(self, protocol: NetworkProtocol[_ST_contra, _DT_co], *, compresslevel: int = 9) -> None:
        super().__init__(protocol=protocol, trailing_error=OSError)
        self.__compresslevel: int = int(compresslevel)

    @final
    def get_compressor(self) -> bz2.BZ2Compressor:
        return bz2.BZ2Compressor(self.__compresslevel)

    @final
    def get_decompressor(self) -> bz2.BZ2Decompressor:
        return bz2.BZ2Decompressor()


class ZlibCompressorNetworkProtocol(AbstractCompressorNetworkProtocol[_ST_contra, _DT_co]):
    __slots__ = ("__compresslevel",)

    def __init__(self, protocol: NetworkProtocol[_ST_contra, _DT_co], *, compresslevel: int = zlib.Z_BEST_COMPRESSION) -> None:
        assert isinstance(protocol, NetworkProtocol)
        super().__init__(protocol=protocol, trailing_error=zlib.error)
        self.__compresslevel: int = int(compresslevel)

    @final
    def get_compressor(self) -> zlib._Compress:
        return zlib.compressobj(self.__compresslevel)

    @final
    def get_decompressor(self) -> zlib._Decompress:
        return zlib.decompressobj()
