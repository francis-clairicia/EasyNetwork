# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Abstract base network packet serializer module"""

from __future__ import annotations

__all__ = [
    "AbstractIncrementalPacketSerializer",
    "AbstractPacketSerializer",
]

from abc import ABCMeta, abstractmethod
from typing import Any, Generator, Generic, TypeVar

from ..exceptions import DeserializeError
from ..tools._utils import concatenate_chunks as _concatenate_chunks

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class AbstractPacketSerializer(Generic[_ST_contra, _DT_co], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def serialize(self, packet: _ST_contra) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def deserialize(self, data: bytes) -> _DT_co:
        raise NotImplementedError


class AbstractIncrementalPacketSerializer(AbstractPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ()

    @abstractmethod
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        raise NotImplementedError

    @abstractmethod
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        raise NotImplementedError

    def serialize(self, packet: _ST_contra) -> bytes:
        return _concatenate_chunks(self.incremental_serialize(packet))

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
