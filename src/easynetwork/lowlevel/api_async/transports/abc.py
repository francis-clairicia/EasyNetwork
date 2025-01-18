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
"""Low-level asynchronous transports interfaces module."""

from __future__ import annotations

__all__ = [
    "AsyncBaseTransport",
    "AsyncDatagramListener",
    "AsyncDatagramReadTransport",
    "AsyncDatagramTransport",
    "AsyncDatagramWriteTransport",
    "AsyncListener",
    "AsyncStreamReadTransport",
    "AsyncStreamTransport",
    "AsyncStreamWriteTransport",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Callable, Coroutine, Iterable
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, NoReturn, Self, TypeVar

from ... import typed_attr

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

    from ..backend.abc import AsyncBackend, TaskGroup

_T_co = TypeVar("_T_co", covariant=True)
_T_Address = TypeVar("_T_Address")


class AsyncBaseTransport(typed_attr.TypedAttributeProvider, metaclass=ABCMeta):
    """
    Base class for an asynchronous data transport.
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
        """
        Calls :meth:`aclose`.
        """
        await self.aclose()

    @abstractmethod
    async def aclose(self) -> None:
        """
        Closes the transport.

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the transport to close.

            If :meth:`aclose` is cancelled, the transport is closed abruptly.
        """
        raise NotImplementedError

    @abstractmethod
    def is_closing(self) -> bool:
        """
        Checks if the transport is closed or in the process of being closed.

        Returns:
            :data:`True` if the transport is closing.
        """
        raise NotImplementedError

    @abstractmethod
    def backend(self) -> AsyncBackend:
        """
        Returns:
            The backend implementation linked to this transport.
        """
        raise NotImplementedError


class AsyncStreamReadTransport(AsyncBaseTransport):
    """
    An asynchronous continuous stream data reader transport.
    """

    __slots__ = ()

    async def recv(self, bufsize: int) -> bytes:
        """
        Read and return up to `bufsize` bytes.

        Parameters:
            bufsize: the maximum buffer size.

        Raises:
            ValueError: Negative `bufsize`.

        Returns:
            some :class:`bytes`.

            If `bufsize` is greater than zero and an empty byte buffer is returned, this indicates an EOF.
        """
        if bufsize == 0:
            return b""
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")

        with memoryview(bytearray(bufsize)) as buffer:
            nbytes = await self.recv_into(buffer)
            if nbytes < 0:
                raise RuntimeError("transport.recv_into() returned a negative value")
            return bytes(buffer[:nbytes])

    @abstractmethod
    async def recv_into(self, buffer: WriteableBuffer) -> int:
        """
        Read into the given `buffer`.

        Parameters:
            buffer: where to write the received bytes.

        Returns:
            the number of bytes written.

            Returning ``0`` for a non-zero buffer indicates an EOF.
        """
        raise NotImplementedError


class AsyncStreamWriteTransport(AsyncBaseTransport):
    """
    An asynchronous continuous stream data writer transport.
    """

    __slots__ = ()

    @abstractmethod
    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.
        """
        raise NotImplementedError

    async def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
        """
        An efficient way to send a bunch of data via the transport.

        Like :meth:`send_all`, this method continues to send data from bytes until either all data has been sent or an error
        occurs. :data:`None` is returned on success. On error, an exception is raised, and there is no way to determine how much
        data, if any, was successfully sent.

        Parameters:
            iterable_of_data: An :term:`iterable` yielding the bytes to send.
        """

        # By default, all chunks are concatenated and sent once.
        data = b"".join(iterable_of_data)
        del iterable_of_data
        await self.send_all(data)


class AsyncStreamTransport(AsyncStreamWriteTransport, AsyncStreamReadTransport):
    """
    An asynchronous continuous stream data transport.
    """

    __slots__ = ()

    @abstractmethod
    async def send_eof(self) -> None:
        """
        Closes the write end of the stream after the buffered write data is flushed.
        """
        raise NotImplementedError


class AsyncDatagramReadTransport(AsyncBaseTransport):
    """
    An asynchronous reader transport of unreliable packets of data.
    """

    __slots__ = ()

    @abstractmethod
    async def recv(self) -> bytes:
        """
        Read and return the next available packet.

        Returns:
            some :class:`bytes`.
        """
        raise NotImplementedError


class AsyncDatagramWriteTransport(AsyncBaseTransport):
    """
    An asynchronous writer transport of unreliable packets of data.
    """

    __slots__ = ()

    @abstractmethod
    async def send(self, data: bytes | bytearray | memoryview) -> None:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.
        """
        raise NotImplementedError


class AsyncDatagramTransport(AsyncDatagramWriteTransport, AsyncDatagramReadTransport):
    """
    An asynchronous transport of unreliable packets of data.
    """

    __slots__ = ()


class AsyncListener(AsyncBaseTransport, Generic[_T_co]):
    """
    An interface for objects that let you accept incoming connections.
    """

    __slots__ = ()

    @abstractmethod
    async def serve(self, handler: Callable[[_T_co], Coroutine[Any, Any, None]], task_group: TaskGroup | None = None) -> NoReturn:
        """
        Accept incoming connections as they come in and start tasks to handle them.

        Parameters:
            handler: a callable that will be used to handle each accepted connection.
            task_group: the task group that will be used to start tasks for handling each accepted connection.
        """
        raise NotImplementedError


class AsyncDatagramListener(AsyncBaseTransport, Generic[_T_Address]):
    """
    An interface specialized for objects that let you handle incoming datagrams from anywhere.
    """

    __slots__ = ()

    @abstractmethod
    async def serve(
        self,
        handler: Callable[[bytes, _T_Address], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        """
        Receive incoming datagrams as they come in and start tasks to handle them.

        Important:
            The implementation must ensure that datagrams are processed in the order in which they are received.

        Parameters:
            handler: a callable that will be used to handle each received datagram.
            task_group: the task group that will be used to start tasks for handling each received datagram.
        """
        raise NotImplementedError

    @abstractmethod
    async def send_to(self, data: bytes | bytearray | memoryview, address: _T_Address) -> None:
        """
        Send the `data` bytes to the remote peer `address`.

        Important:
            This method should be safe to call from multiple tasks.

        Parameters:
            data: the bytes to send.
            address: the remote peer.
        """
        raise NotImplementedError
