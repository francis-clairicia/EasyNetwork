from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import traceback
from collections.abc import AsyncGenerator
from typing import ClassVar

import trio

from easynetwork.exceptions import DatagramProtocolParseError
from easynetwork.lowlevel.socket import UnixSocketAddress
from easynetwork.servers.async_unix_datagram import AsyncUnixDatagramServer
from easynetwork.servers.handlers import AsyncDatagramClient, AsyncDatagramRequestHandler, UNIXClientAttribute


class Request: ...


class Response: ...


class BadRequest(Response): ...


class InternalError(Response): ...


class TimedOut(Response): ...


class MinimumRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        ### Before 'yield'
        # Initializes the generator.
        # This is the setup part before receiving a request.
        # Unlike the stream request handler, the generator is started
        # when the datagram is received (but is not parsed yet).
        ##################

        request: Request = yield

        ### After 'yield'
        # The received datagram is parsed.
        # you can do whatever you want with it and send responses back
        # to the client if necessary.
        await client.send_packet(Response())
        #################

        ### On a 'return'
        # When handle() returns, it means that this request handler is finished.
        # The server creates a new generator when a new datagram is received.
        #################
        return


class SkipDatagramRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        if not self.should_handle(client):
            # By returning before the "yield" statement, you ask the server to discard
            # the received datagram.
            return

        request: Request = yield

    def should_handle(self, client: AsyncDatagramClient[Response]) -> bool:
        return True


class ErrorHandlingInRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        try:
            # *All* exceptions are thrown through the "yield" statement
            # (including BaseException). But you should only catch Exception subclasses.
            request: Request = yield
        except DatagramProtocolParseError:
            await client.send_packet(BadRequest())
        except Exception:
            # Runtime error. Log the error.
            traceback.print_exc()

            await client.send_packet(InternalError())
        else:
            await client.send_packet(Response())


class MultipleYieldInRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        ...

        await client.send_packet(Response())

        if self.need_something_else(request, client):
            additional_data: Request = yield

            ...

            await client.send_packet(Response())

    def need_something_else(self, request: Request, client: AsyncDatagramClient[Response]) -> bool:
        return True


class TimeoutContextRequestHandlerAsyncIO(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        # It is *never* useful to have a timeout for the 1st datagram
        # because the datagram is already in the queue.
        request: Request = yield

        ...

        await client.send_packet(Response())

        try:
            async with asyncio.timeout(30):
                # The client has 30 seconds to send the 2nd request to the server.
                another_request: Request = yield
        except TimeoutError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class TimeoutContextRequestHandlerTrio(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        # It is *never* useful to have a timeout for the 1st datagram
        # because the datagram is already in the queue.
        request: Request = yield

        ...

        await client.send_packet(Response())

        try:
            with trio.fail_after(30):
                # The client has 30 seconds to send the 2nd request to the server.
                another_request: Request = yield
        except trio.TooSlowError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class TimeoutContextRequestHandlerWithClientBackend(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        # It is *never* useful to have a timeout for the 1st datagram
        # because the datagram is already in the queue.
        request: Request = yield

        ...

        await client.send_packet(Response())

        try:
            with client.backend().timeout(30):
                # The client has 30 seconds to send the 2nd request to the server.
                another_request: Request = yield
        except TimeoutError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class TimeoutYieldedRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[float | None, Request]:
        # It is *never* useful to have a timeout for the 1st datagram
        # because the datagram is already in the queue.
        # The yielded value is simply ignored.
        request: Request = yield None

        ...

        await client.send_packet(Response())

        try:
            # The client has 30 seconds to send the 2nd request to the server.
            another_request: Request = yield 30
        except TimeoutError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class ClientExtraAttributesRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        client_address = client.extra(UNIXClientAttribute.peer_name)

        request: Request = yield

        print(f"{client_address} sent {request}")

        await client.send_packet(Response())


class ServiceInitializationHookRequestHandlerAsyncIO(AsyncDatagramRequestHandler[Request, Response]):
    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncUnixDatagramServer[Request, Response],
    ) -> None:
        exit_stack.callback(self._service_quit)

        self.background_tasks = await exit_stack.enter_async_context(asyncio.TaskGroup())

        _ = self.background_tasks.create_task(self._service_actions())

    async def _service_actions(self) -> None:
        while True:
            await asyncio.sleep(1)

            # Do some stuff each second in background
            ...

    def _service_quit(self) -> None:
        print("Service stopped")


class ServiceInitializationHookRequestHandlerTrio(AsyncDatagramRequestHandler[Request, Response]):
    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncUnixDatagramServer[Request, Response],
    ) -> None:
        exit_stack.callback(self._service_quit)

        self.background_tasks = await exit_stack.enter_async_context(trio.open_nursery())

        self.background_tasks.start_soon(self._service_actions)

    async def _service_actions(self) -> None:
        while True:
            await trio.sleep(1)

            # Do some stuff each second in background
            ...

    def _service_quit(self) -> None:
        print("Service stopped")


class ServiceInitializationHookRequestHandlerWithServerBackend(AsyncDatagramRequestHandler[Request, Response]):
    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncUnixDatagramServer[Request, Response],
    ) -> None:
        exit_stack.callback(self._service_quit)

        self.backend = server.backend()
        self.background_tasks = await exit_stack.enter_async_context(self.backend.create_task_group())

        self.background_tasks.start_soon(self._service_actions)

    async def _service_actions(self) -> None:
        while True:
            await self.backend.sleep(1)

            # Do some stuff each second in background
            ...

    def _service_quit(self) -> None:
        print("Service stopped")


class ClientContextRequestHandler(AsyncDatagramRequestHandler[Request, Response]):
    client_addr_var: ClassVar[contextvars.ContextVar[UnixSocketAddress]]
    client_addr_var = contextvars.ContextVar("client_addr")

    @classmethod
    def client_log(cls, message: str) -> None:
        # The address of the currently handled client can be accessed
        # without passing it explicitly to this function.

        logger = logging.getLogger(cls.__name__)

        client_address = cls.client_addr_var.get()

        logger.info("From %s: %s", client_address, message)

    async def handle(
        self,
        client: AsyncDatagramClient[Response],
    ) -> AsyncGenerator[None, Request]:
        address = client.extra(UNIXClientAttribute.peer_name)
        self.client_addr_var.set(address)

        # In any code that we call within "handle()" is now possible to get
        # client's address by calling 'client_addr_var.get()'.

        request: Request = yield

        self.client_log(f"Received request: {request!r}")

        await client.send_packet(Response())
