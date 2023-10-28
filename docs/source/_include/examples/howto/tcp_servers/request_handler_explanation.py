from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator

from easynetwork.api_async.server import AsyncStreamClient, AsyncStreamRequestHandler, AsyncTCPNetworkServer
from easynetwork.exceptions import StreamProtocolParseError


class Request:
    ...


class Response:
    ...


class BadRequest(Response):
    ...


class InternalError(Response):
    ...


class TimedOut(Response):
    ...


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
        # When handle() returns, this means that the handling of ONE request
        # has finished. There is no connection close or whatever.
        # The server will immediately create a new generator.
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


class TimeoutRequestHandler(AsyncStreamRequestHandler[Request, Response]):
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


class ServiceInitializationHookRequestHandler(AsyncStreamRequestHandler[Request, Response]):
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
