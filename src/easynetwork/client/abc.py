# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = ["AbstractNetworkClient"]

from abc import ABCMeta, abstractmethod
from socket import socket as Socket
from typing import TYPE_CHECKING, Any, Generic, Iterator, TypeVar, overload

from ..tools.socket import SocketAddress

_T = TypeVar("_T")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class AbstractNetworkClient(Generic[_SentPacketT, _ReceivedPacketT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractNetworkClient[Any, Any]")

    def __del__(self) -> None:
        if not self.is_closed():
            self.close()

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

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
    def send_packets(self, *packets: _SentPacketT) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_packet(self) -> _ReceivedPacketT:
        raise NotImplementedError

    @overload
    @abstractmethod
    def recv_packet_no_block(self, *, timeout: float = ...) -> _ReceivedPacketT:
        ...

    @overload
    @abstractmethod
    def recv_packet_no_block(self, *, default: _T, timeout: float = ...) -> _ReceivedPacketT | _T:
        ...

    @abstractmethod
    def recv_packet_no_block(self, *, default: _T = ..., timeout: float = ...) -> _ReceivedPacketT | _T:
        raise NotImplementedError

    def iter_received_packets(self, *, timeout: float = 0) -> Iterator[_ReceivedPacketT]:
        timeout = float(timeout)
        _not_received: Any = object()
        while True:
            packet = self.recv_packet_no_block(timeout=timeout, default=_not_received)
            if packet is _not_received:
                break
            yield packet

    def recv_all_packets(self, *, timeout: float = 0) -> list[_ReceivedPacketT]:
        return list(self.iter_received_packets(timeout=timeout))

    @abstractmethod
    def fileno(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def dup(self) -> Socket:
        raise NotImplementedError

    @abstractmethod
    def detach(self) -> Socket:
        raise NotImplementedError
