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
"""Asynchronous network servers' request handler base classes module"""

from __future__ import annotations

__all__ = [
    "AsyncBaseClientInterface",
    "AsyncDatagramClient",
    "AsyncDatagramRequestHandler",
    "AsyncStreamClient",
    "AsyncStreamRequestHandler",
]

import contextlib
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncGenerator, Coroutine
from typing import TYPE_CHECKING, Any, Generic, final

from ..._typevars import _RequestT, _ResponseT
from ...lowlevel.socket import SocketAddress, SocketProxy

if TYPE_CHECKING:
    from ..server.tcp import AsyncTCPNetworkServer
    from ..server.udp import AsyncUDPNetworkServer


class AsyncBaseClientInterface(Generic[_ResponseT], metaclass=ABCMeta):
    """
    The base class for a client interface, used by request handlers.
    """

    __slots__ = ("__addr", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        """
        Parameters:
            address: The remote endpoint's address.
        """
        super().__init__()
        self.__addr: SocketAddress = address

    def __repr__(self) -> str:
        return f"<client with address {self.address} at {id(self):#x}>"

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    async def send_packet(self, packet: _ResponseT, /) -> None:
        """
        Sends `packet` to the remote endpoint. Does not require task synchronization.

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
    def is_closing(self) -> bool:
        """
        Checks if the client is closed or in the process of being closed.

        If :data:`True`, all future operations on the client object will raise a :exc:`.ClientClosedError`.

        Returns:
            the client state.
        """
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        """The remote endpoint's address. Read-only attribute."""
        return self.__addr

    @property
    @abstractmethod
    def socket(self) -> SocketProxy:
        """A view to the underlying socket instance. Read-only attribute."""
        raise NotImplementedError


class AsyncStreamClient(AsyncBaseClientInterface[_ResponseT]):
    """
    A client interface for stream oriented connection, used by stream request handlers.
    """

    __slots__ = ()

    @abstractmethod
    async def aclose(self) -> None:
        """
        Close the client. Does not require task synchronization.

        Once that happens, all future operations on the client object will raise a :exc:`.ClientClosedError`.
        The remote end will receive no more data (after queued data is flushed).

        Can be safely called multiple times.

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the connection to close.

            If :meth:`aclose` is cancelled, the client is closed abruptly.
        """
        raise NotImplementedError


class AsyncDatagramClient(AsyncBaseClientInterface[_ResponseT]):
    """
    A client interface for datagram oriented connection, used by datagram request handlers.
    """

    __slots__ = ()

    @abstractmethod
    def __hash__(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def __eq__(self, other: object, /) -> bool:
        raise NotImplementedError


class AsyncStreamRequestHandler(Generic[_RequestT, _ResponseT], metaclass=ABCMeta):
    """
    The base class for a stream request handler, used by TCP network servers.
    """

    __slots__ = ("__weakref__",)

    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncTCPNetworkServer[_RequestT, _ResponseT],
        /,
    ) -> None:
        """
        Called at the server startup. The default implementation does nothing.

        Parameters:
            exit_stack: An :class:`~contextlib.AsyncExitStack` that can be used to add actions on server's tear down.
            server: A :func:`weakref.proxy` to the server instance.
        """
        pass

    @abstractmethod
    def handle(self, client: AsyncStreamClient[_ResponseT], /) -> AsyncGenerator[None, _RequestT]:
        """
        This function must do all the work required to service a request.

        It is an :term:`asynchronous generator` function::

            async def handle(self, client):
                request = yield

                # Do some stuff
                ...

                await client.send_packet(response)

        :meth:`handle` can :keyword:`yield` whenever a request from the `client` is needed.

        The generator is started immediately after :meth:`on_connection`.
        When the generator returns, a new generator is created and started immediately after.

        The generator **does not** represent the client life time, ``await client.aclose()`` must be called explicitly.

        Note:
            There is one exception: if the generator returns before the first :keyword:`yield` statement,
            the connection is forcibly closed.

        Parameters:
            client: An interface to communicate with the remote endpoint.
        """
        raise NotImplementedError

    def on_connection(
        self,
        client: AsyncStreamClient[_ResponseT],
        /,
    ) -> Coroutine[Any, Any, None] | AsyncGenerator[None, _RequestT]:
        """
        Called once the client is connected to perform any initialization actions required.
        The default implementation does nothing.

        It can be either a :term:`coroutine function`::

            async def on_connection(self, client):
                # Do some stuff
                ...

        or an :term:`asynchronous generator` function::

            async def on_connection(self, client):
                # Do some stuff
                ...

                initial_info = yield

                # Finish initialization
                ...

        In the latter case, as for :meth:`handle`, :meth:`on_connection` can :keyword:`yield` whenever a request from
        the `client` is needed.

        Parameters:
            client: An interface to communicate with the remote endpoint.
        """

        async def _pass() -> None:
            pass

        return _pass()

    async def on_disconnection(self, client: AsyncStreamClient[_ResponseT], /) -> None:
        """
        Called once the client is disconnected to perform any clean-up actions required. The default implementation does nothing.

        This function will not be called in the following conditions:

        * If :meth:`on_connection` is a simple :term:`coroutine function` and raises an exception.

        * If :meth:`on_connection` is an :term:`asynchronous generator` function and raises an exception
          before the first :keyword:`yield`.

        Important:
            :meth:`AsyncStreamClient.is_closing` should return :data:`True` when this function is called.
            However, if :meth:`handle` raises an exception, the client task is shut down and the connection is forcibly closed
            *after* :meth:`on_disconnection` is called.

            This behavior allows you to notify the client that something unusual has occurred.

        Parameters:
            client: An interface to communicate with the remote endpoint.
        """
        pass


class AsyncDatagramRequestHandler(Generic[_RequestT, _ResponseT], metaclass=ABCMeta):
    """
    The base class for a datagram request handler, used by UDP network servers.
    """

    __slots__ = ("__weakref__",)

    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncUDPNetworkServer[_RequestT, _ResponseT],
        /,
    ) -> None:
        """
        Called at the server startup. The default implementation does nothing.

        Parameters:
            exit_stack: An :class:`~contextlib.AsyncExitStack` that can be used to add actions on server's tear down.
            server: A :func:`weakref.proxy` to the server instance.
        """
        pass

    @abstractmethod
    def handle(self, client: AsyncDatagramClient[_ResponseT], /) -> AsyncGenerator[None, _RequestT]:
        """
        This function must do all the work required to service a request.

        It is an :term:`asynchronous generator` function::

            async def handle(self, client):
                request = yield

                # Do some stuff
                ...

                await client.send_packet(response)

        :meth:`handle` can :keyword:`yield` whenever a request from the `client` is needed.

        Warning:
            UDP does not guarantee ordered delivery. Packets are typically "sent" in order, but they may be received out of order.
            In large networks, it is reasonably common for some packets to arrive out of sequence (or not at all).

        Since there is no connection management, the generator is started when the datagram is received.
        When the generator returns, a new generator is created and started when a new datagram is received.

        Important:
            There will always be only one active generator per client.
            All the pending datagrams received while the generator is running are queued.

            This behavior is designed to act like a stream request handler.

        Note:
            If the generator returns before the first :keyword:`yield` statement, the received datagram is discarded.

            This is useful when a client that you do not expect to see sends something; the datagrams are parsed only when
            the generator hits a :keyword:`yield` statement.

        Parameters:
            client: An interface to communicate with the remote endpoint.
        """
        raise NotImplementedError
