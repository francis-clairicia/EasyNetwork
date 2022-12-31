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
from typing import TYPE_CHECKING, Any, TypeVar

from ..tools.socket import SocketAddress


class AbstractNetworkClient(metaclass=ABCMeta):
    __slots__ = ()

    if TYPE_CHECKING:
        __Self = TypeVar("__Self", bound="AbstractNetworkClient")

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
    def fileno(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def dup(self) -> Socket:
        raise NotImplementedError

    @abstractmethod
    def detach(self) -> Socket:
        raise NotImplementedError
