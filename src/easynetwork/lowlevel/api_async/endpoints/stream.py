# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
import warnings
from collections.abc import Callable, Mapping
from typing import Any, Generic, Literal, assert_never

from .... import protocol as protocol_module
from ...._typevars import _T_ReceivedPacket, _T_SentPacket
from ....exceptions import UnsupportedOperation
from ....warnings import ManualBufferAllocationWarning
from ... import _stream, _utils, typed_attr
from ..transports import abc as transports


class AsyncStreamEndpoint(typed_attr.TypedAttributeProvider, Generic[_T_SentPacket, _T_ReceivedPacket]):
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
        protocol: protocol_module.StreamProtocol[_T_SentPacket, _T_ReceivedPacket],
        max_recv_size: int,
        *,
        manual_buffer_allocation: Literal["try", "no", "force"] = "try",
        manual_buffer_allocation_warning_stacklevel: int = 2,
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
            manual_buffer_allocation: Select whether or not to enable the manual buffer allocation system:

                                      * ``"try"``: (the default) will use the buffer API if the transport and protocol support it,
                                        and fall back to the default implementation otherwise.
                                        Emits a :exc:`.ManualBufferAllocationWarning` if only the transport does not support it.

                                      * ``"no"``: does not use the buffer API, even if they both support it.

                                      * ``"force"``: requires the buffer API. Raises :exc:`.UnsupportedOperation` if it fails and
                                        no warnings are emitted.
            manual_buffer_allocation_warning_stacklevel: ``stacklevel`` parameter of :func:`warnings.warn` when emitting
                                                         :exc:`.ManualBufferAllocationWarning`.
        """

        if not isinstance(transport, (transports.AsyncStreamReadTransport, transports.AsyncStreamWriteTransport)):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")
        if manual_buffer_allocation not in ("try", "no", "force"):
            raise ValueError('"manual_buffer_allocation" must be "try", "no" or "force"')
        manual_buffer_allocation_warning_stacklevel = max(manual_buffer_allocation_warning_stacklevel, 2)

        self.__transport: transports.AsyncStreamReadTransport | transports.AsyncStreamWriteTransport = transport
        self.__send_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently sending data on this endpoint")
        self.__recv_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receving data on this endpoint")
        self.__eof_sent: bool = False

        self.__sender: _DataSenderImpl[_T_SentPacket] | None = None
        if isinstance(transport, transports.AsyncStreamWriteTransport):
            self.__sender = _DataSenderImpl(transport, _stream.StreamDataProducer(protocol))

        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] | _BufferedReceiverImpl[_T_ReceivedPacket] | None = None
        if isinstance(transport, transports.AsyncStreamReadTransport):
            match manual_buffer_allocation:
                case "try" | "force":
                    try:
                        buffered_consumer = _stream.BufferedStreamDataConsumer(protocol, max_recv_size)
                        if not isinstance(transport, transports.AsyncBufferedStreamReadTransport):
                            msg = f"The transport implementation {transport!r} does not implement AsyncBufferedStreamReadTransport interface"
                            if manual_buffer_allocation == "try":
                                warnings.warn(
                                    msg,
                                    category=ManualBufferAllocationWarning,
                                    stacklevel=manual_buffer_allocation_warning_stacklevel,
                                )
                            raise UnsupportedOperation(msg)
                        self.__receiver = _BufferedReceiverImpl(transport, buffered_consumer)
                    except UnsupportedOperation:
                        if manual_buffer_allocation == "force":
                            raise
                        self.__receiver = _DataReceiverImpl(transport, _stream.StreamDataConsumer(protocol), max_recv_size)
                case "no":
                    self.__receiver = _DataReceiverImpl(transport, _stream.StreamDataConsumer(protocol), max_recv_size)
                case _:  # pragma: no cover
                    assert_never(manual_buffer_allocation)

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

    async def send_packet(self, packet: _T_SentPacket) -> None:
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

    async def recv_packet(self) -> _T_ReceivedPacket:
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
class _DataSenderImpl(Generic[_T_SentPacket]):
    transport: transports.AsyncStreamWriteTransport
    producer: _stream.StreamDataProducer[_T_SentPacket]

    def clear(self) -> None:
        pass

    async def send(self, packet: _T_SentPacket) -> None:
        return await self.transport.send_all_from_iterable(self.producer.generate(packet))


@dataclasses.dataclass(slots=True)
class _DataReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: transports.AsyncStreamReadTransport
    consumer: _stream.StreamDataConsumer[_T_ReceivedPacket]
    max_recv_size: int
    _eof_reached: bool = dataclasses.field(init=False, default=False)

    def clear(self) -> None:
        self.consumer.clear()

    async def receive(self) -> _T_ReceivedPacket:
        consumer = self.consumer
        try:
            return consumer.next(None)
        except StopIteration:
            pass

        transport = self.transport
        bufsize: int = self.max_recv_size

        while not self._eof_reached:
            chunk: bytes = await transport.recv(bufsize)
            if not chunk:
                self._eof_reached = True
                continue
            try:
                return consumer.next(chunk)
            except StopIteration:
                pass
            finally:
                del chunk

        raise EOFError("end-of-stream")


@dataclasses.dataclass(slots=True)
class _BufferedReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: transports.AsyncBufferedStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_ReceivedPacket]
    _eof_reached: bool = dataclasses.field(init=False, default=False)

    @property
    def max_recv_size(self) -> int:
        # Ensure buffer is allocated
        self.consumer.get_write_buffer()
        return self.consumer.buffer_size

    def clear(self) -> None:
        self.consumer.clear()

    async def receive(self) -> _T_ReceivedPacket:
        consumer = self.consumer
        try:
            return consumer.next(None)
        except StopIteration:
            pass

        transport = self.transport

        while not self._eof_reached:
            nbytes: int = await transport.recv_into(consumer.get_write_buffer())
            if not nbytes:
                self._eof_reached = True
                continue
            try:
                return consumer.next(nbytes)
            except StopIteration:
                pass

        raise EOFError("end-of-stream")
