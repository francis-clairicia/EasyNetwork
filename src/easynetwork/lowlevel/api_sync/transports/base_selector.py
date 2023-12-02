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
"""Low-level transports module"""

from __future__ import annotations

__all__ = [
    "SelectorBaseTransport",
    "SelectorBufferedStreamReadTransport",
    "SelectorDatagramReadTransport",
    "SelectorDatagramTransport",
    "SelectorDatagramWriteTransport",
    "SelectorStreamReadTransport",
    "SelectorStreamTransport",
    "SelectorStreamWriteTransport",
    "WouldBlockOnRead",
    "WouldBlockOnWrite",
]

import errno as _errno
import math
import selectors
from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from ... import _utils
from . import abc as transports

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

_R = TypeVar("_R")


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
        callback: Callable[[], _R],
        timeout: float,
    ) -> _R:
        timeout = _utils.validate_timeout_delay(timeout, positive_check=True)
        retry_interval = self._retry_interval
        event: int
        fileno: int
        while True:
            try:
                return callback()
            except WouldBlockOnRead as exc:
                event = selectors.EVENT_READ
                fileno = exc.fileno
            except WouldBlockOnWrite as exc:
                event = selectors.EVENT_WRITE
                fileno = exc.fileno
            if timeout <= 0:
                break
            is_retry_interval: bool
            wait_time: float
            if timeout <= retry_interval:
                is_retry_interval = False
                wait_time = timeout
            else:
                is_retry_interval = True
                wait_time = retry_interval
            with self._selector_factory() as selector:
                try:
                    selector.register(fileno, event)
                except ValueError as exc:
                    raise _utils.error_from_errno(_errno.EBADF) from exc
                if wait_time == math.inf:
                    available = bool(selector.select())
                    if not available:
                        raise RuntimeError("timeout error with infinite timeout")
                else:
                    with _utils.ElapsedTime() as elapsed:
                        available = bool(selector.select(wait_time))
                    timeout = elapsed.recompute_timeout(timeout)
                    if not available:
                        if not is_retry_interval:
                            break
        raise _utils.error_from_errno(_errno.ETIMEDOUT)


class SelectorStreamReadTransport(SelectorBaseTransport, transports.StreamReadTransport):
    """
    A continuous stream data reader transport using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()

    @abstractmethod
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
        raise NotImplementedError

    def recv(self, bufsize: int, timeout: float) -> bytes:
        """
        Read and return up to `bufsize` bytes.

        The default implementation will retry to call :meth:`recv_noblock` until it succeeds under the given `timeout`.
        """
        return self._retry(lambda: self.recv_noblock(bufsize), timeout)


class SelectorBufferedStreamReadTransport(SelectorStreamReadTransport, transports.BufferedStreamReadTransport):
    """
    A continuous stream data reader transport using the :mod:`selectors` module for blocking operations polling
    that supports externally allocated buffers.
    """

    __slots__ = ()

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
        return self._retry(lambda: self.recv_noblock_into(buffer), timeout)


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
        return self._retry(lambda: self.send_noblock(data), timeout)


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
        return self._retry(lambda: self.recv_noblock(), timeout)


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
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

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
        return self._retry(lambda: self.send_noblock(data), timeout)


class SelectorDatagramTransport(SelectorDatagramWriteTransport, SelectorDatagramReadTransport, transports.DatagramTransport):
    """
    A transport of unreliable packets of data using the :mod:`selectors` module for blocking operations polling.
    """

    __slots__ = ()
