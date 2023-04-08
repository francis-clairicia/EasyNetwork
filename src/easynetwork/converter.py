# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network packet converter module"""

from __future__ import annotations

__all__ = ["AbstractPacketConverter"]

from abc import ABCMeta, abstractmethod
from typing import Callable, Generic, TypeVar, final

_SentDTOPacketT = TypeVar("_SentDTOPacketT")
_ReceivedDTOPacketT = TypeVar("_ReceivedDTOPacketT")

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


class AbstractPacketConverter(Generic[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def create_from_dto_packet(self, packet: _ReceivedDTOPacketT) -> _ReceivedPacketT:
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _SentPacketT) -> _SentDTOPacketT:
        raise NotImplementedError


class PacketConverterComposite(AbstractPacketConverter[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT]):
    __slots__ = ("__create_from_dto", "__convert_to_dto")

    def __init__(
        self,
        create_from_dto: Callable[[_ReceivedDTOPacketT], _ReceivedPacketT],
        convert_to_dto: Callable[[_SentPacketT], _SentDTOPacketT],
    ) -> None:
        super().__init__()
        self.__create_from_dto: Callable[[_ReceivedDTOPacketT], _ReceivedPacketT] = create_from_dto
        self.__convert_to_dto: Callable[[_SentPacketT], _SentDTOPacketT] = convert_to_dto

    @final
    def create_from_dto_packet(self, packet: _ReceivedDTOPacketT) -> _ReceivedPacketT:
        return self.__create_from_dto(packet)

    @final
    def convert_to_dto_packet(self, obj: _SentPacketT) -> _SentDTOPacketT:
        return self.__convert_to_dto(obj)
