from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import NamedTuple

from easynetwork.api_async.server.abc import AbstractAsyncNetworkServer
from easynetwork.exceptions import ServerAlreadyRunning, ServerClosedError

import pytest
import pytest_asyncio


class _ServerBootstrapInfo(NamedTuple):
    task: asyncio.Task[None]
    is_up_event: asyncio.Event


@pytest.mark.asyncio
class BaseTestAsyncServer:
    @pytest.fixture(autouse=True)
    @staticmethod
    def disable_asyncio_logs(caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level("ERROR", "asyncio")

    @pytest_asyncio.fixture  # DO NOT SET autouse=True
    @staticmethod
    async def _bootstrap_server(server: AbstractAsyncNetworkServer) -> AsyncIterator[_ServerBootstrapInfo]:
        async def serve_forever(server: AbstractAsyncNetworkServer, event: asyncio.Event) -> None:
            with contextlib.suppress(ServerClosedError):
                await server.serve_forever(is_up_event=event)

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
        server: AbstractAsyncNetworkServer,
    ) -> None:
        event = asyncio.Event()
        async with asyncio.TaskGroup() as tg:
            _ = tg.create_task(server.serve_forever(is_up_event=event))
            await asyncio.sleep(0)
            assert not event.is_set()
            await server.shutdown()
            assert not event.is_set()

    async def test____serve_forever____server_close_during_setup(
        self,
        server: AbstractAsyncNetworkServer,
    ) -> None:
        event = asyncio.Event()
        server_task = None
        with pytest.raises(ExceptionGroup):
            async with asyncio.TaskGroup() as tg:
                server_task = tg.create_task(server.serve_forever(is_up_event=event))
                await asyncio.sleep(0)
                assert not event.is_set()
                await server.server_close()
                assert not event.is_set()
        assert server_task is not None
        assert isinstance(server_task.exception(), ServerClosedError)

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
