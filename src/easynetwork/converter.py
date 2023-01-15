# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network packet converter module"""

from __future__ import annotations

__all__ = ["AbstractPacketConverter", "PacketConversionError"]

from abc import ABCMeta, abstractmethod
from typing import Generic, TypeVar

_SentDTOPacketT = TypeVar("_SentDTOPacketT")
_ReceivedDTOPacketT = TypeVar("_ReceivedDTOPacketT")

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


class PacketConversionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class AbstractPacketConverter(Generic[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def create_from_dto_packet(self, packet: _ReceivedDTOPacketT) -> _ReceivedPacketT:
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _SentPacketT) -> _SentDTOPacketT:
        raise NotImplementedError
