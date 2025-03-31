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
"""Low-level asynchronous endpoints module for connection-oriented communication."""

from __future__ import annotations

__all__ = [
    "AsyncStreamEndpoint",
    "AsyncStreamReceiverEndpoint",
    "AsyncStreamSenderEndpoint",
]

import dataclasses
import errno as _errno
import warnings
from collections.abc import Callable, Mapping
from typing import Any, Generic, assert_never

from ...._typevars import _T_ReceivedPacket, _T_SentPacket
from ....protocol import AnyStreamProtocolType
from ... import _stream, _utils
from ..backend.abc import AsyncBackend
from ..transports import abc as _transports


class AsyncStreamReceiverEndpoint(_transports.AsyncBaseTransport, Generic[_T_ReceivedPacket]):
    """
    A read-only communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__receiver",
        "__recv_guard",
    )

    def __init__(
        self,
        transport: _transports.AsyncStreamReadTransport,
        protocol: AnyStreamProtocolType[Any, _T_ReceivedPacket],
        max_recv_size: int,
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """

        if not isinstance(transport, _transports.AsyncStreamReadTransport):
            raise TypeError(f"Expected an AsyncStreamReadTransport object, got {transport!r}")
        _check_max_recv_size_value(max_recv_size)

        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] | _BufferedReceiverImpl[_T_ReceivedPacket] = _get_receiver(
            transport=transport,
            protocol=protocol,
            max_recv_size=max_recv_size,
        )

        self.__transport: _transports.AsyncStreamReadTransport = transport
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

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the transport to close.

            If :meth:`aclose` is cancelled, the transport is closed abruptly.
        """
        try:
            await self.__transport.aclose()
        finally:
            self.__receiver.clear()

    async def recv_packet(self) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint.

        Raises:
            ConnectionAbortedError: the read end of the stream is closed.
            StreamProtocolParseError: invalid data received.

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


class AsyncStreamSenderEndpoint(_transports.AsyncBaseTransport, Generic[_T_SentPacket]):
    """
    A write-only communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__send_guard",
    )

    def __init__(
        self,
        transport: _transports.AsyncStreamWriteTransport,
        protocol: AnyStreamProtocolType[_T_SentPacket, Any],
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
        """

        if not isinstance(transport, _transports.AsyncStreamWriteTransport):
            raise TypeError(f"Expected an AsyncStreamWriteTransport object, got {transport!r}")

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, _stream.StreamDataProducer(protocol))

        self.__transport: _transports.AsyncStreamWriteTransport = transport
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

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the transport to close.

            If :meth:`aclose` is cancelled, the transport is closed abruptly.
        """
        await self.__transport.aclose()

    async def send_packet(self, packet: _T_SentPacket) -> None:
        """
        Sends `packet` to the remote endpoint.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.
        """
        with self.__send_guard:
            sender = self.__sender

            return await sender.send(packet)

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__transport.backend()

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class AsyncStreamEndpoint(_transports.AsyncBaseTransport, Generic[_T_SentPacket, _T_ReceivedPacket]):
    """
    A full-duplex communication endpoint based on continuous stream data transport.
    """

    __slots__ = (
        "__transport",
        "__sender",
        "__receiver",
        "__send_guard",
        "__recv_guard",
        "__eof_sent",
    )

    def __init__(
        self,
        transport: _transports.AsyncStreamTransport,
        protocol: AnyStreamProtocolType[_T_SentPacket, _T_ReceivedPacket],
        max_recv_size: int,
    ) -> None:
        """
        Parameters:
            transport: The data transport to use.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
        """

        if not isinstance(transport, _transports.AsyncStreamTransport):
            raise TypeError(f"Expected an AsyncStreamTransport object, got {transport!r}")
        _check_max_recv_size_value(max_recv_size)

        self.__sender: _DataSenderImpl[_T_SentPacket] = _DataSenderImpl(transport, _stream.StreamDataProducer(protocol))
        self.__receiver: _DataReceiverImpl[_T_ReceivedPacket] | _BufferedReceiverImpl[_T_ReceivedPacket] = _get_receiver(
            transport=transport,
            protocol=protocol,
            max_recv_size=max_recv_size,
        )

        self.__transport: _transports.AsyncStreamTransport = transport
        self.__send_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently sending data on this endpoint")
        self.__recv_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receving data on this endpoint")
        self.__eof_sent: bool = False

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

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the transport to close.

            If :meth:`aclose` is cancelled, the transport is closed abruptly.
        """
        with self.__send_guard:
            try:
                await self.__transport.aclose()
            finally:
                self.__receiver.clear()

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

            transport = self.__transport

            await transport.send_eof()
            self.__eof_sent = True

    async def recv_packet(self) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint.

        Raises:
            ConnectionAbortedError: the read end of the stream is closed.
            StreamProtocolParseError: invalid data received.

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
    transport: _transports.AsyncStreamWriteTransport
    producer: _stream.StreamDataProducer[_T_SentPacket]

    async def send(self, packet: _T_SentPacket) -> None:
        return await self.transport.send_all_from_iterable(self.producer.generate(packet))


@dataclasses.dataclass(slots=True)
class _DataReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: _transports.AsyncStreamReadTransport
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

        raise _utils.error_from_errno(_errno.ECONNABORTED, "{strerror} (end-of-stream)")


@dataclasses.dataclass(slots=True)
class _BufferedReceiverImpl(Generic[_T_ReceivedPacket]):
    transport: _transports.AsyncStreamReadTransport
    consumer: _stream.BufferedStreamDataConsumer[_T_ReceivedPacket]
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

        while not self._eof_reached:
            with consumer.get_write_buffer() as buffer:
                nbytes: int = await transport.recv_into(buffer)
            if not nbytes:
                self._eof_reached = True
                continue
            try:
                return consumer.next(nbytes)
            except StopIteration:
                pass

        raise _utils.error_from_errno(_errno.ECONNABORTED, "{strerror} (end-of-stream)")


def _get_receiver(
    transport: _transports.AsyncStreamReadTransport,
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
