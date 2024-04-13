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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = [
    "AbstractAsyncNetworkServer",
    "AbstractNetworkServer",
    "SupportsEventSet",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, Self

from ..lowlevel.api_async.backend.abc import AsyncBackend
from ..lowlevel.socket import SocketAddress

if TYPE_CHECKING:
    from types import TracebackType


class SupportsEventSet(Protocol):
    """
    A :class:`threading.Event`-like object.
    """

    @abstractmethod
    def set(self) -> None:
        """
        Notifies that the event has happened.

        This method MUST be idempotent.
        """
        ...


class AbstractNetworkServer(metaclass=ABCMeta):
    """
    The base class for a network server.
    """

    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Calls :meth:`server_close`."""
        self.server_close()

    @abstractmethod
    def is_serving(self) -> bool:
        """
        Checks whether the server is up and accepting new clients. Thread-safe.
        """
        raise NotImplementedError

    @abstractmethod
    def serve_forever(self, *, is_up_event: SupportsEventSet | None = ...) -> None:
        """
        Starts the server's main loop.

        Parameters:
            is_up_event: If given, will be triggered when the server is ready to accept new clients.

        Raises:
            ServerClosedError: The server is closed.
            ServerAlreadyRunning: Another task already called :meth:`serve_forever`.
        """
        raise NotImplementedError

    @abstractmethod
    def server_close(self) -> None:
        """
        Closes the server. Thread-safe.
        """
        raise NotImplementedError

    @abstractmethod
    def shutdown(self, timeout: float | None = ...) -> None:
        """
        Asks for the server to stop. Thread-safe.

        All active client tasks will be cancelled.

        Warning:
            Do not call this method in the :meth:`serve_forever` thread; it will cause a deadlock.

        Parameters:
            timeout: The maximum amount of seconds to wait.
        """
        raise NotImplementedError

    @abstractmethod
    def get_addresses(self) -> Sequence[SocketAddress]:
        """
        Returns all interfaces to which the server is bound. Thread-safe.

        Returns:
            A sequence of network socket address.
            If the server is not serving (:meth:`is_serving` returns :data:`False`), an empty sequence is returned.
        """
        raise NotImplementedError


class AbstractAsyncNetworkServer(metaclass=ABCMeta):
    """
    The base class for an asynchronous network server.
    """

    __slots__ = ("__weakref__",)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Calls :meth:`server_close`."""
        await self.server_close()

    @abstractmethod
    def is_serving(self) -> bool:
        """
        Checks whether the server is up and accepting new clients.
        """
        raise NotImplementedError

    @abstractmethod
    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = ...) -> None:
        """
        Starts the server's main loop.

        Parameters:
            is_up_event: If given, will be triggered when the server is ready to accept new clients.

        Raises:
            ServerClosedError: The server is closed.
            ServerAlreadyRunning: Another task already called :meth:`serve_forever`.
        """
        raise NotImplementedError

    @abstractmethod
    async def server_close(self) -> None:
        """
        Closes the server.
        """
        raise NotImplementedError

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Asks for the server to stop.

        All active client tasks will be cancelled.

        Warning:
            Do not call this method in the :meth:`serve_forever` task; it will cause a deadlock.
        """
        raise NotImplementedError

    @abstractmethod
    def get_addresses(self) -> Sequence[SocketAddress]:
        """
        Returns all interfaces to which the server is bound.

        Returns:
            A sequence of network socket address.
            If the server is not serving (:meth:`is_serving` returns :data:`False`), an empty sequence is returned.
        """

    @abstractmethod
    def backend(self) -> AsyncBackend:
        """
        Returns:
            The backend implementation linked to this server.
        """
        raise NotImplementedError
