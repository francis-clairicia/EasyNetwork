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
"""Low-level endpoints module for connection-oriented communication."""

from __future__ import annotations

__all__ = [
    "StreamEndpoint",
    "StreamReceiverEndpoint",
    "StreamSenderEndpoint",
]

import dataclasses
import errno as _errno
import math
import warnings
from collections.abc import Callable, Mapping
from typing import Any, Generic, assert_never

from ...._typevars import _T_ReceivedPacket, _T_SentPacket
from ....protocol import AnyStreamProtocolType
from ... import _stream, _utils
from ..transports import abc as _transports


class StreamReceiverEndpoint(_transports.BaseTransport, Generic[_T_ReceivedPacket]):
    """
    A read-only communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__receiver",
    )

    def __init__(
        self,
        transport: _transports.StreamReadTransport,
        protocol: AnyStreamProtocolType[Any, _T_ReceivedPacket],
        max_recv_size: int,
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """

        if not isinstance(transport, _transports.StreamReadTransport):
            raise TypeError(f"Expected a StreamReadTransport object, got {transport!r}")
        _check_max_recv_size_value(max_recv_size)

        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] | _BufferedReceiverImpl[_T_ReceivedPacket] = _get_receiver(
            transport=transport,
            protocol=protocol,
            max_recv_size=max_recv_size,
        )

        self.__transport: _transports.StreamReadTransport = transport

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
        try:
            self.__transport.close()
        finally:
            self.__receiver.clear()

    def recv_packet(self, *, timeout: float | None = None) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            ConnectionAbortedError: the read end of the stream is closed.
            StreamProtocolParseError: invalid data received.

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


class StreamSenderEndpoint(_transports.BaseTransport, Generic[_T_SentPacket]):
    """
    A write-only communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__sender",
    )

    def __init__(
        self,
        transport: _transports.StreamWriteTransport,
        protocol: AnyStreamProtocolType[_T_SentPacket, Any],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.StreamWriteTransport):
            raise TypeError(f"Expected a StreamWriteTransport object, got {transport!r}")

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, _stream.StreamDataProducer(protocol))
        self.__transport: _transports.StreamWriteTransport = transport

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
            A timeout on a send operation is unusual unless you have a SSL/TLS context.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

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


class StreamEndpoint(_transports.BaseTransport, Generic[_T_SentPacket, _T_ReceivedPacket]):
    """
    A full-duplex communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__receiver",
        "__eof_sent",
    )

    def __init__(
        self,
        transport: _transports.StreamTransport,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        max_recv_size: int,
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """

        if not isinstance(transport, _transports.StreamTransport):
            raise TypeError(f"Expected a StreamTransport object, got {transport!r}")
        _check_max_recv_size_value(max_recv_size)

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, _stream.StreamDataProducer(protocol))
        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] | _BufferedReceiverImpl[_T_ReceivedPacket] = _get_receiver(
            transport=transport,
            protocol=protocol,
            max_recv_size=max_recv_size,
        )

        self.__transport: _transports.StreamTransport = transport
        self.__eof_sent: bool = False

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
        try:
            self.__transport.close()
        finally:
            self.__receiver.clear()

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

        transport = self.__transport

        transport.send_eof()
        self.__eof_sent = True

    def recv_packet(self, *, timeout: float | None = None) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            ConnectionAbortedError: the read end of the stream is closed.
            StreamProtocolParseError: invalid data received.

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
    transport: _transports.StreamWriteTransport
    producer: _stream.StreamDataProducer[_T_SentPacket]

    def send(self, packet: _T_SentPacket, timeout: float) -> None:
        return self.transport.send_all_from_iterable(self.producer.generate(packet), timeout)


@dataclasses.dataclass(slots=True)
class _DataReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: _transports.StreamReadTransport
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
            raise _utils.error_from_errno(_errno.ECONNABORTED, "{strerror} (end-of-stream)")
        raise _utils.error_from_errno(_errno.ETIMEDOUT)


@dataclasses.dataclass(slots=True)
class _BufferedReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: _transports.StreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_ReceivedPacket]
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
        while not self._eof_reached:
            with consumer.get_write_buffer() as buffer:
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
            raise _utils.error_from_errno(_errno.ECONNABORTED, "{strerror} (end-of-stream)")
        raise _utils.error_from_errno(_errno.ETIMEDOUT)


def _get_receiver(
    transport: _transports.StreamReadTransport,
    protocol: AnyStreamProtocolType[Any, _T_ReceivedPacket],
    *,
    max_recv_size: int,
) -> _DataReceiverImpl[_T_ReceivedPacket] | _BufferedReceiverImpl[_T_ReceivedPacket]:
    from ....protocol import BufferedStreamProtocol, StreamProtocol

    _stream._check_any_protocol(protocol)

    match protocol:
        case BufferedStreamProtocol():
            return _BufferedReceiverImpl(transport, _stream.BufferedStreamDataConsumer(protocol, max_recv_size))
        case StreamProtocol():
            return _DataReceiverImpl(transport, _stream.StreamDataConsumer(protocol), max_recv_size)
        case _:  # pragma: no cover
            assert_never(protocol)


def _check_max_recv_size_value(max_recv_size: int) -> None:
    if not isinstance(max_recv_size, int) or max_recv_size <= 0:
        raise ValueError("'max_recv_size' must be a strictly positive integer")
