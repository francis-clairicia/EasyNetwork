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
from ._typevars import DeserializedPacketT_co, SerializedPacketT_contra
from .abc import AbstractPacketSerializer


def _get_default_ext_hook() -> Callable[[int, bytes], Any]:
    try:
        import msgpack
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ModuleNotFoundError("message-pack dependencies are missing. Consider adding 'msgpack' extra") from exc
    return msgpack.ExtType


@dataclass(kw_only=True)
class MessagePackerConfig:
    default: Callable[[Any], Any] | None = None
    use_single_float: bool = False
    use_bin_type: bool = True
    datetime: bool = False
    strict_types: bool = False
    unicode_errors: str = "strict"


@dataclass(kw_only=True)
class MessageUnpackerConfig:
    raw: bool = False
    use_list: bool = True
    timestamp: int = 0
    strict_map_key: bool = True
    unicode_errors: str = "strict"
    object_hook: Callable[[dict[Any, Any]], Any] | None = None
    object_pairs_hook: Callable[[list[tuple[Any, Any]]], Any] | None = None
    ext_hook: Callable[[int, bytes], Any] = field(default_factory=_get_default_ext_hook)


class MessagePackSerializer(AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
    __slots__ = ("__packb", "__unpackb", "__unpack_out_of_data_cls", "__unpack_extra_data_cls")

    def __init__(
        self,
        packer_config: MessagePackerConfig | None = None,
        unpacker_config: MessageUnpackerConfig | None = None,
    ) -> None:
        try:
            import msgpack
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError("message-pack dependencies are missing. Consider adding 'msgpack' extra") from exc

        super().__init__()
        self.__packb: Callable[[SerializedPacketT_contra], bytes]
        self.__unpackb: Callable[[bytes], DeserializedPacketT_co]

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

    @final
    def serialize(self, packet: SerializedPacketT_contra) -> bytes:
        return self.__packb(packet)

    @final
    def deserialize(self, data: bytes) -> DeserializedPacketT_co:
        try:
            return self.__unpackb(data)
        except self.__unpack_out_of_data_cls as exc:
            raise DeserializeError("Missing data to create packet", error_info={"data": data}) from exc
        except self.__unpack_extra_data_cls as exc:
            raise DeserializeError("Extra data caught", error_info={"packet": exc.unpacked, "extra": exc.extra}) from exc  # type: ignore[attr-defined]
        except Exception as exc:  # The documentation says to catch all exceptions :)
            raise DeserializeError(str(exc) or "Invalid token", error_info={"data": data}) from exc
