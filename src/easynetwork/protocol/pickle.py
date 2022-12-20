# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
"""pickle-based network packet protocol module"""

from __future__ import annotations

__all__ = [
    "PickleNetworkProtocol",
]

from io import BytesIO
from pickle import DEFAULT_PROTOCOL, Pickler, Unpickler
from pickletools import optimize as pickletools_optimize
from typing import TYPE_CHECKING, Generator, TypeVar, final

if TYPE_CHECKING:
    from pickle import _WritableFileobj, _ReadableFileobj

from .._utils.abc import concreteclass
from .exceptions import DeserializeError
from .stream.abc import StreamNetworkProtocol
from .stream.exceptions import IncrementalDeserializeError

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


@concreteclass
class PickleNetworkProtocol(StreamNetworkProtocol[_ST_contra, _DT_co]):
    __slots__ = ()

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        buffer = BytesIO()
        pickler = self.get_pickler(buffer)
        assert isinstance(pickler, Pickler)
        pickler.dump(packet)
        return pickletools_optimize(buffer.getvalue())

    @final
    def incremental_serialize(self, packet: _ST_contra) -> Generator[bytes, None, None]:
        yield self.serialize(packet)  # 'incremental' :)

    def get_pickler(self, buffer: _WritableFileobj) -> Pickler:
        return Pickler(buffer, protocol=DEFAULT_PROTOCOL, fix_imports=False, buffer_callback=None)

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        if not data:
            raise DeserializeError("Empty bytes")
        buffer = BytesIO(data)
        unpickler = self.get_unpickler(buffer)
        assert isinstance(unpickler, Unpickler)
        try:
            packet: _DT_co = unpickler.load()
        except EOFError as exc:
            raise DeserializeError("Missing data to create packet") from exc
        except Exception as exc:  # pickle.Unpickler does not only raise UnpicklingError... :)
            raise DeserializeError(f"Unpickling error: {exc}") from exc
        if buffer.read():  # There is still data after pickling
            raise DeserializeError("Extra data caught")
        return packet

    @final
    def incremental_deserialize(self) -> Generator[None, bytes, tuple[_DT_co, bytes]]:
        data = BytesIO()

        while True:
            while not (chunk := (yield)):  # Skip empty bytes
                continue
            data.write(chunk)
            data.seek(0)
            unpickler = self.get_unpickler(data)
            assert isinstance(unpickler, Unpickler)
            try:
                packet: _DT_co = unpickler.load()
            except EOFError:
                continue
            except Exception as exc:  # pickle.Unpickler does not only raise UnpicklingError... :)
                remaining_data: bytes = data.read()
                if not remaining_data:  # Possibly an EOF error, give it a chance
                    continue
                raise IncrementalDeserializeError(
                    f"Unpickling error: {exc}",
                    remaining_data=remaining_data,
                ) from exc
            else:
                return (packet, data.read())

    def get_unpickler(self, buffer: _ReadableFileobj) -> Unpickler:
        return Unpickler(buffer, fix_imports=False, encoding="utf-8", errors="strict", buffers=None)
