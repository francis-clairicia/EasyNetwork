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
"""``cbor``-based network packet serializer module.

The `CBOR <https://cbor.io>`_ is an alternative representation of the ``JSON`` data models.

See Also:

    :ref:`optional-dependencies`
        Explains how to install ``cbor`` extra.
"""

from __future__ import annotations

__all__ = [
    "CBORDecoderConfig",
    "CBOREncoderConfig",
    "CBORSerializer",
]

from collections.abc import Callable
from dataclasses import asdict as dataclass_asdict, dataclass
from functools import partial
from typing import IO, TYPE_CHECKING, Any, final

from ..lowlevel import _utils
from ..lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from .base_stream import FileBasedPacketSerializer

if TYPE_CHECKING:
    import datetime


@dataclass(kw_only=True)
class CBOREncoderConfig:
    """
    A dataclass with the CBOR encoder options.

    See :class:`cbor2.CBOREncoder` for details.
    """

    datetime_as_timestamp: bool = False
    timezone: datetime.tzinfo | None = None
    value_sharing: bool = False
    default: Callable[..., Any] | None = None
    canonical: bool = False
    date_as_datetime: bool = False
    string_referencing: bool = False


@dataclass(kw_only=True)
class CBORDecoderConfig:
    """
    A dataclass with the CBOR decoder options.

    See :class:`cbor2.CBORDecoder` for details.
    """

    object_hook: Callable[..., Any] | None = None
    tag_hook: Callable[..., Any] | None = None
    str_errors: str = "strict"


class CBORSerializer(FileBasedPacketSerializer[Any, Any]):
    """
    A :term:`serializer` built on top of the :mod:`cbor2` module.

    Needs ``cbor`` extra dependencies.
    """

    __slots__ = ("__encoder_cls", "__decoder_cls")

    def __init__(
        self,
        encoder_config: CBOREncoderConfig | None = None,
        decoder_config: CBORDecoderConfig | None = None,
        *,
        limit: int = DEFAULT_SERIALIZER_LIMIT,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            encoder_config: Parameter object to configure the :class:`~cbor.encoder.CBOREncoder`.
            decoder_config: Parameter object to configure the :class:`~cbor.decoder.CBORDecoder`.
            limit: Maximum buffer size. Used in incremental serialization context.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        try:
            import cbor2
        except ModuleNotFoundError as exc:
            raise _utils.missing_extra_deps("cbor") from exc

        super().__init__(expected_load_error=(cbor2.CBORDecodeError, UnicodeError), limit=limit, debug=debug)
        self.__encoder_cls: Callable[[IO[bytes]], cbor2.CBOREncoder]
        self.__decoder_cls: Callable[[IO[bytes]], cbor2.CBORDecoder]

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
    def dump_to_file(self, packet: Any, file: IO[bytes]) -> None:
        """
        Write the CBOR representation of `packet` to `file`.

        Roughly equivalent to::

            def dump_to_file(self, packet, file):
                cbor2.dump(packet, file)

        Parameters:
            packet: The Python object to serialize.
            file: The :std:term:`binary file` to write to.
        """
        self.__encoder_cls(file).encode(packet)

    @final
    def load_from_file(self, file: IO[bytes]) -> Any:
        """
        Read from `file` to deserialize the raw CBOR :term:`packet`.

        Roughly equivalent to::

            def load_from_file(self, file):
                return cbor2.load(file)

        Parameters:
            file: The :std:term:`binary file` to read from.

        Returns:
            the deserialized Python object.
        """
        return self.__decoder_cls(file).decode()
