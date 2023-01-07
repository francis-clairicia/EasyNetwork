# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network protocol module"""

from __future__ import annotations

__all__ = ["DatagramProtocol", "StreamProtocol"]

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

from .converter import AbstractPacketConverter, NoPacketConversion
from .serializers.abc import AbstractPacketSerializer
from .serializers.stream.abc import AbstractIncrementalPacketSerializer

_SentDTOPacketT = TypeVar("_SentDTOPacketT")
_ReceivedDTOPacketT = TypeVar("_ReceivedDTOPacketT")

_SentPacketT = TypeVar("_SentPacketT")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")


@dataclass(frozen=True, slots=True)
class DatagramProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    serializer: AbstractPacketSerializer[Any, Any]
    converter: AbstractPacketConverter[_SentPacketT, Any, _ReceivedPacketT, Any] = field(default_factory=NoPacketConversion)

    if TYPE_CHECKING:

        @overload  # type: ignore[no-overload-impl]
        def __init__(
            self,
            serializer: AbstractPacketSerializer[_SentPacketT, _ReceivedPacketT],
        ) -> None:
            ...

        @overload
        def __init__(
            self,
            serializer: AbstractPacketSerializer[_SentDTOPacketT, _ReceivedDTOPacketT],
            converter: AbstractPacketConverter[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT],
        ) -> None:
            ...

    def __post_init__(self) -> None:
        assert isinstance(self.serializer, AbstractPacketSerializer)
        assert isinstance(self.converter, AbstractPacketConverter)


@dataclass(frozen=True, slots=True)
class StreamProtocol(Generic[_SentPacketT, _ReceivedPacketT]):
    serializer: AbstractIncrementalPacketSerializer[Any, Any]
    converter: AbstractPacketConverter[_SentPacketT, Any, _ReceivedPacketT, Any] = field(default_factory=NoPacketConversion)

    if TYPE_CHECKING:

        @overload  # type: ignore[no-overload-impl]
        def __init__(
            self,
            serializer: AbstractIncrementalPacketSerializer[_SentPacketT, _ReceivedPacketT],
        ) -> None:
            ...

        @overload
        def __init__(
            self,
            serializer: AbstractIncrementalPacketSerializer[_SentDTOPacketT, _ReceivedDTOPacketT],
            converter: AbstractPacketConverter[_SentPacketT, _SentDTOPacketT, _ReceivedPacketT, _ReceivedDTOPacketT],
        ) -> None:
            ...

    def __post_init__(self) -> None:
        assert isinstance(self.serializer, AbstractIncrementalPacketSerializer)
        assert isinstance(self.converter, AbstractPacketConverter)
