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
"""Asynchronous network servers' request handler base classes module."""

from __future__ import annotations

__all__ = [
    "AsyncBaseClientInterface",
    "AsyncDatagramClient",
    "AsyncDatagramRequestHandler",
    "AsyncStreamClient",
    "AsyncStreamRequestHandler",
    "INETClientAttribute",
    "UNIXClientAttribute",
]

import contextlib
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncGenerator, Coroutine
from typing import TYPE_CHECKING, Any, Generic

from .._typevars import _T_Request, _T_Response
from ..lowlevel import socket as socket_tools, typed_attr

if TYPE_CHECKING:
    from ..lowlevel.api_async.backend.abc import AsyncBackend


class INETClientAttribute(typed_attr.TypedAttributeSet):
    """
    Typed attributes which can be used on an :class:`AsyncBaseClientInterface`.
    """

    __slots__ = ()

    socket: socket_tools.ISocket = socket_tools.SocketAttribute.socket
    """:class:`socket.socket` instance."""

    local_address: socket_tools.SocketAddress = socket_tools.SocketAttribute.sockname
    """the socket's own address, result of :meth:`socket.socket.getsockname`."""

    remote_address: socket_tools.SocketAddress = socket_tools.SocketAttribute.peername
    """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""


class UNIXClientAttribute(typed_attr.TypedAttributeSet):
    """
    Typed attributes which can be used on an :class:`AsyncBaseClientInterface`.

    .. versionadded:: 1.1
    """

    __slots__ = ()

    socket: socket_tools.ISocket = socket_tools.SocketAttribute.socket
    """:class:`socket.socket` instance."""

    local_name: socket_tools.UnixSocketAddress = typed_attr.typed_attribute()
    """the socket's own address, result of :meth:`socket.socket.getsockname`."""

    peer_name: socket_tools.UnixSocketAddress = typed_attr.typed_attribute()
    """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""

    peer_credentials: socket_tools.UnixCredentials = typed_attr.typed_attribute()
    """the credentials of the peer process connected to this socket."""


class AsyncBaseClientInterface(typed_attr.TypedAttributeProvider, Generic[_T_Response], metaclass=ABCMeta):
    """
    The base class for a client interface, used by request handlers.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    async def send_packet(self, packet: _T_Response, /) -> None:
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

    @abstractmethod
    def backend(self) -> AsyncBackend:
        """
        Returns:
            The backend implementation linked to the server.
        """
        raise NotImplementedError


class AsyncStreamClient(AsyncBaseClientInterface[_T_Response]):
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


class AsyncDatagramClient(AsyncBaseClientInterface[_T_Response]):
    """
    A client interface for datagram oriented connection, used by datagram request handlers.

    Unlike :class:`AsyncStreamClient`, the client object can be recreated on each ``handle()`` call,
    but implements ``__hash__()`` and ``__eq__()`` for uniqueness checking, so it can be used in a :class:`set` for example.
    """

    __slots__ = ()

    @abstractmethod
    def __hash__(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def __eq__(self, other: object, /) -> bool:
        raise NotImplementedError


class AsyncStreamRequestHandler(Generic[_T_Request, _T_Response], metaclass=ABCMeta):
    """
    The base class for a stream request handler, used by TCP network servers.
    """

    __slots__ = ("__weakref__",)

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: Any, /) -> None:
        """
        Called at server startup. The default implementation does nothing.

        Parameters:
            exit_stack: An :class:`~contextlib.AsyncExitStack` that can be used to add actions on server's tear down.
            server: A :func:`weakref.proxy` to the server instance.
        """
        pass

    @abstractmethod
    def handle(self, client: AsyncStreamClient[_T_Response], /) -> AsyncGenerator[float | None, _T_Request]:
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

        Yields:
            :data:`None` or a number interpreted as the timeout delay.
        """
        raise NotImplementedError

    def on_connection(
        self,
        client: AsyncStreamClient[_T_Response],
        /,
    ) -> Coroutine[Any, Any, None] | AsyncGenerator[float | None, _T_Request]:
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

        Yields:
            If it is an :term:`asynchronous generator`, :data:`None` or a number interpreted as the timeout delay.
        """

        async def _pass() -> None:
            pass

        return _pass()

    async def on_disconnection(self, client: AsyncStreamClient[_T_Response], /) -> None:
        """
        Called once the client is disconnected to perform any clean-up actions required. The default implementation does nothing.

        This function will not be called in the following conditions:

        * If :meth:`on_connection` raises an exception.

        * If :meth:`on_connection` is an :term:`asynchronous generator` function and the connection is closed.

        Important:
            :meth:`AsyncStreamClient.is_closing` should return :data:`True` when this function is called.
            However, if :meth:`handle` raises an exception, the client task is shut down and the connection is forcibly closed
            *after* :meth:`on_disconnection` is called.

            This behavior allows you to notify the client that something unusual has occurred.

        Parameters:
            client: An interface to communicate with the remote endpoint.
        """
        pass


class AsyncDatagramRequestHandler(Generic[_T_Request, _T_Response], metaclass=ABCMeta):
    """
    The base class for a datagram request handler, used by UDP network servers.
    """

    __slots__ = ("__weakref__",)

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: Any, /) -> None:
        """
        Called at server startup. The default implementation does nothing.

        Parameters:
            exit_stack: An :class:`~contextlib.AsyncExitStack` that can be used to add actions on server's tear down.
            server: A :func:`weakref.proxy` to the server instance.
        """
        pass

    @abstractmethod
    def handle(self, client: AsyncDatagramClient[_T_Response], /) -> AsyncGenerator[float | None, _T_Request]:
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

        Yields:
            :data:`None` or a number interpreted as the timeout delay.
        """
        raise NotImplementedError
