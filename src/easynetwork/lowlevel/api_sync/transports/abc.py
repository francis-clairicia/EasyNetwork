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
"""Low-level transports interfaces module."""

from __future__ import annotations

__all__ = [
    "BaseTransport",
    "DatagramListener",
    "DatagramReadTransport",
    "DatagramTransport",
    "DatagramWriteTransport",
    "Listener",
    "StreamReadTransport",
    "StreamTransport",
    "StreamWriteTransport",
]

import concurrent.futures
from abc import ABCMeta, abstractmethod
from collections.abc import Callable, Iterable
from types import TracebackType
from typing import TYPE_CHECKING, Generic, Self, TypeVar

from ... import _utils, typed_attr

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

_T_co = TypeVar("_T_co", covariant=True)
_T_Address = TypeVar("_T_Address")
_T_Return = TypeVar("_T_Return")


class BaseTransport(typed_attr.TypedAttributeProvider, metaclass=ABCMeta):
    """
    Base class for a data transport.
    """

    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        """
        Calls :meth:`close`.
        """
        self.close()

    def abort(self) -> None:
        """
        Abruptly closes the transport.

        .. versionadded:: NEXT_VERSION
        """
        self.close()

    @abstractmethod
    def close(self) -> None:
        """
        Closes the transport.
        """
        raise NotImplementedError

    @abstractmethod
    def is_closed(self) -> bool:
        """
        Checks if :meth:`close` has been called.

        Returns:
            :data:`True` if the transport is closed.
        """
        raise NotImplementedError


class StreamReadTransport(BaseTransport):
    """
    A continuous stream data reader transport.
    """

    __slots__ = ()

    def recv(self, bufsize: int, timeout: float) -> bytes:
        """
        Read and return up to `bufsize` bytes.

        Parameters:
            bufsize: the maximum buffer size.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `bufsize`.
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.

        Returns:
            some :class:`bytes`.

            If `bufsize` is greater than zero and an empty byte buffer is returned, this indicates an EOF.
        """
        if bufsize == 0:
            return b""
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")

        with memoryview(bytearray(bufsize)) as buffer:
            nbytes = self.recv_into(buffer, timeout)
            if nbytes < 0:
                raise RuntimeError("transport.recv_into() returned a negative value")
            return bytes(buffer[:nbytes])

    @abstractmethod
    def recv_into(self, buffer: WriteableBuffer, timeout: float) -> int:
        """
        Read into the given `buffer`.

        Parameters:
            buffer: where to write the received bytes.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.

        Returns:
            the number of bytes written.

            Returning ``0`` for a non-zero buffer indicates an EOF.
        """
        raise NotImplementedError


class StreamWriteTransport(BaseTransport):
    """
    A continuous stream data writer transport.
    """

    __slots__ = ()

    @abstractmethod
    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> int:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.

        Returns:
            the number of sent bytes.
        """
        raise NotImplementedError

    def send_all(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        """
        Send the `data` bytes to the remote peer.

        Unlike :meth:`send`, this method continues to send data from bytes until either all data has been sent or an error occurs.
        :data:`None` is returned on success. On error, an exception is raised, and there is no way to determine how much data,
        if any, was successfully sent.

        Parameters:
            data: the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.
        """

        total_sent: int = 0
        with (
            memoryview(data) as data,
            data.cast("B") if data.itemsize != 1 else data as data,
        ):
            nb_bytes_to_send = len(data)
            if nb_bytes_to_send == 0:
                sent = self.send(data, timeout)
                if sent < 0:
                    raise RuntimeError("transport.send() returned a negative value")
                return
            while total_sent < nb_bytes_to_send:
                with data[total_sent:] as buffer, _utils.ElapsedTime() as elapsed:
                    sent = self.send(buffer, timeout)
                if sent < 0:
                    raise RuntimeError("transport.send() returned a negative value")
                total_sent += sent
                timeout = elapsed.recompute_timeout(timeout)

    def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview], timeout: float) -> None:
        """
        An efficient way to send a bunch of data via the transport.

        Like :meth:`send_all`, this method continues to send data from bytes until either all data has been sent or an error
        occurs. :data:`None` is returned on success. On error, an exception is raised, and there is no way to determine how much
        data, if any, was successfully sent.

        Parameters:
            iterable_of_data: An :term:`iterable` yielding the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.
        """

        # By default, all chunks are concatenated and sent once.
        data = b"".join(iterable_of_data)
        del iterable_of_data
        self.send_all(data, timeout)


class StreamTransport(StreamWriteTransport, StreamReadTransport):
    """
    A continuous stream data transport.
    """

    __slots__ = ()

    @abstractmethod
    def send_eof(self) -> None:
        """
        Closes the write end of the stream after the buffered write data is flushed.

        This method does nothing if the transport is closed.
        """
        raise NotImplementedError


class DatagramReadTransport(BaseTransport):
    """
    A reader transport of unreliable packets of data.
    """

    __slots__ = ()

    @abstractmethod
    def recv(self, timeout: float) -> bytes:
        """
        Read and return the next available packet.

        Parameters:
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.

        Returns:
            some :class:`bytes`.
        """
        raise NotImplementedError


class DatagramWriteTransport(BaseTransport):
    """
    A writer transport of unreliable packets of data.
    """

    __slots__ = ()

    @abstractmethod
    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.
        """
        raise NotImplementedError


class DatagramTransport(DatagramWriteTransport, DatagramReadTransport):
    """
    A transport of unreliable packets of data.
    """

    __slots__ = ()


class Listener(BaseTransport, Generic[_T_co]):
    """
    An interface for objects that let you accept incoming connections.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = ()

    @abstractmethod
    def accept(
        self,
        handler: Callable[[_T_co], _T_Return],
        executor: concurrent.futures.Executor,
        timeout: float,
    ) -> concurrent.futures.Future[_T_Return]:
        """
        Accept incoming connections as they come in and start tasks to handle them.

        Parameters:
            handler: a callable that will be used to handle accepted connection.
            executor: will be used to start task for handling accepted connection.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.

        Returns:
            a :class:`~concurrent.futures.Future` for the spawned task.
        """
        raise NotImplementedError

    def is_accept_capacity_error(self, exc: Exception) -> bool:
        """
        Checks whether an error raised by :meth:`accept` is due to a capacity error or not.

        Parameters:
            exc: error raised by :meth:`accept`.

        Returns:
            :data:`True` if the exception is the result of a capacity error.
        """
        return False

    def accept_capacity_error_sleep_time(self) -> float:
        """
        Returns:
            the time (in seconds) to wait before calling :meth:`accept` if there were a capacity error.
        """
        return 0.0


class DatagramListener(BaseTransport, Generic[_T_Address]):
    """
    An interface specialized for objects that let you handle incoming datagrams from anywhere.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = ()

    @abstractmethod
    def recv_from(
        self,
        handler: Callable[[bytes, _T_Address], _T_Return],
        executor: concurrent.futures.Executor,
        timeout: float,
    ) -> concurrent.futures.Future[_T_Return]:
        """
        Receive incoming datagrams as they come in and start tasks to handle them.

        Important:
            The implementation must ensure that datagrams are processed in the order in which they are received.

        Parameters:
            handler: a callable that will be used to handle received datagram.
            executor: will be used to start task for handling accepted datagram.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.

        Returns:
            a :class:`~concurrent.futures.Future` for the spawned task.
        """
        raise NotImplementedError

    @abstractmethod
    def send_to(self, data: bytes | bytearray | memoryview, address: _T_Address, timeout: float) -> None:
        """
        Send the `data` bytes to the remote peer `address`.

        Parameters:
            data: the bytes to send.
            address: the remote peer.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.
        """
        raise NotImplementedError
