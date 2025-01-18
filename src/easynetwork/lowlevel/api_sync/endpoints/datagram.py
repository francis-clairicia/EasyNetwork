# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Low-level endpoints module for datagram-based communication."""

from __future__ import annotations

__all__ = [
    "DatagramEndpoint",
    "DatagramReceiverEndpoint",
    "DatagramSenderEndpoint",
]

import dataclasses
import math
import warnings
from collections.abc import Callable, Mapping
from typing import Any, Generic

from ...._typevars import _T_ReceivedPacket, _T_SentPacket
from ....exceptions import DatagramProtocolParseError
from ....protocol import DatagramProtocol
from ... import _utils
from ..transports import abc as _transports


class DatagramReceiverEndpoint(_transports.BaseTransport, Generic[_T_ReceivedPacket]):
    """
    A read-only communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__receiver",
    )

    def __init__(
        self,
        transport: _transports.DatagramReadTransport,
        protocol: DatagramProtocol[Any, _T_ReceivedPacket],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.DatagramReadTransport):
            raise TypeError(f"Expected a DatagramReadTransport object, got {transport!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] = _DataReceiverImpl(transport, protocol)

        self.__transport: _transports.DatagramReadTransport = transport

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:
            return
        if not transport.is_closed():
            _warn(f"unclosed endpoint {self!r}", ResourceWarning, source=self)
            transport.close()

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

    def recv_packet(self, *, timeout: float | None = None) -> _T_ReceivedPacket:
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
        receiver = self.__receiver

        if timeout is None:
            timeout = math.inf

        return receiver.receive(timeout)

    @property
    @_utils.inherit_doc(_transports.BaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class DatagramSenderEndpoint(_transports.BaseTransport, Generic[_T_SentPacket]):
    """
    A write-only communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__sender",
    )

    def __init__(
        self,
        transport: _transports.DatagramWriteTransport,
        protocol: DatagramProtocol[_T_SentPacket, Any],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.DatagramWriteTransport):
            raise TypeError(f"Expected a DatagramWriteTransport object, got {transport!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, protocol)

        self.__transport: _transports.DatagramWriteTransport = transport

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:
            return
        if not transport.is_closed():
            _warn(f"unclosed endpoint {self!r}", ResourceWarning, source=self)
            transport.close()

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

    def send_packet(self, packet: _T_SentPacket, *, timeout: float | None = None) -> None:
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
        sender = self.__sender

        if timeout is None:
            timeout = math.inf

        return sender.send(packet, timeout)

    @property
    @_utils.inherit_doc(_transports.BaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class DatagramEndpoint(_transports.BaseTransport, Generic[_T_SentPacket, _T_ReceivedPacket]):
    """
    A full-duplex communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__receiver",
    )

    def __init__(
        self,
        transport: _transports.DatagramTransport,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.DatagramTransport):
            raise TypeError(f"Expected a DatagramTransport object, got {transport!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, protocol)
        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] = _DataReceiverImpl(transport, protocol)

        self.__transport: _transports.DatagramTransport = transport

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:
            return
        if not transport.is_closed():
            _warn(f"unclosed endpoint {self!r}", ResourceWarning, source=self)
            transport.close()

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

    def send_packet(self, packet: _T_SentPacket, *, timeout: float | None = None) -> None:
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
        sender = self.__sender

        if timeout is None:
            timeout = math.inf

        return sender.send(packet, timeout)

    def recv_packet(self, *, timeout: float | None = None) -> _T_ReceivedPacket:
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
        receiver = self.__receiver

        if timeout is None:
            timeout = math.inf

        return receiver.receive(timeout)

    @property
    @_utils.inherit_doc(_transports.BaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


@dataclasses.dataclass(slots=True)
class _DataSenderImpl(Generic[_T_SentPacket]):
    transport: _transports.DatagramWriteTransport
    protocol: DatagramProtocol[_T_SentPacket, Any]

    def send(self, packet: _T_SentPacket, timeout: float) -> None:
        try:
            datagram: bytes = self.protocol.make_datagram(packet)
        except Exception as exc:
            raise RuntimeError("protocol.make_datagram() crashed") from exc
        finally:
            del packet

        self.transport.send(datagram, timeout)


@dataclasses.dataclass(slots=True)
class _DataReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: _transports.DatagramReadTransport
    protocol: DatagramProtocol[Any, _T_ReceivedPacket]

    def receive(self, timeout: float) -> _T_ReceivedPacket:
        datagram = self.transport.recv(timeout)
        try:
            return self.protocol.build_packet_from_datagram(datagram)
        except DatagramProtocolParseError:
            raise
        except Exception as exc:
            raise RuntimeError("protocol.build_packet_from_datagram() crashed") from exc
        finally:
            del datagram
