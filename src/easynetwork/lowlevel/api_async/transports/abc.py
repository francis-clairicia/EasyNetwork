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
"""Low-level asynchronous transports module"""

from __future__ import annotations

__all__ = [
    "AsyncBaseTransport",
    "AsyncDatagramReadTransport",
    "AsyncDatagramTransport",
    "AsyncDatagramWriteTransport",
    "AsyncStreamReadTransport",
    "AsyncStreamTransport",
    "AsyncStreamWriteTransport",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Iterable

from ... import typed_attr


class AsyncBaseTransport(typed_attr.TypedAttributeProvider, metaclass=ABCMeta):
    """
    Base class for an asynchronous data transport.
    """

    __slots__ = ("__weakref__",)

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


class AsyncStreamReadTransport(AsyncBaseTransport):
    """
    An asynchronous continous stream data reader transport.
    """

    __slots__ = ()

    @abstractmethod
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
        raise NotImplementedError


class AsyncStreamWriteTransport(AsyncBaseTransport):
    """
    An asynchronous continous stream data writer transport.
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

        Currently, the default implementation concatenates the arguments and
        calls :meth:`send_all` on the result.

        Parameters:
            iterable_of_data: An :term:`iterable` yielding the bytes to send.
        """
        data = b"".join(iterable_of_data)
        del iterable_of_data
        return await self.send_all(data)


class AsyncStreamTransport(AsyncStreamWriteTransport, AsyncStreamReadTransport):
    """
    An asynchronous continous stream data transport.
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
