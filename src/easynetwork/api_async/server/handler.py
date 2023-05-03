# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network servers' request handler base classes module"""

from __future__ import annotations

__all__ = [
    "AsyncBaseRequestHandler",
    "AsyncClientInterface",
    "AsyncDatagramRequestHandler",
    "AsyncStreamRequestHandler",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar, final

if TYPE_CHECKING:
    from ...exceptions import BaseProtocolParseError
    from ...tools.socket import SocketAddress, SocketProxy
    from ..backend.abc import AbstractAsyncBackend


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AsyncClientInterface(Generic[_ResponseT], metaclass=ABCMeta):
    __slots__ = ("__addr", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        super().__init__()
        self.__addr: SocketAddress = address

    def __repr__(self) -> str:
        return f"<client with address {self.address} at {id(self):#x}>"

    @abstractmethod
    async def send_packet(self, packet: _ResponseT) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_closing(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr

    @property
    @abstractmethod
    def socket(self) -> SocketProxy:
        raise NotImplementedError


class AsyncBaseRequestHandler(Generic[_RequestT, _ResponseT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    async def service_init(self, backend: AbstractAsyncBackend, /) -> None:
        pass

    async def service_quit(self) -> None:
        pass

    async def service_actions(self) -> None:
        pass

    @abstractmethod
    async def handle(self, request: _RequestT, client: AsyncClientInterface[_ResponseT]) -> None:
        raise NotImplementedError

    async def bad_request(self, client: AsyncClientInterface[_ResponseT], exc: BaseProtocolParseError) -> None:
        pass

    async def handle_error(self, client: AsyncClientInterface[_ResponseT], exc: Exception) -> bool:
        return False


class AsyncStreamRequestHandler(AsyncBaseRequestHandler[_RequestT, _ResponseT]):
    __slots__ = ()

    async def on_connection(self, client: AsyncClientInterface[_ResponseT]) -> None:
        pass

    async def on_disconnection(self, client: AsyncClientInterface[_ResponseT]) -> None:
        pass


class AsyncDatagramRequestHandler(AsyncBaseRequestHandler[_RequestT, _ResponseT]):
    __slots__ = ()

    async def accept_request_from(self, client_address: SocketAddress) -> bool:
        return True
