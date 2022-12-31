# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
# mypy: no-warn-unused-ignores
"""Network client module"""

from __future__ import annotations

__all__ = ["AbstractNetworkClient"]

from abc import ABCMeta, abstractmethod
from socket import socket as Socket
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, overload

from ..tools.socket import SocketAddress

_T = TypeVar("_T")
_ReceivedPacketT = TypeVar("_ReceivedPacketT")
_SentPacketT = TypeVar("_SentPacketT")


class AbstractNetworkClient(Generic[_SentPacketT, _ReceivedPacketT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractNetworkClient[Any, Any]")

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def getsockname(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    def getpeername(self) -> SocketAddress:
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _SentPacketT, *, timeout: float | None = ..., flags: int = ...) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_packets(self, *packets: _SentPacketT, timeout: float | None = ..., flags: int = ...) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_packet(self, *, flags: int = ..., on_error: Literal["raise", "ignore"] | None = ...) -> _ReceivedPacketT:
        raise NotImplementedError

    @overload
    @abstractmethod
    def recv_packet_no_block(
        self, *, timeout: float = ..., flags: int = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> _ReceivedPacketT:
        ...

    @overload
    @abstractmethod
    def recv_packet_no_block(
        self, *, default: _T, timeout: float = ..., flags: int = ..., on_error: Literal["raise", "ignore"] | None = ...
    ) -> _ReceivedPacketT | _T:
        ...

    @abstractmethod
    def recv_packet_no_block(
        self,
        *,
        default: Any = ...,
        timeout: float = ...,
        flags: int = ...,
        on_error: Literal["raise", "ignore"] | None = ...,
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def recv_packets(
        self,
        *,
        timeout: float | None = ...,
        flags: int = ...,
        on_error: Literal["raise", "ignore"] | None = ...,
    ) -> list[_ReceivedPacketT]:
        raise NotImplementedError

    @abstractmethod
    def fileno(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def dup(self) -> Socket:
        raise NotImplementedError

    @abstractmethod
    def detach(self) -> Socket:
        raise NotImplementedError
