# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from easynetwork.api_async.server.abc import AbstractAsyncNetworkServer

import pytest
import pytest_asyncio


@pytest.mark.asyncio
class BaseTestAsyncServer:
    @pytest_asyncio.fixture  # DO NOT SET autouse=True
    @staticmethod
    async def run_server(server: AbstractAsyncNetworkServer) -> AsyncIterator[asyncio.Event]:
        event = asyncio.Event()
        async with asyncio.TaskGroup() as tg:
            _ = tg.create_task(server.serve_forever(is_up_event=event))
            await asyncio.sleep(0)
            yield event
            await server.shutdown()

    @pytest.mark.usefixtures("run_server")
    async def test____serve_forever____error_already_running(self, server: AbstractAsyncNetworkServer) -> None:
        with pytest.raises(RuntimeError, match=r"^Server is already running$"):
            await server.serve_forever()

    async def test____serve_forever____error_closed_server(self, server: AbstractAsyncNetworkServer) -> None:
        await server.server_close()
        with pytest.raises(RuntimeError, match=r"^Closed server"):
            await server.serve_forever()
