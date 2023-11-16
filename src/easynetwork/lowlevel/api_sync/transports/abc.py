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
    "DatagramReadTransport",
    "DatagramTransport",
    "DatagramWriteTransport",
    "StreamReadTransport",
    "StreamTransport",
    "StreamWriteTransport",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Iterable

from ... import _utils, typed_attr


class BaseTransport(typed_attr.TypedAttributeProvider, metaclass=ABCMeta):
    """
    Base class for a data transport.
    """

    __slots__ = ("__weakref__",)

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
    A continous stream data reader transport.
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
            TimeoutError: Operation timed out.

        Returns:
            some :class:`bytes`.

            If `bufsize` is greater than zero and an empty byte buffer is returned, this indicates an EOF.
        """
        raise NotImplementedError


class StreamWriteTransport(BaseTransport):
    """
    A continous stream data writer transport.
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
        with memoryview(data) as data:
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

        Currently, the default implementation concatenates the arguments and
        calls :meth:`send_all` on the result.

        Parameters:
            iterable_of_data: An :term:`iterable` yielding the bytes to send.
            timeout: the allowed time (in seconds) for blocking operations. Can be set to :data:`math.inf`.

        Raises:
            ValueError: Negative `timeout`.
            TimeoutError: Operation timed out.
        """
        iterable_of_data = list(iterable_of_data)
        if len(iterable_of_data) == 1:
            data = iterable_of_data[0]
        else:
            data = b"".join(iterable_of_data)
        del iterable_of_data
        return self.send_all(data, timeout)


class StreamTransport(StreamWriteTransport, StreamReadTransport):
    """
    A continous stream data transport.
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
