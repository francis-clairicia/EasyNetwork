# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network servers' request handler base classes module"""

from __future__ import annotations

__all__ = [
    "AbstractDatagramClient",
    "AbstractDatagramRequestHandler",
    "AbstractStreamClient",
    "AbstractStreamRequestHandler",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, final

from ..tools.socket import SocketAddress, SocketProxy

if TYPE_CHECKING:
    from ..exceptions import BaseProtocolParseError

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class _ClientMixin(Generic[_ResponseT], metaclass=ABCMeta):
    __slots__ = ("__addr", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        super().__init__()
        self.__addr: SocketAddress = address

    def __repr__(self) -> str:
        return f"<client with address {self.address} at {id(self):#x}>"

    @abstractmethod
    def send_packet(self, packet: _ResponseT) -> None:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr


class AbstractStreamClient(_ClientMixin[_ResponseT]):
    def __init__(self, address: SocketAddress) -> None:
        super().__init__(address)

    def __repr__(self) -> str:
        return f"<connected client with address {self.address} at {id(self):#x}{' closed' if self.is_closed() else ''}>"

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def socket(self) -> SocketProxy:
        raise NotImplementedError


class AbstractDatagramClient(_ClientMixin[_ResponseT]):
    def __init__(self, address: SocketAddress) -> None:
        super().__init__(address)


class _RequestHandlerServiceMixin(Generic[_RequestT, _ResponseT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def service_init(self, server: Any) -> None:
        pass

    def service_quit(self) -> None:
        pass

    def service_actions(self) -> None:
        pass


class AbstractStreamRequestHandler(_RequestHandlerServiceMixin[_RequestT, _ResponseT]):
    __slots__ = ()

    @abstractmethod
    def handle(self, request: _RequestT, client: AbstractStreamClient[_ResponseT]) -> None:
        raise NotImplementedError

    def on_connection(self, client: AbstractStreamClient[_ResponseT]) -> None:
        pass

    def on_disconnection(self, client: AbstractStreamClient[_ResponseT]) -> None:
        pass

    def bad_request(
        self,
        client: AbstractStreamClient[_ResponseT],
        error_type: BaseProtocolParseError.ParseErrorType,
        message: str,
        error_info: Any,
    ) -> None:
        pass

    def handle_error(self, client: AbstractStreamClient[_ResponseT], exc_info: Callable[[], BaseException | None]) -> bool:
        return False


class AbstractDatagramRequestHandler(_RequestHandlerServiceMixin[_RequestT, _ResponseT]):
    __slots__ = ()

    def accept_request_from(self, client_address: SocketAddress) -> bool:
        return True

    @abstractmethod
    def handle(self, request: _RequestT, client: AbstractDatagramClient[_ResponseT]) -> None:
        raise NotImplementedError

    def bad_request(
        self,
        client: AbstractDatagramClient[_ResponseT],
        error_type: BaseProtocolParseError.ParseErrorType,
        message: str,
        error_info: Any,
    ) -> None:
        pass

    def handle_error(self, client: AbstractDatagramClient[_ResponseT], exc_info: Callable[[], BaseException | None]) -> bool:
        return False
