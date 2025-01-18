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
"""``MessagePack``-based network packet serializer module.

The `MessagePack <https://msgpack.org/>`_ is an alternative representation of the ``JSON`` data models.

See Also:

    :ref:`optional-dependencies`
        Explains how to install ``msgpack`` extra.
"""

from __future__ import annotations

__all__ = [
    "MessagePackSerializer",
    "MessagePackerConfig",
    "MessageUnpackerConfig",
]

from collections.abc import Callable
from dataclasses import asdict as dataclass_asdict, dataclass
from functools import partial
from typing import IO, Any, final

from ..exceptions import DeserializeError
from ..lowlevel import _utils
from ..lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
from .base_stream import FileBasedPacketSerializer


@dataclass(kw_only=True)
class MessagePackerConfig:
    """
    A dataclass with the Packer options.

    See :class:`msgpack.Packer` for details.
    """

    default: Callable[[Any], Any] | None = None
    use_single_float: bool = False
    use_bin_type: bool = True
    datetime: bool = False
    strict_types: bool = False
    unicode_errors: str = "strict"


@dataclass(kw_only=True)
class MessageUnpackerConfig:
    """
    A dataclass with the Unpacker options.

    See :class:`msgpack.Unpacker` for details.
    """

    raw: bool = False
    use_list: bool = True
    timestamp: int = 0
    strict_map_key: bool = True
    unicode_errors: str = "strict"
    object_hook: Callable[[dict[Any, Any]], Any] | None = None
    object_pairs_hook: Callable[[list[tuple[Any, Any]]], Any] | None = None
    ext_hook: Callable[[int, bytes], Any] | None = None


class MessagePackSerializer(FileBasedPacketSerializer[Any, Any]):
    """
    A :term:`serializer` built on top of the :mod:`msgpack` module.

    Needs ``msgpack`` extra dependencies.
    """

    __slots__ = (
        "__packb",
        "__unpackb",
        "__incremental_packer",
        "__incremental_unpacker",
        "__unpack_out_of_data_cls",
        "__unpack_extra_data_cls",
    )

    def __init__(
        self,
        packer_config: MessagePackerConfig | None = None,
        unpacker_config: MessageUnpackerConfig | None = None,
        *,
        limit: int = DEFAULT_SERIALIZER_LIMIT,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            packer_config: Parameter object to configure the :class:`~msgpack.Packer`.
            unpacker_config: Parameter object to configure the :class:`~msgpack.Unpacker`.
            limit: Maximum buffer size. Used in incremental serialization context.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        try:
            import msgpack
        except ModuleNotFoundError as exc:
            raise _utils.missing_extra_deps("msgpack", feature_name="message-pack") from exc

        super().__init__(
            expected_load_error=Exception,  # The documentation says to catch all exceptions :)
            limit=limit,
            debug=debug,
        )
        limit = self.buffer_limit
        self.__packb: Callable[[Any], bytes]
        self.__unpackb: Callable[[bytes], Any]
        self.__incremental_packer: Callable[[], msgpack.Packer]
        self.__incremental_unpacker: Callable[[IO[bytes]], msgpack.Unpacker]

        if packer_config is None:
            packer_config = MessagePackerConfig()
        elif not isinstance(packer_config, MessagePackerConfig):
            raise TypeError(f"Invalid packer config: expected {MessagePackerConfig.__name__}, got {type(packer_config).__name__}")

        if unpacker_config is None:
            unpacker_config = MessageUnpackerConfig()
        elif not isinstance(unpacker_config, MessageUnpackerConfig):
            raise TypeError(
                f"Invalid unpacker config: expected {MessageUnpackerConfig.__name__}, got {type(unpacker_config).__name__}"
            )

        packer_options = dataclass_asdict(packer_config)
        unpacker_options = dataclass_asdict(unpacker_config)

        del packer_config, unpacker_config

        if unpacker_options.get("ext_hook") is None:
            unpacker_options["ext_hook"] = msgpack.ExtType

        self.__packb = partial(msgpack.packb, **packer_options, autoreset=True)
        self.__unpackb = partial(msgpack.unpackb, **unpacker_options)
        self.__incremental_packer = partial(msgpack.Packer, **packer_options, autoreset=True)
        self.__incremental_unpacker = partial(msgpack.Unpacker, **unpacker_options, max_buffer_size=limit)
        self.__unpack_out_of_data_cls = msgpack.OutOfData
        self.__unpack_extra_data_cls = msgpack.ExtraData

    @final
    def serialize(self, packet: Any) -> bytes:
        """
        Returns the MessagePack representation of the Python object `packet`.

        Roughly equivalent to::

            def serialize(self, packet):
                return msgpack.packb(packet)

        Parameters:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        return self.__packb(packet)

    @final
    def deserialize(self, data: bytes) -> Any:
        """
        Creates a Python object representing the raw MessagePack :term:`packet` from `data`.

        Roughly equivalent to::

            def deserialize(self, data):
                return msgpack.unpackb(data)

        Parameters:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: Too little or too much data to parse.
            DeserializeError: An unrelated deserialization error occurred.

        Returns:
            the deserialized Python object.
        """
        try:
            return self.__unpackb(data)
        except self.__unpack_extra_data_cls as exc:
            msg = "Extra data caught"
            if self.debug:
                raise DeserializeError(msg, error_info={"packet": exc.unpacked, "extra": exc.extra}) from exc  # type: ignore[attr-defined]
            raise DeserializeError(msg) from exc
        except Exception as exc:  # The documentation says to catch all exceptions :)
            msg = str(exc) or "Invalid token"
            if isinstance(exc, ValueError) and "incomplete input" in msg:  # <- And here is our "OutOfData" :)
                msg = "Missing data to create packet"
            if self.debug:
                raise DeserializeError(msg, error_info={"data": data}) from exc
            raise DeserializeError(msg) from exc
        finally:
            del data

    @final
    def dump_to_file(self, packet: Any, file: IO[bytes]) -> None:
        """
        Write the MessagePack representation of `packet` to `file`.

        Roughly equivalent to::

            def dump_to_file(self, packet, file):
                msgpack.pack(packet, file)

        Parameters:
            packet: The Python object to serialize.
            file: The :std:term:`binary file` to write to.
        """
        file.write(self.__incremental_packer().pack(packet))

    @final
    def load_from_file(self, file: IO[bytes]) -> Any:
        """
        Read from `file` to deserialize the raw MessagePack :term:`packet`.

        Roughly equivalent to::

            def load_from_file(self, file):
                return msgpack.unpack(file)

        Parameters:
            file: The :std:term:`binary file` to read from.

        Returns:
            the deserialized Python object.
        """
        current_position = file.tell()
        unpacker = self.__incremental_unpacker(file)
        try:
            packet = unpacker.unpack()
        except self.__unpack_out_of_data_cls:
            raise EOFError from None
        else:
            file.seek(current_position + unpacker.tell())
        finally:
            del unpacker
        return packet
