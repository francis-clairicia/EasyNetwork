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
"""Network client interfaces definition module"""

from __future__ import annotations

__all__ = ["AbstractNetworkClient"]

import time
from abc import ABCMeta, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING, Generic, Self

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...lowlevel.socket import SocketAddress

if TYPE_CHECKING:
    from types import TracebackType


class AbstractNetworkClient(Generic[_SentPacketT, _ReceivedPacketT], metaclass=ABCMeta):
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
    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        Raises:
            ClientClosedError: the client object is closed.

        Returns:
            the client's local address.
        """
        raise NotImplementedError

    @abstractmethod
    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address.

        Raises:
            ClientClosedError: the client object is closed.

        Returns:
            the client's remote address.
        """
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = ...) -> None:
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
    def recv_packet(self, *, timeout: float | None = ...) -> _ReceivedPacketT:
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

    def iter_received_packets(self, *, timeout: float | None = 0) -> Iterator[_ReceivedPacketT]:
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
        perf_counter = time.perf_counter

        while True:
            try:
                _start = perf_counter()
                packet = self.recv_packet(timeout=timeout)
                _end = perf_counter()
            except OSError:
                return
            yield packet
            if timeout is not None:
                timeout -= _end - _start
                timeout = max(timeout, 0)

    @abstractmethod
    def fileno(self) -> int:
        """
        Returns the socket's file descriptor, or ``-1`` if client (or socket) is closed.

        Returns:
            the opened file descriptor.
        """
        raise NotImplementedError
