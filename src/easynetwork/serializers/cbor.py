# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""cbor-based network packet serializer module"""

from __future__ import annotations

__all__ = [
    "CBORDecoderConfig",
    "CBOREncoderConfig",
    "CBORSerializer",
]

from dataclasses import asdict as dataclass_asdict, dataclass
from typing import IO, TYPE_CHECKING, Any, Callable, Literal, TypeVar, final

from .stream.abc import FileBasedIncrementalPacketSerializer

if TYPE_CHECKING:
    import datetime

_ST_contra = TypeVar("_ST_contra", contravariant=True, bound=list[Any] | dict[str, Any])
_DT_co = TypeVar("_DT_co", covariant=True, bound=list[Any] | dict[str, Any])


@dataclass(kw_only=True, frozen=True)
class CBOREncoderConfig:
    datetime_as_timestamp: bool = False
    timezone: datetime.tzinfo | None = None
    value_sharing: bool = False
    default: Callable[..., Any] | None = None
    canonical: bool = False
    date_as_datetime: bool = False
    string_referencing: bool = False


@dataclass(kw_only=True, frozen=True)
class CBORDecoderConfig:
    object_hook: Callable[..., Any] | None = None
    tag_hook: Callable[..., Any] | None = None
    str_errors: Literal["strict", "error", "replace"] = "strict"


class CBORSerializer(FileBasedIncrementalPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__e", "__d")

    def __init__(self, *, encoder: CBOREncoderConfig | None = None, decoder: CBORDecoderConfig | None = None) -> None:
        try:
            import cbor2
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError("cbor dependencies are missing. Consider adding 'cbor' extra") from exc

        super().__init__(
            unrelated_deserialize_error=cbor2.CBORDecodeError,
        )
        self.__e: dict[str, Any]
        self.__d: dict[str, Any]

        if encoder is None:
            encoder = CBOREncoderConfig()
        elif not isinstance(encoder, CBOREncoderConfig):
            raise TypeError(f"Invalid encoder: expected {CBOREncoderConfig.__name__}, got {type(encoder).__name__}")
        self.__e = dataclass_asdict(encoder)

        if decoder is None:
            decoder = CBORDecoderConfig()
        elif not isinstance(decoder, CBORDecoderConfig):
            raise TypeError(f"Invalid decoder: expected {CBORDecoderConfig.__name__}, got {type(decoder).__name__}")
        self.__d = dataclass_asdict(decoder)

    @final
    def _serialize_to_file(self, packet: _ST_contra, file: IO[bytes]) -> None:
        from cbor2 import CBOREncoder

        CBOREncoder(file, **self.__e).encode(packet)

    @final
    def _deserialize_from_file(self, file: IO[bytes]) -> _DT_co:
        from cbor2 import CBORDecoder

        return CBORDecoder(file, **self.__d).decode()
