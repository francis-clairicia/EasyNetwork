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

__all__ = ["StreamEndpoint"]

import errno as _errno
import math
import time
from collections.abc import Callable, Mapping
from typing import Any, Generic

from ...._typevars import _ReceivedPacketT, _SentPacketT
from ....protocol import StreamProtocol
from ....tools import typed_attr
from ....tools._stream import StreamDataConsumer as _StreamDataConsumer, StreamDataProducer as _StreamDataProducer
from ....tools._utils import error_from_errno as _error_from_errno
from ..transports.abc import StreamTransport


class StreamEndpoint(Generic[_SentPacketT, _ReceivedPacketT], typed_attr.TypedAttributeProvider):
    """
    A communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__producer",
        "__consumer",
        "__max_recv_size",
        "__eof_sent",
        "__eof_reached",
        "__weakref__",
    )

    def __init__(
        self,
        transport: StreamTransport,
        protocol: StreamProtocol[_SentPacketT, _ReceivedPacketT],
        max_recv_size: int,
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """

        if not isinstance(transport, StreamTransport):
            raise TypeError(f"Expected a StreamTransport object, got {transport!r}")
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__producer: _StreamDataProducer[_SentPacketT] = _StreamDataProducer(protocol)
        self.__consumer: _StreamDataConsumer[_ReceivedPacketT] = _StreamDataConsumer(protocol)
        self.__transport: StreamTransport = transport
        self.__max_recv_size: int = max_recv_size
        self.__eof_sent: bool = False
        self.__eof_reached: bool = False

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
        self.__consumer.clear()
        self.__producer.clear()

    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = None) -> None:
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

        if timeout is None:
            timeout = math.inf

        transport = self.__transport
        producer = self.__producer

        producer.enqueue(packet)
        transport.send_all_from_iterable(producer, timeout)

    def send_eof(self) -> None:
        """
        Close the write end of the stream after the buffered write data is flushed.

        Can be safely called multiple times.
        """
        if self.__eof_sent:
            return

        transport = self.__transport
        producer = self.__producer

        if not transport.is_closed():
            transport.send_eof()
        self.__eof_sent = True
        producer.clear()

    def recv_packet(self, *, timeout: float | None = None) -> _ReceivedPacketT:
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
        if timeout is None:
            timeout = math.inf

        transport = self.__transport
        consumer = self.__consumer

        try:
            return next(consumer)  # If there is enough data from last call to create a packet, return immediately
        except StopIteration:
            pass

        if self.__eof_reached:
            raise EOFError("end-of-stream")

        bufsize: int = self.__max_recv_size
        perf_counter = time.perf_counter  # pull function to local namespace

        while True:
            _start = perf_counter()
            chunk: bytes = transport.recv(bufsize, timeout)
            _end = perf_counter()
            if not chunk:
                self.__eof_reached = True
                raise EOFError("end-of-stream")
            try:
                consumer.feed(chunk)
            finally:
                del chunk
            with consumer.get_buffer() as buffer:
                buffer_not_full: bool = buffer.nbytes < bufsize
            try:
                return next(consumer)
            except StopIteration:
                if timeout > 0:
                    timeout -= _end - _start
                    timeout = max(timeout, 0.0)
                elif buffer_not_full:
                    break
        # Loop break
        raise _error_from_errno(_errno.ETIMEDOUT)

    @property
    def max_recv_size(self) -> int:
        """Read buffer size. Read-only attribute."""
        return self.__max_recv_size

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes
