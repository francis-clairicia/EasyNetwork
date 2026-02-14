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
""":mod:`selectors` transports module.

Here are abstract base classes which use :mod:`selectors` module to perform I/O polling.

See Also:

    :external+python:doc:`library/selectors`
        High-level interface for I/O polling
"""

from __future__ import annotations

__all__ = [
    "SelectorBaseTransport",
    "SelectorDatagramListener",
    "SelectorDatagramReadTransport",
    "SelectorDatagramTransport",
    "SelectorDatagramWriteTransport",
    "SelectorListener",
    "SelectorStreamReadTransport",
    "SelectorStreamTransport",
    "SelectorStreamWriteTransport",
    "WouldBlockOnRead",
    "WouldBlockOnWrite",
]

import concurrent.futures
import errno as _errno
import math
import selectors
import time
from abc import abstractmethod
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from ... import _utils
from . import abc as transports

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

_T_co = TypeVar("_T_co", covariant=True)
_T_Address = TypeVar("_T_Address")
_T_Return = TypeVar("_T_Return")


class WouldBlockOnRead(Exception):
    """The operation would block when reading the pipe."""

    def __init__(self, fileno: int) -> None:
        super().__init__(fileno)

        self.fileno: int = fileno
        """The file descriptor to wait for."""


class WouldBlockOnWrite(Exception):
    """The operation would block when writing on the pipe."""

    def __init__(self, fileno: int) -> None:
        super().__init__(fileno)

        self.fileno: int = fileno
        """The file descriptor to wait for."""


class SelectorBaseTransport(transports.BaseTransport):
    """
    Base class for transports using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = (
        "_retry_interval",
        "_selector_factory",
    )

    def __init__(self, retry_interval: float, selector_factory: Callable[[], selectors.BaseSelector] | None = None) -> None:
        """
        Parameters:
            retry_interval: The maximum wait time to wait for a blocking operation before retrying.
                            Set it to :data:`math.inf` to disable this feature.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
                              Otherwise, the selector used by default is:

                              * :class:`selectors.PollSelector` on Unix platforms.

                              * :class:`selectors.SelectSelector` on Windows.
        """
        super().__init__()

        if selector_factory is None:
            selector_factory = getattr(selectors, "PollSelector", selectors.SelectSelector)
        self._selector_factory: Callable[[], selectors.BaseSelector] = selector_factory

        self._retry_interval: float = _utils.validate_timeout_delay(retry_interval, positive_check=False)
        if self._retry_interval <= 0:
            raise ValueError("retry_interval must be a strictly positive float")

    def _retry(
        self,
        callback: Callable[[], _T_Return],
        timeout: float,
    ) -> tuple[_T_Return, float]:
        """
        Calls `callback` without argument and returns the output.

        If the callable raises :class:`WouldBlockOnRead` or :class:`WouldBlockOnWrite`, waits for
        :attr:`~.WouldBlockOnRead.fileno` to be available for reading or writing respectively, and retries to call the callback.

        Parameters:
            callback: the function to call.
            timeout: the maximum amount of seconds to wait for the file descriptor to be available.

        Raises:
            TimeoutError: timed out

        Returns:
            a tuple with the result of the callback and the timeout which is deduced from the waited time.

        :meta public:
        """
        timeout = _utils.validate_timeout_delay(timeout, positive_check=True)
        event: int
        fileno: int
        available: bool = True
        while available:
            try:
                return callback(), timeout
            except WouldBlockOnRead as exc:
                event = selectors.EVENT_READ
                fileno = exc.fileno
            except WouldBlockOnWrite as exc:
                event = selectors.EVENT_WRITE
                fileno = exc.fileno
            available, timeout = _wait_for_fd(self, {fileno: event}, timeout)
        raise _utils.error_from_errno(_errno.ETIMEDOUT)


class SelectorStreamReadTransport(SelectorBaseTransport, transports.StreamReadTransport):
    """
    A continuous stream data reader transport using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()

    def recv_noblock(self, bufsize: int) -> bytes:
        """
        Read and return up to `bufsize` bytes.

        Parameters:
            bufsize: the maximum buffer size.

        Raises:
            ValueError: Negative `bufsize`.
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.

        Returns:
            some :class:`bytes`.

            If `bufsize` is greater than zero and an empty byte buffer is returned, this indicates an EOF.
        """
        if bufsize == 0:
            return b""
        if bufsize < 0:
            raise ValueError("'bufsize' must be a positive or null integer")

        with memoryview(bytearray(bufsize)) as buffer:
            nbytes = self.recv_noblock_into(buffer)
            if nbytes < 0:
                raise RuntimeError("transport.recv_noblock_into() returned a negative value")
            return bytes(buffer[:nbytes])

    def recv(self, bufsize: int, timeout: float) -> bytes:
        """
        Read and return up to `bufsize` bytes.

        The default implementation will retry to call :meth:`recv_noblock` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.recv_noblock(bufsize), timeout)[0]

    @abstractmethod
    def recv_noblock_into(self, buffer: WriteableBuffer) -> int:
        """
        Read into the given `buffer`.

        Parameters:
            buffer: where to write the received bytes.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.

        Returns:
            the number of bytes written.

            Returning ``0`` for a non-zero buffer indicates an EOF.
        """
        raise NotImplementedError

    def recv_into(self, buffer: WriteableBuffer, timeout: float) -> int:
        """
        Read into the given `buffer`.

        The default implementation will retry to call :meth:`recv_noblock_into` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.recv_noblock_into(buffer), timeout)[0]

    def recv_noblock_with_ancillary(self, bufsize: int, ancillary_bufsize: int) -> tuple[bytes, Any]:  # pragma: no cover
        """
        Read and return up to `bufsize` bytes with ancillary data.

        .. versionadded:: 1.2

        Parameters:
            bufsize: the maximum buffer size.
            ancillary_bufsize: the maximum buffer size for ancillary data.

        Raises:
            ValueError: Negative `bufsize`.
            ValueError: Negative `ancillary_bufsize`.
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
            UnsupportedOperation: This transport does not have ancillary data support.

        Returns:
            a tuple with some :class:`bytes` and the ancillary data.

            If `bufsize` is greater than zero and an empty byte buffer is returned, this indicates an EOF.
        """
        from ....exceptions import UnsupportedOperation

        raise UnsupportedOperation("This transport does not have ancillary data support.")

    def recv_with_ancillary(self, bufsize: int, ancillary_bufsize: int, timeout: float) -> tuple[bytes, Any]:
        """
        Read and return up to `bufsize` bytes with ancillary data.

        The default implementation will retry to call :meth:`recv_noblock_with_ancillary` until it succeeds
        under the given `timeout`.

        .. versionadded:: 1.2
        """
        return self._retry(lambda: self.recv_noblock_with_ancillary(bufsize, ancillary_bufsize), timeout)[0]

    def recv_noblock_with_ancillary_into(
        self,
        buffer: WriteableBuffer,
        ancillary_bufsize: int,
    ) -> tuple[int, Any]:  # pragma: no cover
        """
        Read into the given `buffer` with ancillary data.

        .. versionadded:: 1.2

        Parameters:
            buffer: where to write the received bytes.
            ancillary_bufsize: the maximum buffer size for ancillary data.

        Raises:
            ValueError: Negative `ancillary_bufsize`.
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
            UnsupportedOperation: This transport does not have ancillary data support.

        Returns:
            a tuple with the number of bytes written and the ancillary data.

            Returning ``0`` for a non-zero buffer indicates an EOF.
        """
        from ....exceptions import UnsupportedOperation

        raise UnsupportedOperation("This transport does not have ancillary data support.")

    def recv_with_ancillary_into(self, buffer: WriteableBuffer, ancillary_bufsize: int, timeout: float) -> tuple[int, Any]:
        """
        Read into the given `buffer` with ancillary data.

        The default implementation will retry to call :meth:`recv_noblock_with_ancillary` until it succeeds
        under the given `timeout`.

        .. versionadded:: 1.2
        """
        return self._retry(lambda: self.recv_noblock_with_ancillary_into(buffer, ancillary_bufsize), timeout)[0]


