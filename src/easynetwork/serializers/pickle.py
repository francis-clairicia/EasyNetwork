# -*- coding: utf-8 -*-
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

from dataclasses import asdict as dataclass_asdict, dataclass, field
from functools import partial
from io import BytesIO
from typing import IO, TYPE_CHECKING, Callable, TypeVar, final

from ..exceptions import DeserializeError
from .abc import AbstractPacketSerializer

if TYPE_CHECKING:
    from pickle import Pickler as _Pickler, Unpickler as _Unpickler

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


def _get_default_pickler_protocol() -> int:
    import pickle

    return pickle.DEFAULT_PROTOCOL


@dataclass(kw_only=True)
class PicklerConfig:
    protocol: int = field(default_factory=_get_default_pickler_protocol)
    fix_imports: bool = False


@dataclass(kw_only=True)
class UnpicklerConfig:
    fix_imports: bool = False
    encoding: str = "utf-8"
    errors: str = "strict"


class PickleSerializer(AbstractPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__optimize", "__pickler_cls", "__unpickler_cls")

    def __init__(
        self,
        pickler_config: PicklerConfig | None = None,
        unpickler_config: UnpicklerConfig | None = None,
        *,
        pickler_cls: type[_Pickler] | None = None,
        unpickler_cls: type[_Unpickler] | None = None,
        optimize: bool = False,
    ) -> None:
        super().__init__()

        import pickle

        self.__optimize: Callable[[bytes], bytes] | None = None
        if optimize:
            import pickletools

            self.__optimize = pickletools.optimize
        self.__pickler_cls: Callable[[IO[bytes]], _Pickler]
        self.__unpickler_cls: Callable[[IO[bytes]], _Unpickler]

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

        self.__pickler_cls = partial(pickler_cls or pickle.Pickler, **dataclass_asdict(pickler_config), buffer_callback=None)
        self.__unpickler_cls = partial(unpickler_cls or pickle.Unpickler, **dataclass_asdict(unpickler_config), buffers=None)

    @final
    def serialize(self, packet: _ST_contra) -> bytes:
        with BytesIO() as buffer:
            self.__pickler_cls(buffer).dump(packet)
            pickle: bytes = buffer.getvalue()
        if (optimize := self.__optimize) is not None:
            pickle = optimize(pickle)
        return pickle

    @final
    def deserialize(self, data: bytes) -> _DT_co:
        with BytesIO(data) as buffer:
            del data
            try:
                packet: _DT_co = self.__unpickler_cls(buffer).load()
            except Exception as exc:
                raise DeserializeError(str(exc) or "Invalid token", error_info={"data": buffer.getvalue()}) from exc
            if extra := buffer.read():  # There is still data after deserialization
                raise DeserializeError("Extra data caught", {"packet": packet, "extra": extra})
        return packet
