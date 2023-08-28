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
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AbstractAsyncNetworkClient"]

from abc import ABCMeta, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Generic, Self

from ..._typevars import _ReceivedPacketT, _SentPacketT
from ...tools.socket import SocketAddress

if TYPE_CHECKING:
    from types import TracebackType

    from ..backend.abc import AbstractAsyncBackend


class AbstractAsyncNetworkClient(Generic[_SentPacketT, _ReceivedPacketT], metaclass=ABCMeta):
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

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

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
    def get_local_address(self) -> SocketAddress:
        """
        Returns the local socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occurr.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the client's local address.
        """
        raise NotImplementedError

    @abstractmethod
    def get_remote_address(self) -> SocketAddress:
        """
        Returns the remote socket IP address.

        If :meth:`wait_connected` was not called, an :exc:`OSError` may occurr.

        Raises:
            ClientClosedError: the client object is closed.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the client's remote address.
        """
        raise NotImplementedError

    @abstractmethod
    async def send_packet(self, packet: _SentPacketT) -> None:
        """
        Sends `packet` to the remote endpoint.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Arguments:
            packet: the Python object to send.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.
        """
        raise NotImplementedError

    @abstractmethod
    async def recv_packet(self) -> _ReceivedPacketT:
        """
        Waits for a new packet to arrive from the remote endpoint.

        Raises:
            ClientClosedError: the client object is closed.
            ConnectionError: connection unexpectedly closed during operation.
                             You should not attempt any further operation and close the client object.
            OSError: Unrelated OS error happen. You should check :attr:`OSError.errno`.

        Returns:
            the received packet.
        """
        raise NotImplementedError

    async def iter_received_packets(self) -> AsyncIterator[_ReceivedPacketT]:
        """
        Returns an :term:`asynchronous iterator` that waits for a new packet to arrive from the remote endpoint.

        Yields:
            the received packet.
        """
        while True:
            try:
                packet = await self.recv_packet()
            except OSError:
                return
            yield packet

    @abstractmethod
    def get_backend(self) -> AbstractAsyncBackend:
        raise NotImplementedError
