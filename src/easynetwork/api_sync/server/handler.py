# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network servers' request handler base classes module"""

from __future__ import annotations

__all__ = [
    "BaseRequestHandler",
    "ClientInterface",
    "DatagramRequestHandler",
    "StreamRequestHandler",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, TypeVar, final

from ...tools.socket import SocketAddress, SocketProxy

if TYPE_CHECKING:
    from ...exceptions import BaseProtocolParseError

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class ClientInterface(Generic[_ResponseT], metaclass=ABCMeta):
    __slots__ = ("__addr", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        super().__init__()
        self.__addr: SocketAddress = address

    def __repr__(self) -> str:
        return f"<client with address {self.address} at {id(self):#x}>"

    @abstractmethod
    def send_packet(self, packet: _ResponseT) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr

    @property
    @abstractmethod
    def socket(self) -> SocketProxy:
        raise NotImplementedError


class BaseRequestHandler(Generic[_RequestT, _ResponseT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def service_init(self) -> None:
        pass

    def service_quit(self) -> None:
        pass

    @abstractmethod
    def handle(self, request: _RequestT, client: ClientInterface[_ResponseT]) -> None:
        raise NotImplementedError

    def bad_request(
        self,
        client: ClientInterface[_ResponseT],
        error_type: BaseProtocolParseError.ParseErrorType,
        message: str,
        error_info: Any,
    ) -> None:
        pass

    def handle_error(self, client: ClientInterface[_ResponseT], exc: Exception) -> bool:
        return False


class StreamRequestHandler(BaseRequestHandler[_RequestT, _ResponseT]):
    __slots__ = ()

    def on_connection(self, client: ClientInterface[_ResponseT]) -> None:
        pass

    def on_disconnection(self, client: ClientInterface[_ResponseT]) -> None:
        pass


class DatagramRequestHandler(BaseRequestHandler[_RequestT, _ResponseT]):
    __slots__ = ()

    def accept_request_from(self, client_address: SocketAddress) -> bool:
        return True
