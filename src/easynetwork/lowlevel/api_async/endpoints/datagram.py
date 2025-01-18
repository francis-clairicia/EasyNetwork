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
"""Low-level asynchronous endpoints module for datagram-based communication."""

from __future__ import annotations

__all__ = [
    "AsyncDatagramEndpoint",
    "AsyncDatagramReceiverEndpoint",
    "AsyncDatagramSenderEndpoint",
]

import dataclasses
import warnings
from collections.abc import Callable, Mapping
from typing import Any, Generic

from ...._typevars import _T_ReceivedPacket, _T_SentPacket
from ....exceptions import DatagramProtocolParseError
from ....protocol import DatagramProtocol
from ... import _utils
from ..backend.abc import AsyncBackend
from ..transports import abc as _transports


class AsyncDatagramReceiverEndpoint(_transports.AsyncBaseTransport, Generic[_T_ReceivedPacket]):
    """
    A read-only communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__receiver",
        "__recv_guard",
    )

    def __init__(
        self,
        transport: _transports.AsyncDatagramReadTransport,
        protocol: DatagramProtocol[Any, _T_ReceivedPacket],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.AsyncDatagramReadTransport):
            raise TypeError(f"Expected an AsyncDatagramReadTransport object, got {transport!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] = _DataReceiverImpl(transport, protocol)

        self.__transport: _transports.AsyncDatagramReadTransport = transport
        self.__recv_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receving data on this endpoint")

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:
            return
        if not transport.is_closing():
            msg = f"unclosed endpoint {self!r} pointing to {transport!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

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

    async def recv_packet(self) -> _T_ReceivedPacket:
        """
        Waits for a new packet from the remote endpoint.

        Raises:
            DatagramProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        with self.__recv_guard:
            receiver = self.__receiver

            return await receiver.receive()

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__transport.backend()

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class AsyncDatagramSenderEndpoint(_transports.AsyncBaseTransport, Generic[_T_SentPacket]):
    """
    A write-only communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__send_guard",
    )

    def __init__(
        self,
        transport: _transports.AsyncDatagramWriteTransport,
        protocol: DatagramProtocol[_T_SentPacket, Any],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.AsyncDatagramWriteTransport):
            raise TypeError(f"Expected an AsyncDatagramWriteTransport object, got {transport!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, protocol)

        self.__transport: _transports.AsyncDatagramWriteTransport = transport
        self.__send_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently sending data on this endpoint")

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:
            return
        if not transport.is_closing():
            msg = f"unclosed endpoint {self!r} pointing to {transport!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

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

    async def send_packet(self, packet: _T_SentPacket) -> None:
        """
        Sends `packet` to the remote endpoint.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
        """
        with self.__send_guard:
            sender = self.__sender

            await sender.send(packet)

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__transport.backend()

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class AsyncDatagramEndpoint(_transports.AsyncBaseTransport, Generic[_T_SentPacket, _T_ReceivedPacket]):
    """
    A full-duplex communication endpoint based on unreliable packets of data.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__receiver",
        "__send_guard",
        "__recv_guard",
    )

    def __init__(
        self,
        transport: _transports.AsyncDatagramTransport,
        protocol: DatagramProtocol[_T_SentPacket, _T_ReceivedPacket],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.AsyncDatagramTransport):
            raise TypeError(f"Expected an AsyncDatagramTransport object, got {transport!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, protocol)
        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] = _DataReceiverImpl(transport, protocol)

        self.__transport: _transports.AsyncDatagramTransport = transport
        self.__send_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently sending data on this endpoint")
        self.__recv_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receving data on this endpoint")

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self.__transport
        except AttributeError:
            return
        if not transport.is_closing():
            msg = f"unclosed endpoint {self!r} pointing to {transport!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

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

    async def send_packet(self, packet: _T_SentPacket) -> None:
        """
        Sends `packet` to the remote endpoint.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
        """
        with self.__send_guard:
            sender = self.__sender

            await sender.send(packet)

    async def recv_packet(self) -> _T_ReceivedPacket:
        """
        Waits for a new packet from the remote endpoint.

        Raises:
            DatagramProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        with self.__recv_guard:
            receiver = self.__receiver

            return await receiver.receive()

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__transport.backend()

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


@dataclasses.dataclass(slots=True)
class _DataSenderImpl(Generic[_T_SentPacket]):
    transport: _transports.AsyncDatagramWriteTransport
    protocol: DatagramProtocol[_T_SentPacket, Any]

    async def send(self, packet: _T_SentPacket) -> None:
        try:
            datagram: bytes = self.protocol.make_datagram(packet)
        except Exception as exc:
            raise RuntimeError("protocol.make_datagram() crashed") from exc
        finally:
            del packet

        await self.transport.send(datagram)


@dataclasses.dataclass(slots=True)
class _DataReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: _transports.AsyncDatagramReadTransport
    protocol: DatagramProtocol[Any, _T_ReceivedPacket]

    async def receive(self) -> _T_ReceivedPacket:
        datagram = await self.transport.recv()
        try:
            return self.protocol.build_packet_from_datagram(datagram)
        except DatagramProtocolParseError:
            raise
        except Exception as exc:
            raise RuntimeError("protocol.build_packet_from_datagram() crashed") from exc
        finally:
            del datagram
