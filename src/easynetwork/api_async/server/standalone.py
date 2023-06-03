# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AbstractStandaloneNetworkServer", "StandaloneTCPNetworkServer", "StandaloneUDPNetworkServer"]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Self, TypeVar

from .tcp import AsyncTCPNetworkServer as _AsyncTCPNetworkServer
from .udp import AsyncUDPNetworkServer as _AsyncUDPNetworkServer

if TYPE_CHECKING:
    from types import TracebackType

    from ..backend.abc import AbstractThreadsPortal
    from .abc import AbstractAsyncNetworkServer

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AbstractStandaloneNetworkServer(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.server_close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def is_serving(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def serve_forever(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def server_close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError


class _BaseStandaloneNetworkServerImpl(AbstractStandaloneNetworkServer):
    __slots__ = (
        "__server",
        "__threads_portal",
    )

    def __init__(self, server: AbstractAsyncNetworkServer) -> None:
        super().__init__()
        self.__server: AbstractAsyncNetworkServer = server
        self.__threads_portal: AbstractThreadsPortal | None = None

    def is_serving(self) -> bool:
        if (portal := self.__threads_portal) is not None:
            return portal.run_sync(self.__server.is_serving)
        return False

    def server_close(self) -> None:
        if (portal := self.__threads_portal) is not None:
            portal.run_coroutine(self.__server.server_close)
        else:
            backend = self.__server.get_backend()
            backend.bootstrap(self.__server.server_close)

    def shutdown(self) -> None:
        if (portal := self.__threads_portal) is not None:
            portal.run_coroutine(self.__server.shutdown)

    def serve_forever(self) -> None:
        import contextlib

        async def serve_forever() -> None:
            if self.__threads_portal is not None:
                raise RuntimeError("Server is already running")
            try:
                self.__threads_portal = self.__server.get_backend().create_threads_portal()
                async with self.__server:
                    await self.__server.serve_forever()
            finally:
                self.__threads_portal = None

        backend = self.__server.get_backend()
        with contextlib.suppress(backend.get_cancelled_exc_class()):
            backend.bootstrap(serve_forever)

    @property
    def _server(self) -> AbstractAsyncNetworkServer:
        return self.__server

    @property
    def _portal(self) -> AbstractThreadsPortal | None:
        return self.__threads_portal


class StandaloneTCPNetworkServer(_BaseStandaloneNetworkServerImpl, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    def __init__(self, server: _AsyncTCPNetworkServer[_RequestT, _ResponseT]) -> None:
        assert isinstance(server, _AsyncTCPNetworkServer)
        super().__init__(server)

    def stop_listening(self) -> None:
        if (portal := self._portal) is not None:
            portal.run_sync(self._server.stop_listening)

    if TYPE_CHECKING:

        @property
        def _server(self) -> _AsyncTCPNetworkServer[_RequestT, _ResponseT]:
            ...


class StandaloneUDPNetworkServer(_BaseStandaloneNetworkServerImpl, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    def __init__(self, server: _AsyncUDPNetworkServer[_RequestT, _ResponseT]) -> None:
        assert isinstance(server, _AsyncUDPNetworkServer)
        super().__init__(server)

    if TYPE_CHECKING:

        @property
        def _server(self) -> _AsyncUDPNetworkServer[_RequestT, _ResponseT]:
            ...