class SelectorStreamWriteTransport(SelectorBaseTransport, transports.StreamWriteTransport):
    """
    A continuous stream data writer transport using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()

    @abstractmethod
    def send_noblock(self, data: bytes | bytearray | memoryview) -> int:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
        """
        raise NotImplementedError

    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> int:
        """
        Send the `data` bytes to the remote peer.

        The default implementation will retry to call :meth:`send_noblock` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.send_noblock(data), timeout)[0]

    def send_all_noblock_with_ancillary(
        self,
        iterable_of_data: Iterable[bytes | bytearray | memoryview],
        ancillary_data: Any,
    ) -> None:  # pragma: no cover
        """
        An efficient way to send a bunch of data via the transport with ancillary data.

        .. versionadded:: 1.2

        Parameters:
            iterable_of_data: An :term:`iterable` yielding the bytes to send.
            ancillary_data: The ancillary data to send along with the message.

        Raises:
            OSError: Data too big to be sent at once.
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
            UnsupportedOperation: This transport does not have ancillary data support.
        """
        from ....exceptions import UnsupportedOperation

        raise UnsupportedOperation("This transport does not have ancillary data support.")

    def send_all_with_ancillary(
        self,
        iterable_of_data: Iterable[bytes | bytearray | memoryview],
        ancillary_data: Any,
        timeout: float,
    ) -> None:
        """
        An efficient way to send a bunch of data via the transport with ancillary data.

        The default implementation will retry to call :meth:`send_all_noblock_with_ancillary` until it succeeds
        under the given `timeout`.

        .. versionadded:: 1.2
        """
        if hasattr(iterable_of_data, "__next__"):
            # Do not send the iterator directly because if sendmsg() blocks,
            # it would retry with an already consumed iterator.
            iterable_of_data = list(iterable_of_data)
        return self._retry(lambda: self.send_all_noblock_with_ancillary(iterable_of_data, ancillary_data), timeout)[0]


class SelectorStreamTransport(SelectorStreamWriteTransport, SelectorStreamReadTransport, transports.StreamTransport):
    """
    A continuous stream data transport using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()


class SelectorDatagramReadTransport(SelectorBaseTransport, transports.DatagramReadTransport):
    """
    A reader transport of unreliable packets of data using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()

    @abstractmethod
    def recv_noblock(self) -> bytes:
        """
        Read and return the next available packet.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.

        Returns:
            some :class:`bytes`.
        """
        raise NotImplementedError

    def recv(self, timeout: float) -> bytes:
        """
        Read and return the next available packet.

        The default implementation will retry to call :meth:`recv_noblock` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.recv_noblock(), timeout)[0]

    def recv_noblock_with_ancillary(self, ancillary_bufsize: int) -> tuple[bytes, Any]:  # pragma: no cover
        """
        Read and return the next available packet with ancillary data.

        .. versionadded:: 1.2

        Parameters:
            ancillary_bufsize: the maximum buffer size for ancillary data.

        Raises:
            ValueError: Negative `ancillary_bufsize`.
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
            UnsupportedOperation: This transport does not have ancillary data support.

        Returns:
            a tuple with some :class:`bytes` and the ancillary data.
        """
        from ....exceptions import UnsupportedOperation

        raise UnsupportedOperation("This transport does not have ancillary data support.")

    def recv_with_ancillary(self, ancillary_bufsize: int, timeout: float) -> tuple[bytes, Any]:
        """
        Read and return the next available packet with ancillary data.

        The default implementation will retry to call :meth:`recv_noblock_with_ancillary` until it succeeds
        under the given `timeout`.

        .. versionadded:: 1.2
        """
        return self._retry(lambda: self.recv_noblock_with_ancillary(ancillary_bufsize), timeout)[0]


class SelectorDatagramWriteTransport(SelectorBaseTransport, transports.DatagramWriteTransport):
    """
    A writer transport of unreliable packets of data using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()

    @abstractmethod
    def send_noblock(self, data: bytes | bytearray | memoryview) -> None:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
        """
        raise NotImplementedError

    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        """
        Send the `data` bytes to the remote peer.

        The default implementation will retry to call :meth:`send_noblock` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.send_noblock(data), timeout)[0]

    def send_noblock_with_ancillary(self, data: bytes | bytearray | memoryview, ancillary_data: Any) -> None:  # pragma: no cover
        """
        Send the `data` bytes with ancillary data to the remote peer.

        .. versionadded:: 1.2

        Parameters:
            data: the bytes to send.
            ancillary_data: The ancillary data to send along with the message.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
            UnsupportedOperation: This transport does not have ancillary data support.
        """
        from ....exceptions import UnsupportedOperation

        raise UnsupportedOperation("This transport does not have ancillary data support.")

    def send_with_ancillary(self, data: bytes | bytearray | memoryview, ancillary_data: Any, timeout: float) -> None:
        """
        Send the `data` bytes with ancillary data to the remote peer.

        The default implementation will retry to call :meth:`send_noblock_with_ancillary` until it succeeds
        under the given `timeout`.

        .. versionadded:: 1.2
        """
        return self._retry(lambda: self.send_noblock_with_ancillary(data, ancillary_data), timeout)[0]


class SelectorDatagramTransport(SelectorDatagramWriteTransport, SelectorDatagramReadTransport, transports.DatagramTransport):
    """
    A transport of unreliable packets of data using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()


