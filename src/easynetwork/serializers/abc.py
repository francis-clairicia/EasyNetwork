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
from typing import Any, Generic

from .._typevars import _DeserializedPacketT_co, _SerializedPacketT_contra
from ..exceptions import DeserializeError


class AbstractPacketSerializer(Generic[_SerializedPacketT_contra, _DeserializedPacketT_co], metaclass=ABCMeta):
    """
    The base class for implementing a :term:`serializer`.

    Implementing this interface would create a :term:`one-shot serializer`.
    """

    __slots__ = ("__weakref__",)

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def serialize(self, packet: _SerializedPacketT_contra, /) -> bytes:
        """
        Returns the byte representation of the Python object `packet`.

        Arguments:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        raise NotImplementedError

    @abstractmethod
    def deserialize(self, data: bytes, /) -> _DeserializedPacketT_co:
        """
        Creates a Python object representing the raw :term:`packet` from `data`.

        Arguments:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: An unrelated deserialization error occurred.

        Returns:
            the deserialized Python object.
        """
        raise NotImplementedError


class AbstractIncrementalPacketSerializer(AbstractPacketSerializer[_SerializedPacketT_contra, _DeserializedPacketT_co]):
    """
    The base class for implementing an :term:`incremental serializer`.
    """

    __slots__ = ()

    @abstractmethod
    def incremental_serialize(self, packet: _SerializedPacketT_contra, /) -> Generator[bytes, None, None]:
        """
        Returns the byte representation of the Python object `packet`.

        The generator should :keyword:`yield` non-empty byte sequences.

        The main purpose of this method is to add metadata that could not be included in the output of :meth:`.serialize`,
        such as headers, separators, and so on. It is used in the :meth:`.incremental_deserialize` method.

        Arguments:
            packet: The Python object to serialize.

        Yields:
            all the parts of the :term:`packet`.
        """
        raise NotImplementedError

    @abstractmethod
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DeserializedPacketT_co, bytes]]:
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

    def serialize(self, packet: _SerializedPacketT_contra, /) -> bytes:
        """
        Returns the byte representation of the Python object `packet`.

        The default implementation concatenates and returns the parts sent by :meth:`.incremental_serialize`.

        Arguments:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return b"".join(self.incremental_serialize(packet))

    def deserialize(self, data: bytes, /) -> _DeserializedPacketT_co:
        """
        Creates a Python object representing the raw :term:`packet` from `data`.

        The default implementation uses :meth:`.incremental_deserialize` and expects it to deserialize ``data`` at once.

        Arguments:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: Too little or too much data to parse.
            DeserializeError: An unrelated deserialization error occurred.

        Returns:
            the deserialized Python object.
        """
        consumer: Generator[None, bytes, tuple[_DeserializedPacketT_co, bytes]] = self.incremental_deserialize()
        try:
            next(consumer)
        except StopIteration:
            raise RuntimeError("self.incremental_deserialize() generator did not yield") from None
        packet: _DeserializedPacketT_co
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
