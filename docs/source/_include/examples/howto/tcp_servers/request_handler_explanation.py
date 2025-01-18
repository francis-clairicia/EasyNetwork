from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import traceback
from collections.abc import AsyncGenerator
from typing import ClassVar

import trio

from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.lowlevel.socket import SocketAddress
from easynetwork.servers import AsyncTCPNetworkServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler, INETClientAttribute


class Request: ...


class Response: ...


class BadRequest(Response): ...


class InternalError(Response): ...


class TimedOut(Response): ...


class MinimumRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        ### Before 'yield'
        # Initializes the generator.
        # This is the setup part before receiving a request.
        # You don't have much thing to do here.
        ##################

        request: Request = yield

        ### After 'yield'
        # Once the server has sent you the client's request,
        # you can do whatever you want with it and send responses back
        # to the client if necessary.
        await client.send_packet(Response())
        #################

        ### On a 'return'
        # When handle() returns, it means that this request handler is finished.
        # It does not close the connection or anything.
        # The server immediately creates a new generator.
        #################
        return


class ConnectionCloseRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        await client.send_packet(Response())

        # At this point, the transport is closed and the server
        # will not create a new generator.
        await client.aclose()


class ConnectionCloseWithContextRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        async with contextlib.aclosing(client):
            request: Request = yield

            await client.send_packet(Response())


class ConnectionCloseBeforeYieldRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        if not self.should_handle(client):
            return

        request: Request = yield

    def should_handle(self, client: AsyncStreamClient[Response]) -> bool:
        return True


class ErrorHandlingInRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        try:
            # *All* exceptions are thrown through the "yield" statement
            # (including BaseException). But you should only catch Exception subclasses.
            request: Request = yield
        except StreamProtocolParseError:
            await client.send_packet(BadRequest())
        except OSError:
            # It is possible that something went wrong with the underlying
            # transport (the socket) at the OS level.
            # You should check if the client is always usable.
            try:
                await client.send_packet(InternalError())
            except OSError:
                await client.aclose()
                raise
        except Exception:
            # Runtime error. Log the error.
            traceback.print_exc()

            await client.send_packet(InternalError())
        else:
            await client.send_packet(Response())


class MultipleYieldInRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        ...

        await client.send_packet(Response())

        if self.need_something_else(request, client):
            additional_data: Request = yield

            ...

            await client.send_packet(Response())

    def need_something_else(self, request: Request, client: AsyncStreamClient[Response]) -> bool:
        return True


class ClientLoopInRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        # Close the client at the loop break
        async with contextlib.aclosing(client):
            # Ask the user to log in
            initial_user_info: Request = yield

            ...

            # Sucessfully logged in
            await client.send_packet(Response())

            # Start handling requests
            while not client.is_closing():
                request: Request = yield

                ...

                await client.send_packet(Response())


class TimeoutContextRequestHandlerAsyncIO(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        try:
            async with asyncio.timeout(30):
                # The client has 30 seconds to send the request to the server.
                request: Request = yield
        except TimeoutError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class TimeoutContextRequestHandlerTrio(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        try:
            with trio.fail_after(30):
                # The client has 30 seconds to send the request to the server.
                request: Request = yield
        except trio.TooSlowError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class TimeoutContextRequestHandlerWithClientBackend(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        try:
            with client.backend().timeout(30):
                # The client has 30 seconds to send the request to the server.
                request: Request = yield
        except TimeoutError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class TimeoutYieldedRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[float | None, Request]:
        try:
            # The client has 30 seconds to send the request to the server.
            request: Request = yield 30.0
        except TimeoutError:
            await client.send_packet(TimedOut())
        else:
            await client.send_packet(Response())


class ClientConnectionHooksRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def on_connection(self, client: AsyncStreamClient[Response]) -> None:
        print(f"{client!r} is connected")

        # Notify the client that the service is ready.
        await client.send_packet(Response())

    async def on_disconnection(self, client: AsyncStreamClient[Response]) -> None:
        # Perfom service shutdown clean-up
        ...

        print(f"{client!r} is disconnected")

    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        ...

        await client.send_packet(Response())


class ClientConnectionAsyncGenRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def on_connection(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        # Ask the user to log in
        initial_user_info: Request = yield

        ...

        # Sucessfully logged in
        await client.send_packet(Response())

    async def on_disconnection(self, client: AsyncStreamClient[Response]) -> None:
        # Perfom log out clean-up
        ...

    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        ...

        await client.send_packet(Response())


class ClientExtraAttributesRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        client_address = client.extra(INETClientAttribute.remote_address)

        request: Request = yield

        print(f"{client_address.host} sent {request}")

        await client.send_packet(Response())


class ServiceInitializationHookRequestHandlerAsyncIO(AsyncStreamRequestHandler[Request, Response]):
    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncTCPNetworkServer[Request, Response],
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


class ServiceInitializationHookRequestHandlerTrio(AsyncStreamRequestHandler[Request, Response]):
    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncTCPNetworkServer[Request, Response],
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


class ServiceInitializationHookRequestHandlerWithServerBackend(AsyncStreamRequestHandler[Request, Response]):
    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: AsyncTCPNetworkServer[Request, Response],
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


class ClientContextRequestHandler(AsyncStreamRequestHandler[Request, Response]):
    client_addr_var: ClassVar[contextvars.ContextVar[SocketAddress]]
    client_addr_var = contextvars.ContextVar("client_addr")

    @classmethod
    def client_log(cls, message: str) -> None:
        # The address of the currently handled client can be accessed
        # without passing it explicitly to this function.

        logger = logging.getLogger(cls.__name__)

        client_address = cls.client_addr_var.get()

        logger.info("From %s: %s", client_address, message)

    async def on_connection(
        self,
        client: AsyncStreamClient[Response],
    ) -> None:
        address = client.extra(INETClientAttribute.remote_address)
        self.client_addr_var.set(address)

        # In any code that we call within "handle()" is now possible to get
        # client's address by calling 'client_addr_var.get()'.

    async def handle(
        self,
        client: AsyncStreamClient[Response],
    ) -> AsyncGenerator[None, Request]:
        request: Request = yield

        self.client_log(f"Received request: {request!r}")

        await client.send_packet(Response())
