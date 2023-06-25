# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["AbstractNetworkClient"]

import time
from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Iterator, Self, TypeVar

from ...tools.socket import SocketAddress

if TYPE_CHECKING:
    from types import TracebackType

_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class AbstractNetworkClient(Generic[_SentPacketT, _ReceivedPacketT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_local_address(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    def get_remote_address(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _SentPacketT) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_packet(self, timeout: float | None = ...) -> _ReceivedPacketT:
        raise NotImplementedError

    def iter_received_packets(self, timeout: float | None = 0) -> Iterator[_ReceivedPacketT]:
        monotonic = time.monotonic

        recv_packet = self.recv_packet
        while True:
            try:
                _start = monotonic()
                packet = recv_packet(timeout)
                _end = monotonic()
            except OSError:
                return
            yield packet
            if timeout is not None:
                timeout -= _end - _start

    @abstractmethod
    def fileno(self) -> int:
        raise NotImplementedError
