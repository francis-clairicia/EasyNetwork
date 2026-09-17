from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
import time
import traceback
from collections.abc import Generator
from typing import ClassVar

from easynetwork.exceptions import DatagramProtocolParseError
from easynetwork.lowlevel.request_handler import RecvParams
from easynetwork.lowlevel.socket import SocketAddress
from easynetwork.servers import ThreadedUDPNetworkServer
from easynetwork.servers.handlers import BlockingDatagramClient, BlockingDatagramRequestHandler, INETClientAttribute


class Request: ...


class Response: ...


class BadRequest(Response): ...


class InternalError(Response): ...


class TimedOut(Response): ...


class MinimumRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
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
        client.send_packet(Response())
        #################

        ### On a 'return'
        # When handle() returns, it means that this request handler is finished.
        # The server creates a new generator when a new datagram is received.
        #################
        return


class SkipDatagramRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
        if not self.should_handle(client):
            # By returning before the "yield" statement, you ask the server to discard
            # the received datagram.
            return

        request: Request = yield

    def should_handle(self, client: BlockingDatagramClient[Response]) -> bool:
        return True


class ErrorHandlingInRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
        try:
            # *All* exceptions are thrown through the "yield" statement
            # (including BaseException). But you should only catch Exception subclasses.
            request: Request = yield
        except DatagramProtocolParseError:
            client.send_packet(BadRequest())
        except Exception:
            # Runtime error. Log the error.
            traceback.print_exc()

            client.send_packet(InternalError())
        else:
            client.send_packet(Response())


class MultipleYieldInRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        ...

        client.send_packet(Response())

        if self.need_something_else(request, client):
            additional_data: Request = yield

            ...

            client.send_packet(Response())

    def need_something_else(self, request: Request, client: BlockingDatagramClient[Response]) -> bool:
        return True


class TimeoutYieldedRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[RecvParams | None, Request]:
        # It is *never* useful to have a timeout for the 1st datagram
        # because the datagram is already in the queue.
        # The yielded value is simply ignored.
        request: Request = yield None

        ...

        client.send_packet(Response())

        try:
            # The client has 30 seconds to send the 2nd request to the server.
            another_request: Request = yield RecvParams(timeout=30.0)
        except TimeoutError:
            client.send_packet(TimedOut())
        else:
            client.send_packet(Response())


class ClientExtraAttributesRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
        client_address = client.extra(INETClientAttribute.remote_address)

        request: Request = yield

        print(f"{client_address.host} sent {request}")

        client.send_packet(Response())


class ServiceInitializationHookRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    def service_init(
        self,
        exit_stack: contextlib.ExitStack,
        server: ThreadedUDPNetworkServer[Request, Response],
    ) -> None:
        exit_stack.callback(self._service_quit)

        service_stopped = threading.Event()
        exit_stack.callback(service_stopped.set)

        threading.Thread(target=self._service_actions, args=(service_stopped,), daemon=True).start()

    def _service_actions(self, service_stopped: threading.Event) -> None:
        while not service_stopped.is_set():
            time.sleep(1)

            # Do some stuff each second in background
            ...

    def _service_quit(self) -> None:
        print("Service stopped")


class ClientContextRequestHandler(BlockingDatagramRequestHandler[Request, Response]):
    client_addr_var: ClassVar[contextvars.ContextVar[SocketAddress]]
    client_addr_var = contextvars.ContextVar("client_addr")

    @classmethod
    def client_log(cls, message: str) -> None:
        # The address of the currently handled client can be accessed
        # without passing it explicitly to this function.

        logger = logging.getLogger(cls.__name__)

        client_address = cls.client_addr_var.get()

        logger.info("From %s: %s", client_address, message)

    def handle(
        self,
        client: BlockingDatagramClient[Response],
    ) -> Generator[None, Request]:
        address = client.extra(INETClientAttribute.remote_address)
        self.client_addr_var.set(address)

        # In any code that we call within "handle()" is now possible to get
        # client's address by calling 'client_addr_var.get()'.

        request: Request = yield

        self.client_log(f"Received request: {request!r}")

        client.send_packet(Response())
