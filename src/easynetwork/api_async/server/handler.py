# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Asynchronous network servers' request handler base classes module"""

from __future__ import annotations

__all__ = [
    "AsyncBaseClientInterface",
    "AsyncBaseRequestHandler",
    "AsyncDatagramClient",
    "AsyncDatagramRequestHandler",
    "AsyncStreamClient",
    "AsyncStreamRequestHandler",
]

import contextlib
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import TYPE_CHECKING, Any, Generic, final

from ..._typevars import _RequestT, _ResponseT

if TYPE_CHECKING:
    from ...exceptions import DatagramProtocolParseError, StreamProtocolParseError
    from ...tools.socket import SocketAddress, SocketProxy
    from ..backend.abc import AsyncBackend


class AsyncBaseClientInterface(Generic[_ResponseT], metaclass=ABCMeta):
    __slots__ = ("__addr", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        super().__init__()
        self.__addr: SocketAddress = address

    def __repr__(self) -> str:
        return f"<client with address {self.address} at {id(self):#x}>"

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    async def send_packet(self, packet: _ResponseT, /) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_closing(self) -> bool:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr

    @property
    @abstractmethod
    def socket(self) -> SocketProxy:
        raise NotImplementedError


class AsyncStreamClient(AsyncBaseClientInterface[_ResponseT]):
    __slots__ = ()

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError


class AsyncDatagramClient(AsyncBaseClientInterface[_ResponseT]):
    __slots__ = ()

    @abstractmethod
    def __hash__(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def __eq__(self, other: object, /) -> bool:
        raise NotImplementedError


class AsyncBaseRequestHandler(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def set_async_backend(self, backend: AsyncBackend, /) -> None:
        pass

    async def service_init(self, exit_stack: contextlib.AsyncExitStack, /) -> None:
        pass


class AsyncStreamRequestHandler(AsyncBaseRequestHandler, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    @abstractmethod
    def handle(self, client: AsyncStreamClient[_ResponseT], /) -> AsyncGenerator[None, _RequestT]:
        raise NotImplementedError

    @abstractmethod
    async def bad_request(self, client: AsyncStreamClient[_ResponseT], exc: StreamProtocolParseError, /) -> bool | None:
        raise NotImplementedError

    def on_connection(
        self,
        client: AsyncStreamClient[_ResponseT],
        /,
    ) -> Coroutine[Any, Any, None] | AsyncGenerator[None, _RequestT]:
        async def _pass() -> None:
            pass

        return _pass()

    async def on_disconnection(self, client: AsyncStreamClient[_ResponseT], /) -> None:
        pass

    def set_stop_listening_callback(self, stop_listening_callback: Callable[[], None], /) -> None:
        pass


class AsyncDatagramRequestHandler(AsyncBaseRequestHandler, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    @abstractmethod
    def handle(self, client: AsyncDatagramClient[_ResponseT], /) -> AsyncGenerator[None, _RequestT]:
        raise NotImplementedError

    @abstractmethod
    async def bad_request(self, client: AsyncDatagramClient[_ResponseT], exc: DatagramProtocolParseError, /) -> bool | None:
        raise NotImplementedError
