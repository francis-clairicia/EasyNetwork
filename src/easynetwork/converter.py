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
"""EasyNetwork's packet converters module"""

from __future__ import annotations

__all__ = [
    "AbstractPacketConverter",
    "AbstractPacketConverterComposite",
    "StapledPacketConverter",
]

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, final

from ._typevars import _DTOPacketT, _PacketT, _ReceivedPacketT, _SentPacketT


class AbstractPacketConverterComposite(Generic[_SentPacketT, _ReceivedPacketT, _DTOPacketT], metaclass=ABCMeta):
    """
    The base class for implementing a :term:`composite converter`.

    See Also:
        The :class:`AbstractPacketConverter` class.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def create_from_dto_packet(self, packet: _DTOPacketT, /) -> _ReceivedPacketT:
        """
        Constructs the business object from the :term:`DTO` `packet`.

        Parameters:
            packet: The :term:`data transfer object`.

        Raises:
            PacketConversionError: `packet` is invalid.

        Returns:
            the business object.
        """
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _SentPacketT, /) -> _DTOPacketT:
        """
        Creates the :term:`DTO` packet from the business object `obj`.

        Parameters:
            obj: The business object.

        Returns:
            the :term:`data transfer object`.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class StapledPacketConverter(AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, _DTOPacketT]):
    """
    A :term:`composite converter` that merges two converters.
    """

    sent_packet_converter: AbstractPacketConverterComposite[_SentPacketT, Any, _DTOPacketT]
    """Sent packet converter."""

    received_packet_converter: AbstractPacketConverterComposite[Any, _ReceivedPacketT, _DTOPacketT]
    """Received packet converter."""

    @final
    def create_from_dto_packet(self, packet: _DTOPacketT, /) -> _ReceivedPacketT:
        """
        Calls ``self.received_packet_converter.create_from_dto_packet(packet)``.

        Parameters:
            packet: The :term:`data transfer object`.

        Raises:
            PacketConversionError: `packet` is invalid.

        Returns:
            the business object.
        """
        return self.received_packet_converter.create_from_dto_packet(packet)

    @final
    def convert_to_dto_packet(self, obj: _SentPacketT, /) -> _DTOPacketT:
        """
        Calls ``self.sent_packet_converter.convert_to_dto_packet(obj)``.

        Parameters:
            obj: The business object.

        Returns:
            the :term:`data transfer object`.
        """
        return self.sent_packet_converter.convert_to_dto_packet(obj)


class AbstractPacketConverter(AbstractPacketConverterComposite[_PacketT, _PacketT, _DTOPacketT], Generic[_PacketT, _DTOPacketT]):
    """
    The base class for implementing a :term:`converter`.

    See Also:
        The :class:`AbstractPacketConverterComposite` class.
    """

    __slots__ = ()

    @abstractmethod
    def create_from_dto_packet(self, packet: _DTOPacketT, /) -> _PacketT:
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _PacketT, /) -> _DTOPacketT:
        raise NotImplementedError

    create_from_dto_packet.__doc__ = AbstractPacketConverterComposite.create_from_dto_packet.__doc__
    convert_to_dto_packet.__doc__ = AbstractPacketConverterComposite.convert_to_dto_packet.__doc__
