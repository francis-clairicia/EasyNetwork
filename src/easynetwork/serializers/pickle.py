# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""pickle-based network packet serializer module"""

from __future__ import annotations

__all__ = [
    "PickleSerializer",
]

import pickle as _pickle
import pickletools as _pickletools
from dataclasses import asdict as dataclass_asdict, dataclass
from io import BytesIO
from typing import IO, Any, TypeVar, final

from .stream.abc import FileBasedIncrementalPacketSerializer

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


@dataclass(kw_only=True, frozen=True)
class PicklerConfig:
    protocol: int = _pickle.DEFAULT_PROTOCOL
    fix_imports: bool = False


@dataclass(kw_only=True, frozen=True)
class UnpicklerConfig:
    fix_imports: bool = False
    encoding: str = "utf-8"
    errors: str = "strict"


class PickleSerializer(FileBasedIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__optimize", "__pickler_cls", "__pickler_config", "__unpickler_cls", "__unpickler_config")

    def __init__(
        self,
        pickler_config: PicklerConfig | None = None,
        unpickler_config: UnpicklerConfig | None = None,
        *,
        pickler_cls: type[_pickle.Pickler] | None = None,
        unpickler_cls: type[_pickle.Unpickler] | None = None,
        optimize: bool = False,
    ) -> None:
        super().__init__(
            expected_load_error=(
                _pickle.UnpicklingError,
                ValueError,
            ),  # pickle.Unpickler does not only raise UnpicklingError... :)
        )
        self.__optimize = bool(optimize)
        self.__pickler_config: dict[str, Any]
        self.__unpickler_config: dict[str, Any]

        if pickler_config is None:
            pickler_config = PicklerConfig()
        elif not isinstance(pickler_config, PicklerConfig):
            raise TypeError(f"Invalid pickler config: expected {PicklerConfig.__name__}, got {type(pickler_config).__name__}")
        self.__pickler_config = dataclass_asdict(pickler_config)

        if unpickler_config is None:
            unpickler_config = UnpicklerConfig()
        elif not isinstance(unpickler_config, UnpicklerConfig):
            raise TypeError(
                f"Invalid unpickler config: expected {UnpicklerConfig.__name__}, got {type(unpickler_config).__name__}"
            )
        self.__unpickler_config = dataclass_asdict(unpickler_config)

        self.__pickler_cls: type[_pickle.Pickler] = pickler_cls or _pickle.Pickler
        self.__unpickler_cls: type[_pickle.Unpickler] = unpickler_cls or _pickle.Unpickler

    @final
    def dump_to_file(self, packet: _ST_contra, file: IO[bytes]) -> None:
        if not self.__optimize:
            self.__pickler_cls(file, **self.__pickler_config, buffer_callback=None).dump(packet)
            return
        with BytesIO() as buffer:
            self.__pickler_cls(buffer, **self.__pickler_config, buffer_callback=None).dump(packet)
            file.write(_pickletools.optimize(buffer.getvalue()))

    @final
    def load_from_file(self, file: IO[bytes]) -> _DT_co:
        return self.__unpickler_cls(file, **self.__unpickler_config, buffers=None).load()
