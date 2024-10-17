from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack

import trio

from easynetwork.servers.async_tcp import AsyncTCPNetworkServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler


class Request: ...


class Response: ...


class RunInSomeThreadRequestHandlerAsyncIO(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        response = await asyncio.to_thread(self._data_processing, request)

        await client.send_packet(response)

    def _data_processing(self, request: Request) -> Response:
        # Simulate long computing
        time.sleep(1)

        return Response()


class RunInSomeThreadRequestHandlerTrio(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        response = await trio.to_thread.run_sync(self._data_processing, request)

        await client.send_packet(response)

    def _data_processing(self, request: Request) -> Response:
        # Simulate long computing
        time.sleep(1)

        return Response()


class RunInSomeThreadRequestHandlerWithClientBackend(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        response = await client.backend().run_in_thread(self._data_processing, request)

        await client.send_packet(response)

    def _data_processing(self, request: Request) -> Response:
        # Simulate long computing
        time.sleep(1)

        return Response()


class RunInSomeThreadRequestHandlerWithExecutor(AsyncStreamRequestHandler[Request, Response]):
    async def service_init(self, exit_stack: AsyncExitStack, server: AsyncTCPNetworkServer[Request, Response]) -> None:
        from concurrent.futures import ThreadPoolExecutor

        from easynetwork.lowlevel.futures import AsyncExecutor

        # 4 worker threads for the demo
        self.executor = AsyncExecutor(ThreadPoolExecutor(max_workers=4), server.backend())
        # Shut down executor at server stop
        await exit_stack.enter_async_context(self.executor)

    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        response = await self.executor.run(self._data_processing, request)

        await client.send_packet(response)

    def _data_processing(self, request: Request) -> Response:
        # Simulate long computing
        time.sleep(1)

        return Response()
