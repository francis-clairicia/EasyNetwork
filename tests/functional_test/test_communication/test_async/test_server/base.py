from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from threading import Event
from typing import NamedTuple

from easynetwork.exceptions import ServerAlreadyRunning, ServerClosedError
from easynetwork.servers.abc import AbstractAsyncNetworkServer

import pytest
import pytest_asyncio


class _ServerBootstrapInfo(NamedTuple):
    task: asyncio.Task[None]
    is_up_event: asyncio.Event


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_eager_tasks")
class BaseTestAsyncServer:
    @pytest.fixture(autouse=True)
    @staticmethod
    def disable_asyncio_logs(caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.ERROR, "asyncio")

    @pytest_asyncio.fixture  # DO NOT SET autouse=True
    @staticmethod
    async def _bootstrap_server(
        server: AbstractAsyncNetworkServer,
        logger_crash_enable: Event,
    ) -> AsyncIterator[_ServerBootstrapInfo]:
        async def serve_forever(server: AbstractAsyncNetworkServer, event: asyncio.Event) -> None:
            with contextlib.suppress(ServerClosedError):
                await server.serve_forever(is_up_event=event)

        logger_crash_enable.set()

        event = asyncio.Event()
        async with asyncio.TaskGroup() as tg:
            task = tg.create_task(serve_forever(server, event))
            await asyncio.sleep(0)
            yield _ServerBootstrapInfo(task, event)
            await server.shutdown()

    @pytest_asyncio.fixture  # DO NOT SET autouse=True
    @staticmethod
    async def run_server(_bootstrap_server: _ServerBootstrapInfo) -> asyncio.Event:
        return _bootstrap_server.is_up_event

    @pytest_asyncio.fixture  # DO NOT SET autouse=True
    @staticmethod
    async def server_task(_bootstrap_server: _ServerBootstrapInfo) -> asyncio.Task[None]:
        return _bootstrap_server.task

    async def test____server_close____idempotent(self, server: AbstractAsyncNetworkServer) -> None:
        await server.server_close()
        await server.server_close()
        await server.server_close()

    async def test____server_close____while_server_is_running(
        self,
        server: AbstractAsyncNetworkServer,
        run_server: asyncio.Event,
    ) -> None:
        await run_server.wait()
        await server.server_close()

        # There is no client so the server loop should stop by itself
        assert not server.is_serving()
        assert not server.is_listening()

    async def test____server_close____while_server_is_running____closed_forcefully(
        self,
        server: AbstractAsyncNetworkServer,
        run_server: asyncio.Event,
    ) -> None:
        await run_server.wait()
        with server.backend().move_on_after(0) as scope:
            await server.server_close()
        assert scope.cancelled_caught()

        assert not server.is_serving()
        assert not server.is_listening()

    @pytest.mark.usefixtures("run_server")
    async def test____serve_forever____error_already_running(self, server: AbstractAsyncNetworkServer) -> None:
        with pytest.raises(ServerAlreadyRunning):
            await server.serve_forever()

    async def test____serve_forever____error_closed_server(self, server: AbstractAsyncNetworkServer) -> None:
        await server.server_close()
        with pytest.raises(ServerClosedError):
            await server.serve_forever()

    async def test____serve_forever____shutdown_during_setup(
        self,
        server_not_activated: AbstractAsyncNetworkServer,
        enable_eager_tasks: bool,
    ) -> None:
        event = asyncio.Event()
        async with asyncio.TaskGroup() as tg:
            _ = tg.create_task(server_not_activated.serve_forever(is_up_event=event))
            if not enable_eager_tasks:
                await asyncio.sleep(0)
            assert not event.is_set()
            async with asyncio.timeout(1):
                await server_not_activated.shutdown()
            assert not event.is_set()

    async def test____serve_forever____without_is_up_event(
        self,
        server: AbstractAsyncNetworkServer,
    ) -> None:
        async with asyncio.TaskGroup() as tg:
            _ = tg.create_task(server.serve_forever())

            await asyncio.sleep(1)
            if not server.is_serving():
                pytest.fail("Timeout error")

            await server.shutdown()

    @pytest.mark.parametrize("server_is_up", [False, True], ids=lambda p: f"server_is_up=={p}")
    async def test____serve_forever____concurrent_shutdown(
        self,
        server_is_up: bool,
        server: AbstractAsyncNetworkServer,
        run_server: asyncio.Event,
    ) -> None:
        if server_is_up:
            await run_server.wait()

        await asyncio.gather(*[server.shutdown() for _ in range(10)])

    async def test____server_activate____server_close_during_activation(
        self,
        server_not_activated: AbstractAsyncNetworkServer,
        enable_eager_tasks: bool,
    ) -> None:
        assert not server_not_activated.is_listening()

        async def serve() -> None:
            with pytest.raises(ServerClosedError):
                await server_not_activated.server_activate()

        async with asyncio.TaskGroup() as tg:
            _ = tg.create_task(serve())
            if not enable_eager_tasks:
                await asyncio.sleep(0)
            assert not server_not_activated.is_listening()
            async with asyncio.timeout(1):
                await server_not_activated.server_close()
            assert not server_not_activated.is_listening()
