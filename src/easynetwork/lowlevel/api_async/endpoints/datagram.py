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
"""Low-level asynchronous endpoints module"""

from __future__ import annotations

__all__ = ["AsyncDatagramEndpoint"]

from collections.abc import Callable, Mapping
from typing import Any, Generic, TypeGuard

from .... import protocol as protocol_module
from ...._typevars import _ReceivedPacketT, _SentPacketT
from ... import typed_attr
from ..transports import abc as transports


class AsyncDatagramEndpoint(Generic[_SentPacketT, _ReceivedPacketT], typed_attr.TypedAttributeProvider):
    """
    A communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__is_read_transport",
        "__is_write_transport",
        "__protocol",
        "__weakref__",
    )

    def __init__(
        self,
        transport: transports.AsyncDatagramTransport
        | transports.AsyncDatagramReadTransport
        | transports.AsyncDatagramWriteTransport,
        protocol: protocol_module.DatagramProtocol[_SentPacketT, _ReceivedPacketT],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, (transports.AsyncDatagramReadTransport, transports.AsyncDatagramWriteTransport)):
            raise TypeError(f"Expected an AsyncDatagramTransport object, got {transport!r}")
        if not isinstance(protocol, protocol_module.DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__is_read_transport: bool = isinstance(transport, transports.AsyncDatagramReadTransport)
        self.__is_write_transport: bool = isinstance(transport, transports.AsyncDatagramWriteTransport)
        self.__transport: transports.AsyncDatagramReadTransport | transports.AsyncDatagramWriteTransport = transport
        self.__protocol: protocol_module.DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol

    def is_closing(self) -> bool:
        """
        Checks if the endpoint is closed or in the process of being closed.

        Returns:
            :data:`True` if the endpoint is closed.
        """
        return self.__transport.is_closing()

    async def aclose(self) -> None:
        """
        Closes the endpoint.
        """
        await self.__transport.aclose()

    async def send_packet(self, packet: _SentPacketT) -> None:
        """
        Sends `packet` to the remote endpoint.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
        """
        transport = self.__transport
        protocol = self.__protocol

        if not self.__supports_write(transport):
            raise NotImplementedError("transport does not support sending data")

        await transport.send(protocol.make_datagram(packet))

    async def recv_packet(self) -> _ReceivedPacketT:
        """
        Waits for a new packet from the remote endpoint.

        Raises:
            DatagramProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        transport = self.__transport
        protocol = self.__protocol

        if not self.__supports_read(transport):
            raise NotImplementedError("transport does not support receiving data")

        return protocol.build_packet_from_datagram(await transport.recv())

    def __supports_read(self, transport: transports.AsyncBaseTransport) -> TypeGuard[transports.AsyncDatagramReadTransport]:
        return self.__is_read_transport

    def __supports_write(self, transport: transports.AsyncBaseTransport) -> TypeGuard[transports.AsyncDatagramWriteTransport]:
        return self.__is_write_transport

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes
