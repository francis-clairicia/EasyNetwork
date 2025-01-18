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
"""Network packet serializer base classes module."""

from __future__ import annotations

__all__ = [
    "AbstractIncrementalPacketSerializer",
    "AbstractPacketSerializer",
    "BufferedIncrementalPacketSerializer",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Generator
from typing import TYPE_CHECKING, Generic

from .._typevars import _T_Buffer, _T_ReceivedDTOPacket, _T_SentDTOPacket
from ..exceptions import DeserializeError

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class AbstractPacketSerializer(Generic[_T_SentDTOPacket, _T_ReceivedDTOPacket], metaclass=ABCMeta):
    """
    The base class for implementing a :term:`serializer`.

    Implementing this interface would create a :term:`one-shot serializer`.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def serialize(self, packet: _T_SentDTOPacket, /) -> bytes:
        """
        Returns the byte representation of the Python object `packet`.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        raise NotImplementedError

    @abstractmethod
    def deserialize(self, data: bytes, /) -> _T_ReceivedDTOPacket:
        """
        Creates a Python object representing the raw :term:`packet` from `data`.

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: An unrelated deserialization error occurred.

        Returns:
            the deserialized Python object.
        """
        raise NotImplementedError


class AbstractIncrementalPacketSerializer(AbstractPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket]):
    """
    The base class for implementing an :term:`incremental serializer`.
    """

    __slots__ = ()

    @abstractmethod
    def incremental_serialize(self, packet: _T_SentDTOPacket, /) -> Generator[bytes]:
        """
        Returns the byte representation of the Python object `packet`.

        The generator should :keyword:`yield` non-empty byte sequences.

        The main purpose of this method is to add metadata that could not be included in the output of :meth:`serialize`,
        such as headers, separators, and so on. It is used in the :meth:`incremental_deserialize` method.

        Parameters:
            packet: The Python object to serialize.

        Yields:
            all the parts of the :term:`packet`.
        """
        raise NotImplementedError

    @abstractmethod
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]]:
        """
        Creates a Python object representing the raw :term:`packet`.

        Raises:
            IncrementalDeserializeError: An unrelated deserialization error occurred.

        Yields:
            :data:`None` until the whole :term:`packet` has been deserialized.

            At each :keyword:`yield` checkpoint, the endpoint implementation sends to the generator the data received
            from the remote endpoint.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.
        """
        raise NotImplementedError

    def serialize(self, packet: _T_SentDTOPacket, /) -> bytes:
        """
        Returns the byte representation of the Python object `packet`.

        The default implementation concatenates and returns the parts sent by :meth:`incremental_serialize`.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return b"".join(self.incremental_serialize(packet))

    def deserialize(self, data: bytes, /) -> _T_ReceivedDTOPacket:
        """
        Creates a Python object representing the raw :term:`packet` from `data`.

        The default implementation uses :meth:`incremental_deserialize` and expects it to deserialize ``data`` at once.

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: Too little or too much data to parse.
            DeserializeError: An unrelated deserialization error occurred.

        Returns:
            the deserialized Python object.
        """
        consumer: Generator[None, bytes, tuple[_T_ReceivedDTOPacket, bytes]] = self.incremental_deserialize()
        try:
            next(consumer)
        except StopIteration:
            raise RuntimeError("self.incremental_deserialize() generator did not yield") from None
        packet: _T_ReceivedDTOPacket
        remaining: bytes
        try:
            consumer.send(data)
        except StopIteration as exc:
            packet, remaining = exc.value
        else:
            consumer.close()
            raise DeserializeError("Missing data to create packet", error_info={"data": data}) from None
        if remaining:
            raise DeserializeError("Extra data caught", error_info={"packet": packet, "extra": remaining})
        return packet


class BufferedIncrementalPacketSerializer(
    AbstractIncrementalPacketSerializer[_T_SentDTOPacket, _T_ReceivedDTOPacket],
    Generic[_T_SentDTOPacket, _T_ReceivedDTOPacket, _T_Buffer],
):
    """
    The base class for implementing an :term:`incremental serializer` with manual control of the receive buffer.
    """

    __slots__ = ()

    @abstractmethod
    def create_deserializer_buffer(self, sizehint: int, /) -> _T_Buffer:
        """
        Called to allocate a new receive buffer.

        Parameters:
            sizehint: the recommended size (in bytes) for the returned buffer.
                      It is acceptable to return smaller or larger buffers than what `sizehint` suggests.

        Returns:
            an object implementing the :ref:`buffer protocol <bufferobjects>`. It is an error to return a buffer with a zero size.
        """
        raise NotImplementedError

    @abstractmethod
    def buffered_incremental_deserialize(
        self,
        buffer: _T_Buffer,
        /,
    ) -> Generator[int | None, int, tuple[_T_ReceivedDTOPacket, ReadableBuffer]]:
        """
        Creates a Python object representing the raw :term:`packet`.

        Parameters:
            buffer: The buffer allocated by :meth:`create_deserializer_buffer`.

        Raises:
            IncrementalDeserializeError: An unrelated deserialization error occurred.

        Yields:
            until the whole :term:`packet` has been deserialized.

            The value yielded is the position to start writing to the buffer. It can be:

            * :data:`None`: Just use the whole buffer. Therefore, ``yield`` and ``yield None`` are equivalent to ``yield 0``.

            * A positive integer (starting at ``0``): Skips the first `n` bytes.

            * A negative integer: Skips until the last `n` bytes.
              For example, ``yield -10`` means to write from the last 10th byte of the buffer.

            At each :keyword:`yield` checkpoint, the endpoint implementation sends to the generator
            the number of bytes written to the `buffer`.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.

            The remainder can be a :class:`memoryview` pointing to `buffer` or an external :term:`bytes-like object`.
        """
        raise NotImplementedError
