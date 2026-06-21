# Copyright 2021-2026, Francis Clairicia-Rose-Claire-Josephine
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
"""EasyNetwork's packet converters module."""

from __future__ import annotations

__all__ = [
    "AbstractPacketConverter",
    "AbstractPacketConverterComposite",
    "StapledPacketConverter",
]

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, final

from .lowlevel import _utils


class AbstractPacketConverterComposite[SentPacket, ReceivedPacket, SentDTOPacket, ReceivedDTOPacket](
    metaclass=ABCMeta,
):
    """
    The base class for implementing a :term:`composite converter`.

    See Also:
        The :class:`AbstractPacketConverter` class.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def create_from_dto_packet(self, packet: ReceivedDTOPacket, /) -> ReceivedPacket:
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
    def convert_to_dto_packet(self, obj: SentPacket, /) -> SentDTOPacket:
        """
        Creates the :term:`DTO` packet from the business object `obj`.

        Parameters:
            obj: The business object.

        Returns:
            the :term:`data transfer object`.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class StapledPacketConverter[SentPacket, ReceivedPacket, SentDTOPacket, ReceivedDTOPacket](
    AbstractPacketConverterComposite[SentPacket, ReceivedPacket, SentDTOPacket, ReceivedDTOPacket]
):
    """
    A :term:`composite converter` that merges two converters.
    """

    sent_packet_converter: AbstractPacketConverterComposite[SentPacket, Any, SentDTOPacket, Any]
    """Sent packet converter."""

    received_packet_converter: AbstractPacketConverterComposite[Any, ReceivedPacket, Any, ReceivedDTOPacket]
    """Received packet converter."""

    @final
    def create_from_dto_packet(self, packet: ReceivedDTOPacket, /) -> ReceivedPacket:
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
    def convert_to_dto_packet(self, obj: SentPacket, /) -> SentDTOPacket:
        """
        Calls ``self.sent_packet_converter.convert_to_dto_packet(obj)``.

        Parameters:
            obj: The business object.

        Returns:
            the :term:`data transfer object`.
        """
        return self.sent_packet_converter.convert_to_dto_packet(obj)


class AbstractPacketConverter[SentPacket, SentDTOPacket](
    AbstractPacketConverterComposite[SentPacket, SentPacket, SentDTOPacket, SentDTOPacket],
):
    """
    The base class for implementing a :term:`converter`.

    See Also:
        The :class:`AbstractPacketConverterComposite` class.
    """

    __slots__ = ()

    @abstractmethod
    @_utils.inherit_doc(AbstractPacketConverterComposite)
    def create_from_dto_packet(self, packet: SentDTOPacket, /) -> SentPacket:
        raise NotImplementedError

    @abstractmethod
    @_utils.inherit_doc(AbstractPacketConverterComposite)
    def convert_to_dto_packet(self, obj: SentPacket, /) -> SentDTOPacket:
        raise NotImplementedError
