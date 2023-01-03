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

from abc import abstractmethod
from contextlib import contextmanager
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable, Generic, Iterator, TypeVar, final

from ..tools.socket import SocketAddress

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class ConnectedClient(Generic[_ResponseT]):
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


class AbstractNetworkServer(Generic[_RequestT, _ResponseT]):
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

    @final
    def handle_request(self, request: _RequestT, client: ConnectedClient[_ResponseT]) -> None:
        def process_request(client: ConnectedClient[_ResponseT]) -> None:
            return self.process_request(request, client)

        return self.__process_request_hook__(process_request, client, self.handle_error)

    def __process_request_hook__(
        self,
        process_request: Callable[[ConnectedClient[Any]], None],
        client: ConnectedClient[Any],
        error_handler: Callable[[ConnectedClient[Any]], None],
    ) -> None:
        try:
            return process_request(client)
        except Exception:
            error_handler(client)

    @abstractmethod
    def process_request(self, request: _RequestT, client: ConnectedClient[_ResponseT]) -> None:
        raise NotImplementedError

    def handle_error(self, client: ConnectedClient[Any]) -> None:
        from sys import exc_info, stderr
        from traceback import print_exc

        if exc_info() == (None, None, None):
            return

        print("-" * 40, file=stderr)
        print(f"Exception occurred during processing of request from {client.address}", file=stderr)
        print_exc(file=stderr)
        print("-" * 40, file=stderr)

    @property
    @abstractmethod
    def address(self) -> SocketAddress:
        raise NotImplementedError
