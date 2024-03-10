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
"""Low-level endpoints module"""

from __future__ import annotations

__all__ = ["StreamEndpoint"]

import dataclasses
import errno as _errno
import math
import warnings
from collections.abc import Callable, Mapping
from typing import Any, Generic, Literal, assert_never

from .... import protocol as protocol_module
from ...._typevars import _T_ReceivedPacket, _T_SentPacket
from ....exceptions import UnsupportedOperation
from ....warnings import ManualBufferAllocationWarning
from ... import _stream, _utils, typed_attr
from ..transports import abc as transports


class StreamEndpoint(typed_attr.TypedAttributeProvider, Generic[_T_SentPacket, _T_ReceivedPacket]):
    """
    A communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__receiver",
        "__eof_sent",
        "__weakref__",
    )

    def __init__(
        self,
        transport: transports.StreamTransport | transports.StreamReadTransport | transports.StreamWriteTransport,
        protocol: protocol_module.StreamProtocol[_T_SentPacket, _T_ReceivedPacket],
        max_recv_size: int,
        *,
        manual_buffer_allocation: Literal["try", "no", "force"] = "try",
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """

        if not isinstance(transport, (transports.StreamReadTransport, transports.StreamWriteTransport)):
            raise TypeError(f"Expected a StreamTransport object, got {transport!r}")
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")
        if manual_buffer_allocation not in ("try", "no", "force"):
            raise ValueError('"manual_buffer_allocation" must be "try", "no" or "force"')

        self.__transport: transports.StreamReadTransport | transports.StreamWriteTransport = transport
        self.__eof_sent: bool = False

        self.__sender: _DataSenderImpl[_T_SentPacket] | None = None
        if isinstance(transport, transports.StreamWriteTransport):
            self.__sender = _DataSenderImpl(transport, _stream.StreamDataProducer(protocol))

        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] | _BufferedReceiverImpl[_T_ReceivedPacket] | None = None
        if isinstance(transport, transports.StreamReadTransport):
            match manual_buffer_allocation:
                case "try" | "force":
                    try:
                        buffered_consumer = _stream.BufferedStreamDataConsumer(protocol, max_recv_size)
                        if not isinstance(transport, transports.BufferedStreamReadTransport):
                            msg = f"The transport implementation {transport!r} does not implement BufferedStreamReadTransport interface"
                            if manual_buffer_allocation == "try":
                                warnings.warn(msg, category=ManualBufferAllocationWarning, stacklevel=2)
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
            if self.__receiver is None:
                raise AssertionError("self.__receiver should be set.")

    def __del__(self) -> None:
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
        if self.__receiver is not None:
            self.__receiver.clear()
        if self.__sender is not None:
            self.__sender.clear()

    def send_packet(self, packet: _T_SentPacket, *, timeout: float | None = None) -> None:
        """
        Sends `packet` to the remote endpoint.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Warning:
            A timeout on a send operation is unusual unless you have a SSL/TLS context.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the send operation does not end up after `timeout` seconds.
            RuntimeError: :meth:`send_eof` has been called earlier.
        """
        if self.__eof_sent:
            raise RuntimeError("send_eof() has been called earlier")

        sender = self.__sender

        if sender is None:
            raise UnsupportedOperation("transport does not support sending data")

        if timeout is None:
            timeout = math.inf

        return sender.send(packet, timeout)

    def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed.

        This method does nothing if the endpoint is closed.

        Can be safely called multiple times.
        """
        if self.__eof_sent:
            return

        sender = self.__sender

        if sender is None or not isinstance(sender.transport, transports.StreamTransport):
            raise UnsupportedOperation("transport does not support sending EOF")

        sender.transport.send_eof()
        self.__eof_sent = True
        sender.clear()

    def recv_packet(self, *, timeout: float | None = None) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            EOFError: the read end of the stream is closed.
            StreamProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        receiver = self.__receiver

        if receiver is None:
            raise UnsupportedOperation("transport does not support receiving data")

        if timeout is None:
            timeout = math.inf

        return receiver.receive(timeout)

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
    transport: transports.StreamWriteTransport
    producer: _stream.StreamDataProducer[_T_SentPacket]

    def clear(self) -> None:
        pass

    def send(self, packet: _T_SentPacket, timeout: float) -> None:
        return self.transport.send_all_from_iterable(self.producer.generate(packet), timeout)


@dataclasses.dataclass(slots=True)
class _DataReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: transports.StreamReadTransport
    consumer: _stream.StreamDataConsumer[_T_ReceivedPacket]
    max_recv_size: int
    _eof_reached: bool = dataclasses.field(init=False, default=False)

    def clear(self) -> None:
        self.consumer.clear()

    def receive(self, timeout: float) -> _T_ReceivedPacket:
        consumer = self.consumer
        try:
            return consumer.next(None)
        except StopIteration:
            pass

        transport = self.transport
        bufsize: int = self.max_recv_size

        while not self._eof_reached:
            with _utils.ElapsedTime() as elapsed:
                chunk: bytes = transport.recv(bufsize, timeout)
            if not chunk:
                self._eof_reached = True
                continue
            try:
                return consumer.next(chunk)
            except StopIteration:
                if timeout > 0:
                    timeout = elapsed.recompute_timeout(timeout)
                elif len(chunk) < bufsize:
                    break
            finally:
                del chunk
        # Loop break
        if self._eof_reached:
            raise EOFError("end-of-stream")
        raise _utils.error_from_errno(_errno.ETIMEDOUT)


@dataclasses.dataclass(slots=True)
class _BufferedReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: transports.BufferedStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_ReceivedPacket]
    _eof_reached: bool = dataclasses.field(init=False, default=False)

    @property
    def max_recv_size(self) -> int:
        # Ensure buffer is allocated
        self.consumer.get_write_buffer()
        return self.consumer.buffer_size

    def clear(self) -> None:
        self.consumer.clear()

    def receive(self, timeout: float) -> _T_ReceivedPacket:
        consumer = self.consumer
        try:
            return consumer.next(None)
        except StopIteration:
            pass

        transport = self.transport
        while not self._eof_reached:
            with memoryview(consumer.get_write_buffer()) as buffer:
                bufsize: int = buffer.nbytes
                with _utils.ElapsedTime() as elapsed:
                    nbytes: int = transport.recv_into(buffer, timeout)
            if not nbytes:
                self._eof_reached = True
                continue
            try:
                return consumer.next(nbytes)
            except StopIteration:
                if timeout > 0:
                    timeout = elapsed.recompute_timeout(timeout)
                elif nbytes < bufsize:
                    break
        # Loop break
        if self._eof_reached:
            raise EOFError("end-of-stream")
        raise _utils.error_from_errno(_errno.ETIMEDOUT)
