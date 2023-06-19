# -*- coding: utf-8 -*-
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
from functools import partial
from typing import IO, TYPE_CHECKING, Any, Callable, TypeVar, final

from .base_stream import FileBasedPacketSerializer

if TYPE_CHECKING:
    import datetime

_ST_contra = TypeVar("_ST_contra", contravariant=True)
_DT_co = TypeVar("_DT_co", covariant=True)


@dataclass(kw_only=True)
class CBOREncoderConfig:
    datetime_as_timestamp: bool = False
    timezone: datetime.tzinfo | None = None
    value_sharing: bool = False
    default: Callable[..., Any] | None = None
    canonical: bool = False
    date_as_datetime: bool = False
    string_referencing: bool = False


@dataclass(kw_only=True)
class CBORDecoderConfig:
    object_hook: Callable[..., Any] | None = None
    tag_hook: Callable[..., Any] | None = None
    str_errors: str = "strict"


class CBORSerializer(FileBasedPacketSerializer[_ST_contra, _DT_co]):
    __slots__ = ("__encoder_cls", "__decoder_cls")

    def __init__(
        self,
        encoder_config: CBOREncoderConfig | None = None,
        decoder_config: CBORDecoderConfig | None = None,
    ) -> None:
        try:
            import cbor2
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("cbor dependencies are missing. Consider adding 'cbor' extra") from exc

        super().__init__(expected_load_error=(cbor2.CBORDecodeError, UnicodeError))
        self.__encoder_cls: Callable[[IO[bytes]], cbor2.CBOREncoder]  # type: ignore[no-any-unimported]
        self.__decoder_cls: Callable[[IO[bytes]], cbor2.CBORDecoder]  # type: ignore[no-any-unimported]

        if encoder_config is None:
            encoder_config = CBOREncoderConfig()
        elif not isinstance(encoder_config, CBOREncoderConfig):
            raise TypeError(f"Invalid encoder config: expected {CBOREncoderConfig.__name__}, got {type(encoder_config).__name__}")

        if decoder_config is None:
            decoder_config = CBORDecoderConfig()
        elif not isinstance(decoder_config, CBORDecoderConfig):
            raise TypeError(f"Invalid decoder config: expected {CBORDecoderConfig.__name__}, got {type(decoder_config).__name__}")

        self.__encoder_cls = partial(cbor2.CBOREncoder, **dataclass_asdict(encoder_config))
        self.__decoder_cls = partial(cbor2.CBORDecoder, **dataclass_asdict(decoder_config))

    @final
    def dump_to_file(self, packet: _ST_contra, file: IO[bytes]) -> None:
        self.__encoder_cls(file).encode(packet)

    @final
    def load_from_file(self, file: IO[bytes]) -> _DT_co:
        return self.__decoder_cls(file).decode()
