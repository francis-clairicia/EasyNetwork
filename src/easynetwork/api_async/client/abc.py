# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network client module"""

from __future__ import annotations

__all__ = ["AbstractAsyncNetworkClient"]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator, Generic, TypeVar

from ...tools.socket import SocketAddress

if TYPE_CHECKING:
    from types import TracebackType

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class AbstractAsyncNetworkClient(Generic[_SentPacketT, _ReceivedPacketT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractAsyncNetworkClient[Any, Any]")

    async def __aenter__(self: __Self) -> __Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def is_closing(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def abort(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_local_address(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    def get_remote_address(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    async def send_packet(self, packet: _SentPacketT) -> None:
        raise NotImplementedError

    @abstractmethod
    async def recv_packet(self) -> _ReceivedPacketT:
        raise NotImplementedError

    async def iter_received_packets(self) -> AsyncIterator[_ReceivedPacketT]:
        recv_packet = self.recv_packet
        while True:
            try:
                packet = await recv_packet()
            except OSError:
                return
            yield packet

    @abstractmethod
    def fileno(self) -> int:
        raise NotImplementedError