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
"""pickle-based packet serializer module"""

from __future__ import annotations

__all__ = [
    "PickleSerializer",
    "PicklerConfig",
    "UnpicklerConfig",
]

from collections.abc import Callable
from dataclasses import asdict as dataclass_asdict, dataclass, field
from functools import partial
from io import BytesIO
from typing import IO, TYPE_CHECKING, final

from ..exceptions import DeserializeError
from ._typevars import DeserializedPacketT_co, SerializedPacketT_contra
from .abc import AbstractPacketSerializer

if TYPE_CHECKING:
    from pickle import Pickler as _Pickler, Unpickler as _Unpickler


def _get_default_pickler_protocol() -> int:
    import pickle

    return pickle.DEFAULT_PROTOCOL


@dataclass(kw_only=True)
class PicklerConfig:
    """
    A dataclass with the Pickler options.

    See :class:`pickle.Pickler` for more information.
    """

    protocol: int = field(default_factory=_get_default_pickler_protocol)
    fix_imports: bool = False


@dataclass(kw_only=True)
class UnpicklerConfig:
    """
    A dataclass with the Unpickler options.

    See :class:`pickle.Unpickler` for more information.
    """

    fix_imports: bool = False
    encoding: str = "utf-8"
    errors: str = "strict"


class PickleSerializer(AbstractPacketSerializer[SerializedPacketT_contra, DeserializedPacketT_co]):
    """
    A :term:`one-shot serializer` built on top of the :mod:`pickle` module.
    """

    __slots__ = ("__optimize", "__pickler_cls", "__unpickler_cls")

    def __init__(
        self,
        pickler_config: PicklerConfig | None = None,
        unpickler_config: UnpicklerConfig | None = None,
        *,
        pickler_cls: type[_Pickler] | None = None,
        unpickler_cls: type[_Unpickler] | None = None,
        pickler_optimize: bool = False,
    ) -> None:
        """
        Arguments:
            pickler_config: Parameter object to configure the :class:`~pickle.Pickler`.
            unpickler_config: Parameter object to configure the :class:`~pickle.Unpickler`.
            pickler_cls: The :class:`~pickle.Pickler` class to use (see :ref:`pickle-inst`).
            unpickler_cls: The :class:`~pickle.Unpickler` class to use (see :ref:`pickle-restrict`).
            pickler_optimize: If `True`, :func:`pickletools.optimize` will be applied to :meth:`pickle.Pickler.dump` output.
        """
        super().__init__()

        import pickle

        self.__optimize: Callable[[bytes], bytes] | None = None
        if pickler_optimize:
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
    def serialize(self, packet: SerializedPacketT_contra) -> bytes:
        """
        Returns the pickle representation of the Python object `packet`.

        Roughly equivalent to::

            def serialize(packet):
                return pickle.dumps(packet)

        Arguments:
            packet: The Python object to serialize.

        Returns:
            a byte sequence.
        """
        with BytesIO() as buffer:
            self.__pickler_cls(buffer).dump(packet)
            pickle: bytes = buffer.getvalue()
        if (optimize := self.__optimize) is not None:
            pickle = optimize(pickle)
        return pickle

    @final
    def deserialize(self, data: bytes) -> DeserializedPacketT_co:
        """
        Creates a Python object representing the raw pickle :term:`packet` from `data`.

        Roughly equivalent to::

            def deserialize(data):
                return pickle.loads(data)

        Arguments:
            data: The byte sequence to deserialize.

        Raises:
            DeserializeError: Too little or too much data to parse.
            DeserializeError: An unrelated deserialization error occurred.

        Returns:
            the deserialized Python object.
        """
        with BytesIO(data) as buffer:
            try:
                packet: DeserializedPacketT_co = self.__unpickler_cls(buffer).load()
            except Exception as exc:
                raise DeserializeError(str(exc) or "Invalid token", error_info={"data": data}) from exc
            finally:
                del data
            if extra := buffer.read():  # There is still data after deserialization
                raise DeserializeError("Extra data caught", {"packet": packet, "extra": extra})
        return packet
