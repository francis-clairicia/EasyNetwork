from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
import time
import traceback
from collections.abc import Generator
from typing import ClassVar

from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.lowlevel.request_handler import RecvAncillaryDataParams, RecvParams
from easynetwork.lowlevel.socket import SCMCredentials, SCMRights, SocketAncillary, UnixSocketAddress
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers.json import JSONSerializer
from easynetwork.servers.handlers import BlockingStreamClient, BlockingStreamRequestHandler, UNIXClientAttribute
from easynetwork.servers.threaded_unix_stream import ThreadedUnixStreamServer


class Request: ...


class Response: ...


class BadRequest(Response): ...


class InternalError(Response): ...


class TimedOut(Response): ...


class MinimumRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
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
        client.send_packet(Response())
        #################

        ### On a 'return'
        # When handle() returns, it means that this request handler is finished.
        # It does not close the connection or anything.
        # The server immediately creates a new generator.
        #################
        return


class ConnectionCloseRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        client.send_packet(Response())

        # At this point, the transport is closed and the server
        # will not create a new generator.
        client.close()


class ConnectionCloseWithContextRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        with contextlib.closing(client):
            request: Request = yield

            client.send_packet(Response())


class ConnectionCloseBeforeYieldRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        if not self.should_handle(client):
            return

        request: Request = yield

    def should_handle(self, client: BlockingStreamClient[Response]) -> bool:
        return True


class ErrorHandlingInRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        try:
            # *All* exceptions are thrown through the "yield" statement
            # (including BaseException). But you should only catch Exception subclasses.
            request: Request = yield
        except StreamProtocolParseError:
            client.send_packet(BadRequest())
        except OSError:
            # It is possible that something went wrong with the underlying
            # transport (the socket) at the OS level.
            # You should check if the client is always usable.
            try:
                client.send_packet(InternalError())
            except OSError:
                client.close()
                raise
        except Exception:
            # Runtime error. Log the error.
            traceback.print_exc()

            client.send_packet(InternalError())
        else:
            client.send_packet(Response())


class MultipleYieldInRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        ...

        client.send_packet(Response())

        if self.need_something_else(request, client):
            additional_data: Request = yield

            ...

            client.send_packet(Response())

    def need_something_else(self, request: Request, client: BlockingStreamClient[Response]) -> bool:
        return True


class ClientLoopInRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        # Close the client at the loop break
        with contextlib.closing(client):
            # Ask the user to log in
            initial_user_info: Request = yield

            ...

            # Sucessfully logged in
            client.send_packet(Response())

            # Start handling requests
            while not client.is_closing():
                request: Request = yield

                ...

                client.send_packet(Response())


class TimeoutYieldedRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[RecvParams | None, Request]:
        try:
            # The client has 30 seconds to send the request to the server.
            request: Request = yield RecvParams(timeout=30.0)
        except TimeoutError:
            client.send_packet(TimedOut())
        else:
            client.send_packet(Response())


class SCMSendRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        ancillary = SocketAncillary()
        ancillary.add_fds([4])
        client.send_packet_with_ancillary(Response(), ancillary)


class SCMRecvRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[RecvParams | None, Request]:
        ancillary = SocketAncillary()
        request: Request = yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary.update_from_raw))

        for message in ancillary.messages():
            match message:
                case SCMRights(fds):
                    for fd in fds:
                        print(f"Received file descriptor: {fd}")
                case SCMCredentials(credentials):
                    for ucred in credentials:
                        print(f"Received unix credential: {ucred}")

    @staticmethod
    async def example_custom_ancillary_bufsize() -> None:
        # [start]
        from socket import CMSG_LEN

        max_fds = 128
        server = ThreadedUnixStreamServer(
            "/var/run/app.sock",
            StreamProtocol(JSONSerializer()),
            SCMRecvRequestHandler(),
            ancillary_bufsize=CMSG_LEN(max_fds * 4),
        )


class ClientConnectionHooksRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def on_connection(self, client: BlockingStreamClient[Response]) -> None:
        print(f"{client!r} is connected")

        # Notify the client that the service is ready.
        client.send_packet(Response())

    def on_disconnection(self, client: BlockingStreamClient[Response]) -> None:
        # Perfom service shutdown clean-up
        ...

        print(f"{client!r} is disconnected")

    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        ...

        client.send_packet(Response())


class ClientConnectionGeneratorRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def on_connection(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        # Ask the user to log in
        initial_user_info: Request = yield

        ...

        # Sucessfully logged in
        client.send_packet(Response())

    def on_disconnection(self, client: BlockingStreamClient[Response]) -> None:
        # Perfom log out clean-up
        ...

    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        ...

        client.send_packet(Response())


class ClientExtraAttributesRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        client_address = client.extra(UNIXClientAttribute.peer_name)

        request: Request = yield

        print(f"{client_address} sent {request}")

        client.send_packet(Response())


class ServiceInitializationHookRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    def service_init(
        self,
        exit_stack: contextlib.ExitStack,
        server: ThreadedUnixStreamServer[Request, Response],
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


class ClientContextRequestHandler(BlockingStreamRequestHandler[Request, Response]):
    client_addr_var: ClassVar[contextvars.ContextVar[UnixSocketAddress]]
    client_addr_var = contextvars.ContextVar("client_addr")

    @classmethod
    def client_log(cls, message: str) -> None:
        # The address of the currently handled client can be accessed
        # without passing it explicitly to this function.

        logger = logging.getLogger(cls.__name__)

        client_address = cls.client_addr_var.get()

        logger.info("From %s: %s", client_address, message)

    def on_connection(
        self,
        client: BlockingStreamClient[Response],
    ) -> None:
        address = client.extra(UNIXClientAttribute.peer_name)
        self.client_addr_var.set(address)

        # In any code that we call within "handle()" is now possible to get
        # client's address by calling 'client_addr_var.get()'.

    def handle(
        self,
        client: BlockingStreamClient[Response],
    ) -> Generator[None, Request]:
        request: Request = yield

        self.client_log(f"Received request: {request!r}")

        client.send_packet(Response())
