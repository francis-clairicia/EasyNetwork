# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["StandaloneTCPNetworkServer", "StandaloneUDPNetworkServer"]

import asyncio
import contextlib
from typing import Any, Callable, Coroutine, TypeVar

from easynetwork.api_async.server.standalone import BaseStandaloneTCPNetworkServer, BaseStandaloneUDPNetworkServer
from easynetwork.api_async.server.tcp import AsyncTCPNetworkServer as _AsyncTCPNetworkServer
from easynetwork.api_async.server.udp import AsyncUDPNetworkServer as _AsyncUDPNetworkServer

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class _AsyncioBootstrapMixin:
    __slots__ = ()

    def _bootstrap(self, __func: Callable[..., Coroutine[Any, Any, None]], /, *args: Any) -> None:
        with self._new_asyncio_runner() as runner, contextlib.suppress(asyncio.CancelledError):
            runner.run(__func(*args))

    def _new_asyncio_runner(self) -> asyncio.Runner:
        return asyncio.Runner()


class StandaloneTCPNetworkServer(_AsyncioBootstrapMixin, BaseStandaloneTCPNetworkServer[_RequestT, _ResponseT]):
    __slots__ = ("__asyncio_runner_factory",)

    def __init__(
        self,
        server: _AsyncTCPNetworkServer[_RequestT, _ResponseT],
        *,
        runner_factory: Callable[[], asyncio.Runner] | None = None,
    ) -> None:
        from .backend import AsyncioBackend

        assert isinstance(server.get_backend(), AsyncioBackend)
        super().__init__(server)
        self.__asyncio_runner_factory: Callable[[], asyncio.Runner] | None = runner_factory

    def _new_asyncio_runner(self) -> asyncio.Runner:
        if (runner_factory := self.__asyncio_runner_factory) is None:
            return super()._new_asyncio_runner()
        return runner_factory()


class StandaloneUDPNetworkServer(_AsyncioBootstrapMixin, BaseStandaloneUDPNetworkServer[_RequestT, _ResponseT]):
    __slots__ = ("__asyncio_runner_factory",)

    def __init__(
        self,
        server: _AsyncUDPNetworkServer[_RequestT, _ResponseT],
        *,
        runner_factory: Callable[[], asyncio.Runner] | None = None,
    ) -> None:
        from .backend import AsyncioBackend

        assert isinstance(server.get_backend(), AsyncioBackend)
        super().__init__(server)
        self.__asyncio_runner_factory: Callable[[], asyncio.Runner] | None = runner_factory

    def _new_asyncio_runner(self) -> asyncio.Runner:
        if (runner_factory := self.__asyncio_runner_factory) is None:
            return super()._new_asyncio_runner()
        return runner_factory()
