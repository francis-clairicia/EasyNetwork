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
    "BaseTransport",
    "DatagramTransport",
    "StreamTransport",
]

import time
from abc import ABCMeta, abstractmethod
from collections.abc import Iterable, MutableMapping
from typing import Any


class BaseTransport(metaclass=ABCMeta):
    """
    Base class for a data transport.
    """

    __slots__ = ("_extra", "__weakref__")

    def __init__(self, extra: MutableMapping[str, Any] | None = None):
        if extra is None:
            extra = {}
        self._extra: MutableMapping[str, Any] = extra

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

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        """
        Returns information about the transport or underlying resources it uses.

        Parameters:
            name: a string representing the piece of transport-specific information to get.
            default: the value to return if the information is not available, or if the transport does not support querying it
                     on the current platform.

        Categories of information that can be queried on some transports:
        * socket:

            * ``'peername'``: the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`
              (:data:`None` on error)

            * ``'socket'``: :class:`socket.socket` instance

            * ``'sockname'``: the socket's own address, result of :meth:`socket.socket.getsockname`

        * SSL socket:

            * ``'compression'``: the compression algorithm being used as a string, or None if the connection isn't compressed;
              result of :meth:`ssl.SSLSocket.compression`

            * ``'cipher'``: a three-value tuple containing the name of the cipher being used, the version of the SSL protocol
              that defines its use, and the number of secret bits being used; result of :meth:`ssl.SSLSocket.cipher`

            * ``'peercert'``: peer certificate; result of :meth:`ssl.SSLSocket.getpeercert`

            * ``'sslcontext'``: :class:`ssl.SSLContext` instance
        """
        return self._extra.get(name, default)


class StreamTransport(BaseTransport):
    """
    A continous stream data transport.
    """

    __slots__ = ()

    @abstractmethod
    def recv(self, bufsize: int, timeout: float) -> bytes:
        """
        Read and return up to `bufsize` bytes.

        Parameters:
            bufsize: the maximum buffer size.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `bufsize`.
            ValueError: Negative `timeout`.

        Returns:
            some :class:`bytes`.

            If `bufsize` is greater than zero and an empty byte buffer is returned, this indicates an EOF.
        """
        raise NotImplementedError

    @abstractmethod
    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> int:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.

        Returns:
            the number of sent bytes.
        """
        raise NotImplementedError

    @abstractmethod
    def send_eof(self) -> None:
        """
        Closes the write end of the stream after the buffered write data is flushed.
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
        """

        perf_counter = time.perf_counter  # pull function to local namespace
        total_sent: int = 0
        with memoryview(data) as data:
            nb_bytes_to_send = len(data)
            if nb_bytes_to_send == 0:
                self.send(data, timeout)
                return
            while total_sent < nb_bytes_to_send:
                with data[total_sent:] as buffer:
                    _start = perf_counter()
                    sent: int = self.send(buffer, timeout)
                    _end = perf_counter()
                if sent < 0:
                    raise RuntimeError("transport.send() returned a negative value")
                total_sent += sent
                elapsed = _end - _start
                if elapsed >= timeout:
                    timeout = 0.0
                else:
                    timeout -= elapsed

    def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview], timeout: float) -> None:
        """
        An efficient way to send a bunch of data via the transport.

        Currently, the default implementation concatenates the arguments and
        calls :meth:`send_all` on the result.

        Parameters:
            iterable_of_data: An :term:`iterable` yielding the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.
        """
        data = b"".join(iterable_of_data)
        return self.send_all(data, timeout)


class DatagramTransport(BaseTransport):
    """
    A transport of unreliable packets of data.
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

        Returns:
            some :class:`bytes`.
        """
        raise NotImplementedError

    @abstractmethod
    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        """
        Send the `data` bytes to the remote peer.

        Parameters:
            data: the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
        """
        raise NotImplementedError
