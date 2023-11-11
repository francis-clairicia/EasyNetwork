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
"""msgpack-based network packet serializer module"""

from __future__ import annotations

__all__ = [
    "MessagePackSerializer",
    "MessagePackerConfig",
    "MessageUnpackerConfig",
]

from collections.abc import Callable
from dataclasses import asdict as dataclass_asdict, dataclass, field
from functools import partial
from typing import Any, final

from ..exceptions import DeserializeError
from .abc import AbstractPacketSerializer


def _get_default_ext_hook() -> Callable[[int, bytes], Any]:
    try:
        import msgpack
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ModuleNotFoundError("message-pack dependencies are missing. Consider adding 'msgpack' extra") from exc
    return msgpack.ExtType


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
    ext_hook: Callable[[int, bytes], Any] = field(default_factory=_get_default_ext_hook)


class MessagePackSerializer(AbstractPacketSerializer[Any]):
    """
    A :term:`one-shot serializer` built on top of the :mod:`msgpack` module.

    Needs ``msgpack`` extra dependencies.
    """

    __slots__ = ("__packb", "__unpackb", "__unpack_out_of_data_cls", "__unpack_extra_data_cls", "__debug")

    def __init__(
        self,
        packer_config: MessagePackerConfig | None = None,
        unpacker_config: MessageUnpackerConfig | None = None,
        *,
        debug: bool = False,
    ) -> None:
        """
        Parameters:
            packer_config: Parameter object to configure the :class:`~msgpack.Packer`.
            unpacker_config: Parameter object to configure the :class:`~msgpack.Unpacker`.
            debug: If :data:`True`, add information to :exc:`.DeserializeError` via the ``error_info`` attribute.
        """
        try:
            import msgpack
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("message-pack dependencies are missing. Consider adding 'msgpack' extra") from exc

        super().__init__()
        self.__packb: Callable[[Any], bytes]
        self.__unpackb: Callable[[bytes], Any]

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

        self.__packb = partial(msgpack.packb, **dataclass_asdict(packer_config), autoreset=True)
        self.__unpackb = partial(msgpack.unpackb, **dataclass_asdict(unpacker_config))
        self.__unpack_out_of_data_cls = msgpack.OutOfData
        self.__unpack_extra_data_cls = msgpack.ExtraData

        self.__debug: bool = bool(debug)

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
        except self.__unpack_out_of_data_cls as exc:
            msg = "Missing data to create packet"
            if self.debug:
                raise DeserializeError(msg, error_info={"data": data}) from exc
            raise DeserializeError(msg) from exc
        except self.__unpack_extra_data_cls as exc:
            msg = "Extra data caught"
            if self.debug:
                raise DeserializeError(msg, error_info={"packet": exc.unpacked, "extra": exc.extra}) from exc  # type: ignore[attr-defined]
            raise DeserializeError(msg) from exc
        except Exception as exc:  # The documentation says to catch all exceptions :)
            msg = str(exc) or "Invalid token"
            if self.debug:
                raise DeserializeError(msg, error_info={"data": data}) from exc
            raise DeserializeError(msg) from exc
        finally:
            del data

    @property
    @final
    def debug(self) -> bool:
        """
        The debug mode flag. Read-only attribute.
        """
        return self.__debug
