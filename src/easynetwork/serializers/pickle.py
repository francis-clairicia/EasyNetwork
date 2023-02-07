# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""pickle-based network packet serializer module"""

from __future__ import annotations

__all__ = [
    "PickleSerializer",
    "PicklerConfig",
    "UnpicklerConfig",
]

import pickle as _pickle
import pickletools as _pickletools
from dataclasses import asdict as dataclass_asdict, dataclass
from functools import partial
from io import BytesIO
from typing import IO, Callable, TypeVar, final

from .base_stream import FileBasedIncrementalPacketSerializer

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
    __slots__ = ("__optimize", "__pickler_cls", "__unpickler_cls")

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
        self.__pickler_cls: Callable[[IO[bytes]], _pickle.Pickler]
        self.__unpickler_cls: Callable[[IO[bytes]], _pickle.Unpickler]

        if pickler_config is None:
            pickler_config = PicklerConfig()
        elif not isinstance(pickler_config, PicklerConfig):
            raise TypeError(f"Invalid pickler config: expected {PicklerConfig.__name__}, got {type(pickler_config).__name__}")

        if unpickler_config is None:
            unpickler_config = UnpicklerConfig()
        elif not isinstance(unpickler_config, UnpicklerConfig):
            raise TypeError(
                f"Invalid unpickler config: expected {UnpicklerConfig.__name__}, got {type(unpickler_config).__name__}"
            )

        self.__pickler_cls = partial(pickler_cls or _pickle.Pickler, **dataclass_asdict(pickler_config), buffer_callback=None)
        self.__unpickler_cls = partial(unpickler_cls or _pickle.Unpickler, **dataclass_asdict(unpickler_config), buffers=None)

    @final
    def dump_to_file(self, packet: _ST_contra, file: IO[bytes]) -> None:
        if not self.__optimize:
            self.__pickler_cls(file).dump(packet)
            return
        with BytesIO() as buffer:
            self.__pickler_cls(buffer).dump(packet)
            file.write(_pickletools.optimize(buffer.getvalue()))

    @final
    def load_from_file(self, file: IO[bytes]) -> _DT_co:
        return self.__unpickler_cls(file).load()
