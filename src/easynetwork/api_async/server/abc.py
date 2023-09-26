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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = [
    "AbstractAsyncNetworkServer",
    "SupportsEventSet",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, Self

if TYPE_CHECKING:
    from types import TracebackType

    from ..backend.abc import AsyncBackend


class SupportsEventSet(Protocol):
    """
    A :class:`threading.Event`-like object.
    """

    def set(self) -> None:  # pragma: no cover
        """
        Notifies that the event has happened.

        This method MUST be idempotent.
        """
        ...


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

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def is_serving(self) -> bool:
        """
        Checks whether the server is up and accepting new clients.
        """
        raise NotImplementedError

    @abstractmethod
    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = ...) -> NoReturn:
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
    def get_backend(self) -> AsyncBackend:
        raise NotImplementedError
