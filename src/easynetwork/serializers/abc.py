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
"""Network packet serializer base classes module"""

from __future__ import annotations

__all__ = [
    "AbstractIncrementalPacketSerializer",
    "AbstractPacketSerializer",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Generator
from typing import Generic

from .._typevars import _DTOPacketT
from ..exceptions import DeserializeError


class AbstractPacketSerializer(Generic[_DTOPacketT], metaclass=ABCMeta):
    """
    The base class for implementing a :term:`serializer`.

    Implementing this interface would create a :term:`one-shot serializer`.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def serialize(self, packet: _DTOPacketT, /) -> bytes:
        """
        Returns the byte representation of the Python object `packet`.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        raise NotImplementedError

    @abstractmethod
    def deserialize(self, data: bytes, /) -> _DTOPacketT:
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


class AbstractIncrementalPacketSerializer(AbstractPacketSerializer[_DTOPacketT]):
    """
    The base class for implementing an :term:`incremental serializer`.
    """

    __slots__ = ()

    @abstractmethod
    def incremental_serialize(self, packet: _DTOPacketT, /) -> Generator[bytes, None, None]:
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
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DTOPacketT, bytes]]:
        """
        Creates a Python object representing the raw :term:`packet`.

        Raises:
            IncrementalDeserializeError: An unrelated deserialization error occurred.

        Yields:
            :data:`None` until the whole :term:`packet` has been deserialized.

        Returns:
            a tuple with the deserialized Python object and the unused trailing data.
        """
        raise NotImplementedError

    def serialize(self, packet: _DTOPacketT, /) -> bytes:
        """
        Returns the byte representation of the Python object `packet`.

        The default implementation concatenates and returns the parts sent by :meth:`incremental_serialize`.

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return b"".join(self.incremental_serialize(packet))

    def deserialize(self, data: bytes, /) -> _DTOPacketT:
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
        consumer: Generator[None, bytes, tuple[_DTOPacketT, bytes]] = self.incremental_deserialize()
        try:
            next(consumer)
        except StopIteration:
            raise RuntimeError("self.incremental_deserialize() generator did not yield") from None
        packet: _DTOPacketT
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
