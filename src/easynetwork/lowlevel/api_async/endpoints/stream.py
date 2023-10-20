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

__all__ = ["AsyncStreamEndpoint"]

from collections.abc import Callable, Mapping
from typing import Any, Generic, TypeGuard

from .... import protocol as protocol_module
from ...._typevars import _ReceivedPacketT, _SentPacketT
from ... import _stream, _utils, typed_attr
from ..transports import abc as transports


class AsyncStreamEndpoint(Generic[_SentPacketT, _ReceivedPacketT], typed_attr.TypedAttributeProvider):
    """
    A communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__is_read_transport",
        "__is_write_transport",
        "__is_bidirectional_transport",
        "__producer",
        "__consumer",
        "__send_guard",
        "__recv_guard",
        "__max_recv_size",
        "__eof_sent",
        "__eof_reached",
        "__weakref__",
    )

    def __init__(
        self,
        transport: transports.AsyncStreamTransport | transports.AsyncStreamReadTransport | transports.AsyncStreamWriteTransport,
        protocol: protocol_module.StreamProtocol[_SentPacketT, _ReceivedPacketT],
        max_recv_size: int,
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """

        if not isinstance(transport, (transports.AsyncStreamReadTransport, transports.AsyncStreamWriteTransport)):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__producer: _stream.StreamDataProducer[_SentPacketT] = _stream.StreamDataProducer(protocol)
        self.__consumer: _stream.StreamDataConsumer[_ReceivedPacketT] = _stream.StreamDataConsumer(protocol)
        self.__is_read_transport: bool = isinstance(transport, transports.AsyncStreamReadTransport)
        self.__is_write_transport: bool = isinstance(transport, transports.AsyncStreamWriteTransport)
        self.__is_bidirectional_transport: bool = isinstance(transport, transports.AsyncStreamTransport)
        self.__transport: transports.AsyncStreamReadTransport | transports.AsyncStreamWriteTransport = transport
        self.__send_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently sending data on this endpoint")
        self.__recv_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receving data on this endpoint")
        self.__max_recv_size: int = max_recv_size
        self.__eof_sent: bool = False
        self.__eof_reached: bool = False

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
        self.__consumer.clear()
        self.__producer.clear()

    async def send_packet(self, packet: _SentPacketT) -> None:
        """
        Sends `packet` to the remote endpoint.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.

        Raises:
            RuntimeError: :meth:`send_eof` has been called earlier.
        """
        with self.__send_guard:
            if self.__eof_sent:
                raise RuntimeError("send_eof() has been called earlier")

            transport = self.__transport
            producer = self.__producer

            if not self.__supports_write(transport):
                raise NotImplementedError("transport does not support sending data")

            producer.enqueue(packet)
            await transport.send_all_from_iterable(producer)

    async def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed.

        This method does nothing if the endpoint is closed.

        Can be safely called multiple times.
        """
        with self.__send_guard:
            if self.__eof_sent:
                return

            transport = self.__transport
            producer = self.__producer

            if not self.__supports_sending_eof(transport):
                raise NotImplementedError("transport does not support sending EOF")

            await transport.send_eof()
            self.__eof_sent = True
            producer.clear()

    async def recv_packet(self) -> _ReceivedPacketT:
        """
        Waits for a new packet to arrive from the remote endpoint.

        Raises:
            EOFError: the read end of the stream is closed.
            StreamProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        with self.__recv_guard:
            transport = self.__transport
            consumer = self.__consumer

            if not self.__supports_read(transport):
                raise NotImplementedError("transport does not support receiving data")

            try:
                return next(consumer)  # If there is enough data from last call to create a packet, return immediately
            except StopIteration:
                pass

            if self.__eof_reached:
                raise EOFError("end-of-stream")

            bufsize: int = self.__max_recv_size

            while True:
                chunk: bytes = await transport.recv(bufsize)
                if not chunk:
                    self.__eof_reached = True
                    raise EOFError("end-of-stream")
                try:
                    consumer.feed(chunk)
                finally:
                    del chunk
                try:
                    return next(consumer)
                except StopIteration:
                    pass

    def __supports_read(self, transport: transports.AsyncBaseTransport) -> TypeGuard[transports.AsyncStreamReadTransport]:
        return self.__is_read_transport

    def __supports_write(self, transport: transports.AsyncBaseTransport) -> TypeGuard[transports.AsyncStreamWriteTransport]:
        return self.__is_write_transport

    def __supports_sending_eof(self, transport: transports.AsyncBaseTransport) -> TypeGuard[transports.AsyncStreamTransport]:
        return self.__is_bidirectional_transport

    @property
    def max_recv_size(self) -> int:
        """Read buffer size. Read-only attribute."""
        return self.__max_recv_size

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes
