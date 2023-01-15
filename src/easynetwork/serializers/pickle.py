# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""pickle-based network packet serializer module"""

from __future__ import annotations

__all__ = [
    "PickleSerializer",
]

from dataclasses import asdict as dataclass_asdict, dataclass
from io import BytesIO
from pickle import DEFAULT_PROTOCOL, STOP as STOP_OPCODE, Pickler, Unpickler, UnpicklingError
from pickletools import optimize as pickletools_optimize
from typing import IO, Any, TypeVar, final

from .stream.abc import FileBasedIncrementalPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


@dataclass(kw_only=True, frozen=True)
class PicklerConfig:
    protocol: int = DEFAULT_PROTOCOL
    fix_imports: bool = False


@dataclass(kw_only=True, frozen=True)
class UnpicklerConfig:
    fix_imports: bool = False
    encoding: str = "utf-8"


class PickleSerializer(FileBasedIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__optimize", "__pickler_cls", "__pickler_conf", "__unpickler_cls", "__unpickler_conf")

    def __init__(
        self,
        pickler: PicklerConfig | None = None,
        unpickler: UnpicklerConfig | None = None,
        *,
        pickler_cls: type[Pickler] | None = None,
        unpickler_cls: type[Unpickler] | None = None,
        optimize: bool = False,
    ) -> None:
        super().__init__(
            unrelated_deserialize_error=(
                UnpicklingError,
                ValueError,
            ),  # pickle.Unpickler does not only raise UnpicklingError... :)
        )
        self.__optimize = bool(optimize)
        self.__pickler_conf: dict[str, Any]
        self.__unpickler_conf: dict[str, Any]

        if pickler is None:
            pickler = PicklerConfig()
        elif not isinstance(pickler, PicklerConfig):
            raise TypeError(f"Invalid pickler config: expected {PicklerConfig.__name__}, got {type(pickler).__name__}")
        self.__pickler_conf = dataclass_asdict(pickler)

        if unpickler is None:
            unpickler = UnpicklerConfig()
        elif not isinstance(unpickler, UnpicklerConfig):
            raise TypeError(f"Invalid unpickler config: expected {UnpicklerConfig.__name__}, got {type(unpickler).__name__}")
        self.__unpickler_conf = dataclass_asdict(unpickler)

        self.__pickler_cls: type[Pickler] = pickler_cls or Pickler
        self.__unpickler_cls: type[Unpickler] = unpickler_cls or Unpickler

    @final
    def _serialize_to_file(self, packet: _ST_contra, file: IO[bytes]) -> None:
        if not self.__optimize:
            self.__pickler_cls(file, **self.__pickler_conf, buffer_callback=None).dump(packet)
            return
        with BytesIO() as buffer:
            self.__pickler_cls(buffer, **self.__pickler_conf, buffer_callback=None).dump(packet)
            file.write(pickletools_optimize(buffer.getvalue()))

    @final
    def _deserialize_from_file(self, file: IO[bytes]) -> _DT_co:
        return self.__unpickler_cls(file, **self.__unpickler_conf, errors="strict", buffers=None).load()

    @final
    def _wait_for_next_chunk(self, given_chunk: bytes) -> bool:
        return STOP_OPCODE not in given_chunk
