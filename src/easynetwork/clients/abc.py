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
"""Network client interfaces definition module."""

from __future__ import annotations

__all__ = ["AbstractAsyncNetworkClient", "AbstractNetworkClient"]

from abc import ABCMeta, abstractmethod
from collections.abc import AsyncIterator, Iterator
from types import TracebackType
from typing import Generic, Self

from .._typevars import _T_ReceivedPacket, _T_SentPacket
from ..lowlevel.api_async.backend.abc import AsyncBackend


class AbstractNetworkClient(Generic[_T_SentPacket, _T_ReceivedPacket], metaclass=ABCMeta):
    """
    The base class for a network client interface.
    """

    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        """
        Calls :meth:`close`.
        """
        self.close()

    @abstractmethod
    def is_closed(self) -> bool:
        """
        Checks if the client is in a closed state.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        See Also:
            :meth:`close` method.

        Returns:
            the client state.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """
        Close the client.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Can be safely called multiple times.
        """
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _T_SentPacket, *, timeout: float | None = ...) -> None:
        """
        Sends `packet` to the remote endpoint.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Warning:
            A timeout on a send operation is unusual unless the implementation is using a lower-level
            communication protocol (such as SSL/TLS).

            In the case of a timeout, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            TimeoutError: the send operation does not end up after `timeout` seconds.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        raise NotImplementedError

    @abstractmethod
    def recv_packet(self, *, timeout: float | None = ...) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            TimeoutError: the receive operation does not end up after `timeout` seconds.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            BaseProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        raise NotImplementedError

    def iter_received_packets(self, *, timeout: float | None = 0) -> Iterator[_T_ReceivedPacket]:
        """
        Returns an :term:`iterator` that waits for a new packet to arrive from the remote endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds; it defaults to zero.

        Important:
            The `timeout` is for the entire iterator::

                iterator = client.iter_received_packets(timeout=10)

                # Let's say that this call took 6 seconds...
                first_packet = next(iterator)

                # ...then this call has a maximum of 4 seconds, not 10.
                second_packet = next(iterator)

            The time taken outside the iterator object is not decremented to the timeout parameter.

        Parameters:
            timeout: the allowed time (in seconds) for all the receive operations.

        Yields:
            the received packet.
        """
        from ._iter import ClientRecvIterator

        return ClientRecvIterator(self, timeout)

    @abstractmethod
    def fileno(self) -> int:
        """
        Returns the client's file descriptor, or ``-1`` if client is closed.

        Returns:
            the opened file descriptor.
        """
        raise NotImplementedError


class AbstractAsyncNetworkClient(Generic[_T_SentPacket, _T_ReceivedPacket], metaclass=ABCMeta):
    """
    The base class for an asynchronous network client interface.
    """

    __slots__ = ("__weakref__",)

    async def __aenter__(self) -> Self:
        """
        Calls :meth:`wait_connected`.
        """
        await self.wait_connected()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Calls :meth:`aclose`.
        """
        await self.aclose()

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Checks if the client initialization is finished.

        See Also:
            :meth:`wait_connected` method.

        Returns:
            the client connection state.
        """
        raise NotImplementedError

    @abstractmethod
    async def wait_connected(self) -> None:
        """
        Finishes initializing the client, doing the asynchronous operations that could not be done in the constructor.

        It is not needed to call it directly if the client is used as an :term:`asynchronous context manager`::

            async with client:  # wait_connected() has been called.
                ...

        Warning:
            In the case of a cancellation, this would leave the client in an inconsistent state.

            It is recommended to close the client in this case.

        Can be safely called multiple times.
        """
        raise NotImplementedError

    @abstractmethod
    def is_closing(self) -> bool:
        """
        Checks if the client is closed or in the process of being closed.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        See Also:
            :meth:`aclose` method.

        Returns:
            the client state.
        """
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        """
        Close the client.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the connection to close.

            If :meth:`aclose` is cancelled, the client is closed abruptly.

        Can be safely called multiple times.
        """
        raise NotImplementedError

    @abstractmethod
    async def send_packet(self, packet: _T_SentPacket) -> None:
        """
        Sends `packet` to the remote endpoint.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
        """
        raise NotImplementedError

    @abstractmethod
    async def recv_packet(self) -> _T_ReceivedPacket:
        """
        Waits for a new packet to arrive from the remote endpoint.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: unrelated OS error occurred. You should check :attr:`OSError.errno`.
            BaseProtocolParseError: invalid data received.

        Returns:
            the received packet.
        """
        raise NotImplementedError

    def iter_received_packets(self, *, timeout: float | None = 0) -> AsyncIterator[_T_ReceivedPacket]:
        """
        Returns an :term:`asynchronous iterator` that waits for a new packet to arrive from the remote endpoint.

        If `timeout` is not :data:`None`, the entire receive operation will take at most `timeout` seconds; it defaults to zero.

        Important:
            The `timeout` is for the entire iterator::

                async_iterator = client.iter_received_packets(timeout=10)

                # Let's say that this call took 6 seconds...
                first_packet = await anext(async_iterator)

                # ...then this call has a maximum of 4 seconds, not 10.
                second_packet = await anext(async_iterator)

            The time taken outside the iterator object is not decremented to the timeout parameter.

        Parameters:
            timeout: the allowed time (in seconds) for all the receive operations.

        Yields:
            the received packet.
        """
        from ._iter import AsyncClientRecvIterator

        return AsyncClientRecvIterator(self, timeout)

    @abstractmethod
    def backend(self) -> AsyncBackend:
        """
        Returns:
            The backend implementation linked to this client.
        """
        raise NotImplementedError