class SelectorListener(SelectorBaseTransport, transports.Listener[_T_co]):
    """
    An interface for objects that let you accept incoming connections
    using the :mod:`selectors` module for blocking operations polling.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = ()

    @abstractmethod
    def accept_noblock(
        self,
        handler: Callable[[_T_co], _T_Return],
        executor: concurrent.futures.Executor,
    ) -> concurrent.futures.Future[_T_Return]:
        """
        Accept incoming connections as they come in and start tasks to handle them.

        Parameters:
            handler: a callable that will be used to handle accepted connection.
            executor: will be used to start task for handling accepted connection.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
            OutOfResourcesError: Resource limits exceeded.

        Returns:
            a :class:`~concurrent.futures.Future` for the spawned task.
        """
        raise NotImplementedError

    def accept(
        self,
        handler: Callable[[_T_co], _T_Return],
        executor: concurrent.futures.Executor,
        timeout: float,
    ) -> concurrent.futures.Future[_T_Return]:
        """
        Accept incoming connections as they come in and start tasks to handle them.

        The default implementation will retry to call :meth:`accept_noblock` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.accept_noblock(handler, executor), timeout)[0]


class SelectorDatagramListener(SelectorBaseTransport, transports.DatagramListener[_T_Address]):
    """
    An interface specialized for objects that let you handle incoming datagrams from anywhere
    using the :mod:`selectors` module for blocking operations polling.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = ()

    @abstractmethod
    def recv_noblock_from(self) -> tuple[bytes, _T_Address]:
        """
        Read and return the next available packet.

        Important:
            The implementation must ensure that datagrams are processed in the order in which they are received.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
            OutOfResourcesError: Resource limits exceeded.

        Returns:
            a tuple with some :class:`bytes` and the sender's address.
        """
        raise NotImplementedError

    def recv_from(self, timeout: float) -> tuple[bytes, _T_Address]:
        """
        Read and return the next available packet.

        The default implementation will retry to call :meth:`recv_noblock_from` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.recv_noblock_from(), timeout)[0]

    @abstractmethod
    def send_noblock_to(self, data: bytes | bytearray | memoryview, address: _T_Address) -> None:
        """
        Send the `data` bytes to the remote peer `address`.

        Parameters:
            data: the bytes to send.
            address: the remote peer.

        Raises:
            WouldBlockOnRead: the operation would block when reading the pipe.
            WouldBlockOnWrite: the operation would block when writing on the pipe.
        """
        raise NotImplementedError

    def send_to(self, data: bytes | bytearray | memoryview, address: _T_Address, timeout: float) -> None:
        """
        Send the `data` bytes to the remote peer `address`.

        The default implementation will retry to call :meth:`send_noblock_to` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.send_noblock_to(data, address), timeout)[0]


def _wait_for_fd(transport: SelectorBaseTransport, fds: Mapping[int, int], timeout: float) -> tuple[bool, float]:
    if timeout <= 0:
        return False, 0.0
    is_retry_interval: bool
    wait_time: float
    if timeout > (retry_interval := transport._retry_interval):
        is_retry_interval = True
        wait_time = retry_interval
    else:
        is_retry_interval = False
        wait_time = timeout
    with transport._selector_factory() as selector:
        try:
            for fileno, events in fds.items():
                selector.register(fileno, events)
        except ValueError as exc:
            raise _utils.error_from_errno(_errno.EBADF) from exc
        if wait_time == math.inf:
            available = bool(selector.select())
            if not available:
                raise RuntimeError("timeout error with infinite timeout")
        else:
            deadline: float = time.perf_counter() + timeout
            _ready_fds = selector.select(wait_time)
            timeout = max(deadline - time.perf_counter(), 0.0)
            available = bool(_ready_fds) or is_retry_interval
        return available, timeout
