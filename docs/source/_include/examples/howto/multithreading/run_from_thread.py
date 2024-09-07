from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack

from easynetwork.lowlevel.api_async.backend.abc import IEvent
from easynetwork.servers.async_tcp import AsyncTCPNetworkServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler


class Request: ...


class Response: ...


class BaseRunFromSomeThreadRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def service_init(self, exit_stack: AsyncExitStack, server: AsyncTCPNetworkServer[Request, Response]) -> None:
        from concurrent.futures import ThreadPoolExecutor

        from easynetwork.lowlevel.futures import AsyncExecutor

        # 4 worker threads for the demo
        self.executor = AsyncExecutor(ThreadPoolExecutor(max_workers=4), server.backend())
        await exit_stack.enter_async_context(self.executor)

        # Create a portal to execute code from external threads in the scheduler loop
        self.portal = server.backend().create_threads_portal()
        await exit_stack.enter_async_context(self.portal)


class RunCoroutineFromSomeThreadRequestHandler(BaseRunFromSomeThreadRequestHandler):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        response = await self.executor.run(self._data_processing, request)

        await client.send_packet(response)

    def _data_processing(self, request: Request) -> Response:
        # Get back in scheduler loop for 1 second
        backend = self.executor.backend()
        self.portal.run_coroutine(backend.sleep, 1)

        return Response()


class RunSyncFromSomeThreadRequestHandler(BaseRunFromSomeThreadRequestHandler):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        event = client.backend().create_event()

        self.executor.wrapped.submit(self._blocking_wait, event)
        await event.wait()

        await client.send_packet(Response())

    def _blocking_wait(self, event: IEvent) -> None:
        time.sleep(1)

        # Thread-safe flag set
        self.portal.run_sync(event.set)


class SpawnTaskFromSomeThreadRequestHandler(BaseRunFromSomeThreadRequestHandler):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        await self.executor.run(self._blocking_wait)

        await client.send_packet(Response())

    def _blocking_wait(self) -> None:
        sleep = self.executor.backend().sleep

        async def long_running_task(index: int) -> str:
            await sleep(1)
            print(f"Task {index} running...")
            await sleep(index)
            return f"Task {index} return value"

        # Spawn several tasks
        from concurrent.futures import as_completed

        futures = [self.portal.run_coroutine_soon(long_running_task, i) for i in range(1, 5)]
        for future in as_completed(futures):
            print(future.result())
