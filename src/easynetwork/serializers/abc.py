# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Abstract base network packet serializer module"""

from __future__ import annotations

__all__ = ["PacketSerializer"]

from abc import ABCMeta, abstractmethod
from typing import Generic, TypeVar

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


class PacketSerializer(Generic[_ST_contra, _DT_co], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def serialize(self, packet: _ST_contra) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def deserialize(self, data: bytes) -> _DT_co:
        raise NotImplementedError
