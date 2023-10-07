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
from typing import Any, Generic

from ...._typevars import _ReceivedPacketT, _SentPacketT
from ....protocol import DatagramProtocol
from ....tools import typed_attr
from ..transports.abc import DatagramTransport


class DatagramEndpoint(Generic[_SentPacketT, _ReceivedPacketT], typed_attr.TypedAttributeProvider):
    """
    A communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__protocol",
        "__weakref__",
    )

    def __init__(self, transport: DatagramTransport, protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT]) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, DatagramTransport):
            raise TypeError(f"Expected a DatagramTransport object, got {transport!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__transport: DatagramTransport = transport
        self.__protocol: DatagramProtocol[_SentPacketT, _ReceivedPacketT] = protocol

    def __del__(self) -> None:  # pragma: no cover
        try:
            transport = self.__transport
        except AttributeError:
            return
        if not transport.is_closed():
            self.close()

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

        return protocol.build_packet_from_datagram(transport.recv(timeout))

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes
