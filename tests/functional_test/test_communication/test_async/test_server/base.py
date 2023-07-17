from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from easynetwork.api_async.server.abc import AbstractAsyncNetworkServer
from easynetwork.exceptions import ServerAlreadyRunning, ServerClosedError

import pytest
import pytest_asyncio


@pytest.mark.asyncio
class BaseTestAsyncServer:
    @pytest_asyncio.fixture  # DO NOT SET autouse=True
    @staticmethod
    async def run_server(server: AbstractAsyncNetworkServer) -> AsyncIterator[asyncio.Event]:
        async def serve_forever(server: AbstractAsyncNetworkServer, event: asyncio.Event) -> None:
            with contextlib.suppress(ServerClosedError):
                await server.serve_forever(is_up_event=event)

        event = asyncio.Event()
        async with asyncio.TaskGroup() as tg:
            _ = tg.create_task(serve_forever(server, event))
            await asyncio.sleep(0)
            yield event
            await server.shutdown()

    @pytest.mark.usefixtures("run_server")
    async def test____serve_forever____error_already_running(self, server: AbstractAsyncNetworkServer) -> None:
        with pytest.raises(ServerAlreadyRunning):
            await server.serve_forever()

    async def test____serve_forever____error_closed_server(self, server: AbstractAsyncNetworkServer) -> None:
        await server.server_close()
        with pytest.raises(ServerClosedError):
            await server.serve_forever()

    async def test____serve_forever____concurrent_shutdown(
        self,
        server: AbstractAsyncNetworkServer,
        run_server: asyncio.Event,
    ) -> None:
        await run_server.wait()

        await asyncio.gather(*[server.shutdown() for _ in range(10)])
