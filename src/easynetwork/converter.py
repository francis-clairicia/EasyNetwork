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
"""Network packet converter module"""

from __future__ import annotations

__all__ = [
    "AbstractPacketConverter",
    "AbstractPacketConverterComposite",
    "PacketConverterComposite",
    "RequestResponseConverterBuilder",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from typing import Any, Generic, TypeVar, final

_SentDTOPacketT = TypeVar("_SentDTOPacketT")
_ReceivedDTOPacketT = TypeVar("_ReceivedDTOPacketT")
_DTOPacketT = TypeVar("_DTOPacketT")

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_PacketT = TypeVar("_PacketT")


class AbstractPacketConverterComposite(
    Generic[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT], metaclass=ABCMeta
):
    __slots__ = ("__weakref__",)

    @abstractmethod
    def create_from_dto_packet(self, packet: _ReceivedDTOPacketT, /) -> _ReceivedPacketT:
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _SentPacketT, /) -> _SentDTOPacketT:
        raise NotImplementedError


class PacketConverterComposite(
    AbstractPacketConverterComposite[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT]
):
    __slots__ = ("__create_from_dto", "__convert_to_dto")

    def __init__(
        self,
        convert_to_dto: Callable[[_SentPacketT], _SentDTOPacketT],
        create_from_dto: Callable[[_ReceivedDTOPacketT], _ReceivedPacketT],
    ) -> None:
        super().__init__()
        self.__create_from_dto: Callable[[_ReceivedDTOPacketT], _ReceivedPacketT] = create_from_dto
        self.__convert_to_dto: Callable[[_SentPacketT], _SentDTOPacketT] = convert_to_dto

    @final
    def create_from_dto_packet(self, packet: _ReceivedDTOPacketT, /) -> _ReceivedPacketT:
        return self.__create_from_dto(packet)

    @final
    def convert_to_dto_packet(self, obj: _SentPacketT, /) -> _SentDTOPacketT:
        return self.__convert_to_dto(obj)


class AbstractPacketConverter(
    AbstractPacketConverterComposite[_PacketT, _DTOPacketT, _PacketT, _DTOPacketT], Generic[_PacketT, _DTOPacketT]
):
    __slots__ = ()

    @abstractmethod
    def create_from_dto_packet(self, packet: _DTOPacketT, /) -> _PacketT:
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _PacketT, /) -> _DTOPacketT:
        raise NotImplementedError


@final
class RequestResponseConverterBuilder:
    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("RequestResponseConverterBuilder cannot be subclassed")

    @staticmethod
    def build_for_client(
        request_converter: AbstractPacketConverterComposite[_SentPacketT, _SentDTOPacketT, Any, Any],
        response_converter: AbstractPacketConverterComposite[Any, Any, _ReceivedPacketT, _ReceivedDTOPacketT],
    ) -> AbstractPacketConverterComposite[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT]:
        return PacketConverterComposite(
            create_from_dto=response_converter.create_from_dto_packet,
            convert_to_dto=request_converter.convert_to_dto_packet,
        )

    @staticmethod
    def build_for_server(
        request_converter: AbstractPacketConverterComposite[Any, Any, _ReceivedPacketT, _ReceivedDTOPacketT],
        response_converter: AbstractPacketConverterComposite[_SentPacketT, _SentDTOPacketT, Any, Any],
    ) -> AbstractPacketConverterComposite[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT]:
        return PacketConverterComposite(
            create_from_dto=request_converter.create_from_dto_packet,
            convert_to_dto=response_converter.convert_to_dto_packet,
        )
