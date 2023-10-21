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
"""Low-level endpoints module"""

from __future__ import annotations

__all__ = ["DatagramEndpoint"]

import math
from collections.abc import Callable, Mapping
from typing import Any, Generic, TypeGuard

from .... import protocol as protocol_module
from ...._typevars import _ReceivedPacketT, _SentPacketT
from ... import typed_attr
from ..transports import abc as transports


class DatagramEndpoint(typed_attr.TypedAttributeProvider, Generic[_SentPacketT, _ReceivedPacketT]):
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
        transport: transports.DatagramTransport | transports.DatagramReadTransport | transports.DatagramWriteTransport,
        protocol: protocol_module.DatagramProtocol[_SentPacketT, _ReceivedPacketT],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, (transports.DatagramReadTransport, transports.DatagramWriteTransport)):
            raise TypeError(f"Expected a DatagramTransport object, got {transport!r}")
        if not isinstance(protocol, protocol_module.DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__is_read_transport: bool = isinstance(transport, transports.DatagramReadTransport)
        self.__is_write_transport: bool = isinstance(transport, transports.DatagramWriteTransport)
        self.__transport: transports.DatagramReadTransport | transports.DatagramWriteTransport = transport
        self.__protocol: protocol_module.DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol

    def __del__(self) -> None:  # pragma: no cover
        try:
            if not self.__transport.is_closed():
                self.close()
        except AttributeError:
            return

    def is_closed(self) -> bool:
        """
        Checks if :meth:`close` has been called.

        Returns:
            :data:`True` if the endpoint is closed.
        """
        return self.__transport.is_closed()

    def close(self) -> None:
        """
        Closes the endpoint.
        """
        self.__transport.close()

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = None) -> None:
        """
        Sends `packet` to the remote endpoint.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Warning:
            A timeout on a send operation is unusual.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the send operation does not end up after `timeout` seconds.
        """
        if timeout is None:
            timeout = math.inf

        transport = self.__transport
        protocol = self.__protocol

        if not self.__supports_write(transport):
            raise NotImplementedError("transport does not support sending data")

        transport.send(protocol.make_datagram(packet), timeout)

    def recv_packet(self, *, timeout: float | None = None) -> _ReceivedPacketT:
        """
        Waits for a new packet from the remote endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            DatagramProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        if timeout is None:
            timeout = math.inf

        transport = self.__transport
        protocol = self.__protocol

        if not self.__supports_read(transport):
            raise NotImplementedError("transport does not support receiving data")

        return protocol.build_packet_from_datagram(transport.recv(timeout))

    def __supports_read(self, transport: transports.BaseTransport) -> TypeGuard[transports.DatagramReadTransport]:
        return self.__is_read_transport

    def __supports_write(self, transport: transports.BaseTransport) -> TypeGuard[transports.DatagramWriteTransport]:
        return self.__is_write_transport

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes
