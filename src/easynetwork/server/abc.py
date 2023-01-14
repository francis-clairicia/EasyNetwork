# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = [
    "AbstractNetworkServer",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ..tools.socket import SocketAddress

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AbstractNetworkServer(Generic[_RequestT, _ResponseT], metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractNetworkServer[Any, Any]")

    def __del__(self) -> None:
        if not self.is_closed():
            self.server_close()

    def __enter__(self: __Self) -> __Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()
        self.server_close()

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

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
