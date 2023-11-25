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

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any, Generic

from .... import protocol as protocol_module
from ...._typevars import _ReceivedPacketT, _SentPacketT
from ....exceptions import UnsupportedOperation
from ... import _stream, _utils, typed_attr
from ..transports import abc as transports


class AsyncStreamEndpoint(typed_attr.TypedAttributeProvider, Generic[_SentPacketT, _ReceivedPacketT]):
    """
    A communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__receiver",
        "__send_guard",
        "__recv_guard",
        "__eof_sent",
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

        self.__sender: _DataSenderImpl[_SentPacketT] | None = None
        if isinstance(transport, transports.AsyncStreamWriteTransport):
            self.__sender = _DataSenderImpl(transport, _stream.StreamDataProducer(protocol))

        self.__receiver: _DataReceiverImpl[_ReceivedPacketT] | _BufferedReceiverImpl[_ReceivedPacketT] | None = None
        try:
            if not isinstance(transport, transports.AsyncBufferedStreamReadTransport):
                raise UnsupportedOperation
            self.__receiver = _BufferedReceiverImpl(transport, _stream.BufferedStreamDataConsumer(protocol, max_recv_size))
        except UnsupportedOperation:
            if isinstance(transport, transports.AsyncStreamReadTransport):
                self.__receiver = _DataReceiverImpl(transport, _stream.StreamDataConsumer(protocol), max_recv_size)

        self.__transport: transports.AsyncStreamReadTransport | transports.AsyncStreamWriteTransport = transport
        self.__send_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently sending data on this endpoint")
        self.__recv_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receving data on this endpoint")
        self.__eof_sent: bool = False

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
        if self.__receiver is not None:
            self.__receiver.clear()
        if self.__sender is not None:
            self.__sender.clear()

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

            sender = self.__sender

            if sender is None:
                raise UnsupportedOperation("transport does not support sending data")

            return await sender.send(packet)

    async def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed.

        This method does nothing if the endpoint is closed.

        Can be safely called multiple times.
        """
        with self.__send_guard:
            if self.__eof_sent:
                return

            sender = self.__sender

            if sender is None or not isinstance(sender.transport, transports.AsyncStreamTransport):
                raise UnsupportedOperation("transport does not support sending EOF")

            await sender.transport.send_eof()
            self.__eof_sent = True
            sender.clear()

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
            receiver = self.__receiver

            if receiver is None:
                raise UnsupportedOperation("transport does not support receiving data")

            return await receiver.receive()

    @property
    def max_recv_size(self) -> int:
        """Read buffer size. Read-only attribute."""
        receiver = self.__receiver
        if receiver is None:
            return 0
        return receiver.max_recv_size

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


@dataclasses.dataclass(slots=True)
class _DataSenderImpl(Generic[_SentPacketT]):
    transport: transports.AsyncStreamWriteTransport
    producer: _stream.StreamDataProducer[_SentPacketT]

    def clear(self) -> None:
        self.producer.clear()

    async def send(self, packet: _SentPacketT) -> None:
        self.producer.enqueue(packet)
        return await self.transport.send_all_from_iterable(self.producer)


@dataclasses.dataclass(slots=True)
class _DataReceiverImpl(Generic[_ReceivedPacketT]):
    transport: transports.AsyncStreamReadTransport
    consumer: _stream.StreamDataConsumer[_ReceivedPacketT]
    max_recv_size: int
    _eof_reached: bool = dataclasses.field(init=False, default=False)

    def clear(self) -> None:
        self.consumer.clear()

    async def receive(self) -> _ReceivedPacketT:
        transport = self.transport
        consumer = self.consumer
        bufsize: int = self.max_recv_size

        while True:
            try:
                return next(consumer)
            except StopIteration:
                pass
            if not self._eof_reached:
                chunk: bytes = await transport.recv(bufsize)
                if chunk:
                    consumer.feed(chunk)
                else:
                    self._eof_reached = True
                del chunk
            if self._eof_reached:
                raise EOFError("end-of-stream")


@dataclasses.dataclass(slots=True)
class _BufferedReceiverImpl(Generic[_ReceivedPacketT]):
    transport: transports.AsyncBufferedStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_ReceivedPacketT]
    _eof_reached: bool = dataclasses.field(init=False, default=False)

    @property
    def max_recv_size(self) -> int:
        # Ensure buffer is allocated
        self.consumer.get_write_buffer()
        return self.consumer.buffer_size

    def clear(self) -> None:
        self.consumer.clear()

    async def receive(self) -> _ReceivedPacketT:
        transport = self.transport
        consumer = self.consumer

        while True:
            try:
                return next(consumer)
            except StopIteration:
                pass
            if not self._eof_reached:
                nbytes: int = await transport.recv_into(consumer.get_write_buffer())
                if nbytes:
                    consumer.buffer_updated(nbytes)
                else:
                    self._eof_reached = True
            if self._eof_reached:
                raise EOFError("end-of-stream")
