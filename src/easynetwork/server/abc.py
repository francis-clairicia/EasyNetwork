# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = [
    "AbstractNetworkServer",
    "ConnectedClient",
]

from abc import ABCMeta, abstractmethod
from contextlib import contextmanager
from threading import RLock
from typing import TYPE_CHECKING, Any, Generic, Iterator, TypeVar, final

from ..tools.socket import SocketAddress

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class ConnectedClient(Generic[_ResponseT], metaclass=ABCMeta):
    __slots__ = ("__addr", "__transaction_lock", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        super().__init__()
        self.__addr: SocketAddress = address
        self.__transaction_lock = RLock()

    def __repr__(self) -> str:
        return f"<connected client with address {self.__addr} at {id(self):#x}{' closed' if self.closed else ''}>"

    @final
    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.__transaction_lock:
            yield

    def shutdown(self) -> None:
        with self.transaction():
            if not self.closed:
                try:
                    self.flush()
                finally:
                    self.close()

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _ResponseT) -> None:
        raise NotImplementedError

    def send_packets(self, *packets: _ResponseT) -> None:
        with self.transaction():
            send_packet = self.send_packet
            for packet in packets:
                send_packet(packet)

    @abstractmethod
    def flush(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def closed(self) -> bool:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr


class AbstractNetworkServer(Generic[_RequestT, _ResponseT], metaclass=ABCMeta):
    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractNetworkServer[Any, Any]")

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()
        self.server_close()

    @abstractmethod
    def serve_forever(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def server_close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def running(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def address(self) -> SocketAddress:
        raise NotImplementedError
