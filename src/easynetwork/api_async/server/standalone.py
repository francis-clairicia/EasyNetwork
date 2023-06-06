# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AbstractStandaloneNetworkServer", "StandaloneTCPNetworkServer", "StandaloneUDPNetworkServer"]

import contextlib as _contextlib
from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Mapping, Self, Sequence, TypeVar

from .tcp import AsyncTCPNetworkServer
from .udp import AsyncUDPNetworkServer

if TYPE_CHECKING:
    import logging as _logging
    import threading as _threading
    from ssl import SSLContext as _SSLContext
    from types import TracebackType

    from ...protocol import DatagramProtocol, StreamProtocol
    from ..backend.abc import AbstractAsyncBackend, AbstractThreadsPortal, IEvent
    from .abc import AbstractAsyncNetworkServer
    from .handler import AsyncBaseRequestHandler

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
    def serve_forever(self, *, is_up_event: _threading.Event | None = ...) -> None:
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
            with _contextlib.suppress(RuntimeError):
                return portal.run_sync(self.__server.is_serving)
        return False

    def server_close(self) -> None:
        if (portal := self.__threads_portal) is not None:
            with _contextlib.suppress(RuntimeError):
                portal.run_coroutine(self.__server.server_close)
        else:
            backend = self.__server.get_backend()
            backend.bootstrap(self.__server.server_close)

    def shutdown(self) -> None:
        if (portal := self.__threads_portal) is not None:
            with _contextlib.suppress(RuntimeError):
                portal.run_coroutine(self.__server.shutdown)

    def serve_forever(self, *, is_up_event: _threading.Event | None = None) -> None:
        async def wait_and_set_event(is_up_event_async: IEvent, is_up_event: _threading.Event) -> None:
            await is_up_event_async.wait()
            is_up_event.set()

        async def serve_forever() -> None:
            if self.__threads_portal is not None:
                raise RuntimeError("Server is already running")
            backend = self.__server.get_backend()
            try:
                self.__threads_portal = backend.create_threads_portal()
                is_up_event_async: IEvent | None = None
                async with self.__server, backend.create_task_group() as task_group:
                    if is_up_event is not None:
                        is_up_event_async = backend.create_event()
                        task_group.start_soon(wait_and_set_event, is_up_event_async, is_up_event)
                    await self.__server.serve_forever(is_up_event=is_up_event_async)
            finally:
                self.__threads_portal = None

        backend = self.__server.get_backend()
        with _contextlib.suppress(backend.get_cancelled_exc_class()):
            backend.bootstrap(serve_forever)

    @property
    def _server(self) -> AbstractAsyncNetworkServer:
        return self.__server

    @property
    def _portal(self) -> AbstractThreadsPortal | None:
        return self.__threads_portal


class StandaloneTCPNetworkServer(_BaseStandaloneNetworkServerImpl, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        backend: str | AbstractAsyncBackend,
        *,
        ssl: _SSLContext | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        family: int = 0,
        backlog: int | None = None,
        reuse_port: bool = False,
        max_recv_size: int | None = None,
        service_actions_interval: float | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        logger: _logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        assert backend is not None, "You must explicitly give a backend name or instance"
        super().__init__(
            AsyncTCPNetworkServer(
                host=host,
                port=port,
                protocol=protocol,
                request_handler=request_handler,
                ssl=ssl,
                ssl_handshake_timeout=ssl_handshake_timeout,
                ssl_shutdown_timeout=ssl_shutdown_timeout,
                family=family,
                backlog=backlog,
                reuse_port=reuse_port,
                max_recv_size=max_recv_size,
                service_actions_interval=service_actions_interval,
                backend=backend,
                backend_kwargs=backend_kwargs,
                logger=logger,
                **kwargs,
            )
        )

    def stop_listening(self) -> None:
        if (portal := self._portal) is not None:
            with _contextlib.suppress(RuntimeError):
                portal.run_sync(self._server.stop_listening)

    if TYPE_CHECKING:

        @property
        def _server(self) -> AsyncTCPNetworkServer[_RequestT, _ResponseT]:
            ...


class StandaloneUDPNetworkServer(_BaseStandaloneNetworkServerImpl, Generic[_RequestT, _ResponseT]):
    __slots__ = ()

    def __init__(
        self,
        host: str | None,
        port: int,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        backend: str | AbstractAsyncBackend,
        *,
        family: int = 0,
        reuse_port: bool = False,
        backend_kwargs: Mapping[str, Any] | None = None,
        service_actions_interval: float | None = None,
        logger: _logging.Logger | None = None,
        **kwargs: Any,
    ) -> None:
        assert backend is not None, "You must explicitly give a backend name or instance"
        super().__init__(
            AsyncUDPNetworkServer(
                host=host,
                port=port,
                protocol=protocol,
                request_handler=request_handler,
                family=family,
                reuse_port=reuse_port,
                backend=backend,
                backend_kwargs=backend_kwargs,
                service_actions_interval=service_actions_interval,
                logger=logger,
                **kwargs,
            )
        )

    if TYPE_CHECKING:

        @property
        def _server(self) -> AsyncUDPNetworkServer[_RequestT, _ResponseT]:
            ...
