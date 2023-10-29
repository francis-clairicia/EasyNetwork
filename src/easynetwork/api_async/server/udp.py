# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkServer"]

import contextlib
import logging
import weakref
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, Callable, Coroutine, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, NoReturn, final

from ..._typevars import _RequestT, _ResponseT
from ...exceptions import ClientClosedError, ServerAlreadyRunning, ServerClosedError
from ...lowlevel import _asyncgen, _utils
from ...lowlevel.api_async.backend.factory import AsyncBackendFactory
from ...lowlevel.api_async.servers import datagram as lowlevel_datagram_server
from ...lowlevel.api_async.transports.abc import AsyncDatagramListener
from ...lowlevel.socket import INETSocketAttribute, SocketAddress, SocketProxy, new_socket_address
from ...protocol import DatagramProtocol
from .abc import AbstractAsyncNetworkServer, SupportsEventSet
from .handler import AsyncDatagramClient, AsyncDatagramRequestHandler, INETClientAttribute

if TYPE_CHECKING:
    from ...lowlevel.api_async.backend.abc import AsyncBackend, CancelScope, IEvent, ILock, Task, TaskGroup


class AsyncUDPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    """
    An asynchronous network server for UDP communication.
    """

    __slots__ = (
        "__backend",
        "__servers",
        "__listeners_factory",
        "__listeners_factory_scope",
        "__protocol",
        "__request_handler",
        "__is_shutdown",
        "__shutdown_asked",
        "__clients_cache",
        "__send_locks_cache",
        "__servers_tasks",
        "__mainloop_task",
        "__logger",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncDatagramRequestHandler[_RequestT, _ResponseT],
        *,
        reuse_port: bool = False,
        logger: logging.Logger | None = None,
        backend: str | AsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Parameters:
            host: specify which network interface to which the server should bind.
            port: specify which port the server should listen on. If the value is ``0``, a random unused port will be selected
                  (note that if `host` resolves to multiple network interfaces, a different random port will be selected
                  for each interface).
            protocol: The :term:`protocol object` to use.
            request_handler: The request handler to use.

        Keyword Arguments:
            reuse_port: tells the kernel to allow this endpoint to be bound to the same port as other existing endpoints
                        are bound to, so long as they all set this flag when being created.
                        This option is not supported on Windows.
            logger: If given, the logger instance to use.

        Backend Parameters:
            backend: the backend to use. Automatically determined otherwise.
            backend_kwargs: Keyword arguments for backend instanciation.
                            Ignored if `backend` is already an :class:`.AsyncBackend` instance.
        """
        super().__init__()

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
        if not isinstance(request_handler, AsyncDatagramRequestHandler):
            raise TypeError(f"Expected an AsyncDatagramRequestHandler object, got {request_handler!r}")

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        self.__listeners_factory: Callable[[], Coroutine[Any, Any, Sequence[AsyncDatagramListener[tuple[Any, ...]]]]] | None
        self.__listeners_factory = _utils.make_callback(
            backend.create_udp_listeners,
            host,
            port,
            reuse_port=reuse_port,
        )
        self.__listeners_factory_scope: CancelScope | None = None

        self.__backend: AsyncBackend = backend
        self.__servers: tuple[lowlevel_datagram_server.AsyncDatagramServer[_RequestT, _ResponseT, tuple[Any, ...]], ...] | None
        self.__servers = None
        self.__protocol: DatagramProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncDatagramRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_shutdown: IEvent = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__shutdown_asked: bool = False
        self.__servers_tasks: deque[Task[NoReturn]] = deque()  # type: ignore[assignment]
        self.__mainloop_task: Task[NoReturn] | None = None
        self.__logger: logging.Logger = logger or logging.getLogger(__name__)
        self.__clients_cache: defaultdict[
            lowlevel_datagram_server.AsyncDatagramServer[_RequestT, _ResponseT, tuple[Any, ...]],
            weakref.WeakValueDictionary[SocketAddress, _ClientAPI[_ResponseT]],
        ]
        self.__send_locks_cache: defaultdict[
            lowlevel_datagram_server.AsyncDatagramServer[_RequestT, _ResponseT, tuple[Any, ...]],
            weakref.WeakValueDictionary[SocketAddress, ILock],
        ]
        self.__clients_cache = defaultdict(weakref.WeakValueDictionary)
        self.__send_locks_cache = defaultdict(weakref.WeakValueDictionary)

    def is_serving(self) -> bool:
        return self.__servers is not None and all(not server.is_closing() for server in self.__servers)

    is_serving.__doc__ = AbstractAsyncNetworkServer.is_serving.__doc__

    async def server_close(self) -> None:
        if self.__listeners_factory_scope is not None:
            self.__listeners_factory_scope.cancel()
        self.__listeners_factory = None
        await self.__close_servers()

    server_close.__doc__ = AbstractAsyncNetworkServer.server_close.__doc__

    async def __close_servers(self) -> None:
        async with contextlib.AsyncExitStack() as exit_stack:
            servers, self.__servers = self.__servers, None
            if servers is not None:
                for server in servers:
                    exit_stack.push_async_callback(server.aclose)
                    del server

            for server_task in self.__servers_tasks:
                server_task.cancel()
                exit_stack.push_async_callback(server_task.wait)
                del server_task

            if self.__mainloop_task is not None:
                self.__mainloop_task.cancel()
                exit_stack.push_async_callback(self.__mainloop_task.wait)

            await self.__backend.cancel_shielded_coro_yield()

    async def shutdown(self) -> None:
        if self.__mainloop_task is not None:
            self.__mainloop_task.cancel()
        if self.__shutdown_asked:
            await self.__is_shutdown.wait()
            return
        self.__shutdown_asked = True
        try:
            await self.__is_shutdown.wait()
        finally:
            self.__shutdown_asked = False

    shutdown.__doc__ = AbstractAsyncNetworkServer.shutdown.__doc__

    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> NoReturn:
        async with contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")
            self.__is_shutdown = is_shutdown = self.__backend.create_event()
            server_exit_stack.callback(is_shutdown.set)
            ################

            # Bind and activate
            assert self.__servers is None  # nosec assert_used
            assert self.__listeners_factory_scope is None  # nosec assert_used
            if self.__listeners_factory is None:
                raise ServerClosedError("Closed server")
            listeners: list[AsyncDatagramListener[tuple[Any, ...]]] = []
            try:
                with self.__backend.open_cancel_scope() as self.__listeners_factory_scope:
                    await self.__backend.coro_yield()
                    listeners.extend(await self.__listeners_factory())
                if self.__listeners_factory_scope.cancelled_caught():
                    raise ServerClosedError("Closed server")
            finally:
                self.__listeners_factory_scope = None
            if not listeners:
                raise OSError("empty listeners list")
            self.__servers = tuple(
                lowlevel_datagram_server.AsyncDatagramServer(
                    listener,
                    self.__protocol,
                    backend=self.__backend,
                )
                for listener in listeners
            )
            del listeners
            ###################

            # Final teardown
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            ################

            # Initialize request handler
            server_exit_stack.callback(self.__send_locks_cache.clear)
            server_exit_stack.callback(self.__clients_cache.clear)
            await self.__request_handler.service_init(
                await server_exit_stack.enter_async_context(contextlib.AsyncExitStack()),
                weakref.proxy(self),
            )
            server_exit_stack.push_async_callback(self.__close_servers)
            ############################

            # Setup task group
            server_exit_stack.callback(self.__servers_tasks.clear)
            task_group: TaskGroup = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            self.__servers_tasks.extend(task_group.start_soon(self.__serve, server, task_group) for server in self.__servers)
            self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
            #################

            # Server is up
            if is_up_event is not None and not self.__shutdown_asked:
                is_up_event.set()
            ##############

            # Main loop
            self.__mainloop_task = task_group.start_soon(self.__backend.sleep_forever)
            if self.__shutdown_asked:
                self.__mainloop_task.cancel()
            try:
                await self.__mainloop_task.join()
            finally:
                self.__mainloop_task = None

        raise AssertionError("sleep_forever() does not return")

    serve_forever.__doc__ = AbstractAsyncNetworkServer.serve_forever.__doc__

    async def __serve(
        self,
        server: lowlevel_datagram_server.AsyncDatagramServer[_RequestT, _ResponseT, tuple[Any, ...]],
        task_group: TaskGroup,
    ) -> NoReturn:
        async with contextlib.aclosing(server):
            await server.serve(self.__datagram_received_coroutine, task_group)

    async def __datagram_received_coroutine(
        self,
        address: tuple[Any, ...],
        server: lowlevel_datagram_server.AsyncDatagramServer[_RequestT, _ResponseT, tuple[Any, ...]],
    ) -> AsyncGenerator[None, _RequestT]:
        address = new_socket_address(address, server.extra(INETSocketAttribute.family))
        with self.__suppress_and_log_remaining_exception(client_address=address):
            send_locks_cache = self.__send_locks_cache[server]
            try:
                send_lock = send_locks_cache[address]
            except KeyError:
                send_locks_cache[address] = send_lock = self.__backend.create_lock()

            clients_cache = self.__clients_cache[server]
            try:
                client = clients_cache[address]
            except KeyError:
                clients_cache[address] = client = _ClientAPI(address, server, send_lock, self.__logger)

            async with contextlib.aclosing(self.__request_handler.handle(client)) as request_handler_generator:
                del client, send_lock
                try:
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    return

                action: _asyncgen.AsyncGenAction[None, _RequestT]
                while True:
                    try:
                        action = _asyncgen.SendAction((yield))
                    except BaseException as exc:
                        action = _asyncgen.ThrowAction(exc)
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        return
                    finally:
                        del action

    @contextlib.contextmanager
    def __suppress_and_log_remaining_exception(self, client_address: SocketAddress) -> Iterator[None]:
        try:
            try:
                yield
            except* ClientClosedError as excgrp:
                _utils.remove_traceback_frames_in_place(excgrp, 1)  # Removes the 'yield' frame just above
                self.__logger.warning(
                    "There have been attempts to do operation on closed client %s",
                    client_address,
                    exc_info=excgrp,
                )
        except Exception as exc:
            _utils.remove_traceback_frames_in_place(exc, 1)  # Removes the 'yield' frame just above
            self.__logger.error("-" * 40)
            self.__logger.error("Exception occurred during processing of request from %s", client_address, exc_info=exc)
            self.__logger.error("-" * 40)

    def get_addresses(self) -> Sequence[SocketAddress]:
        if (servers := self.__servers) is None:
            return ()
        return tuple(
            new_socket_address(server.extra(INETSocketAttribute.sockname), server.extra(INETSocketAttribute.family))
            for server in servers
            if not server.is_closing()
        )

    get_addresses.__doc__ = AbstractAsyncNetworkServer.get_addresses.__doc__

    def get_backend(self) -> AsyncBackend:
        return self.__backend

    get_backend.__doc__ = AbstractAsyncNetworkServer.get_backend.__doc__

    @property
    def sockets(self) -> Sequence[SocketProxy]:
        """The listeners sockets. Read-only attribute."""
        if (servers := self.__servers) is None:
            return ()
        return tuple(SocketProxy(server.extra(INETSocketAttribute.socket)) for server in servers)

    @property
    def logger(self) -> logging.Logger:
        """The server's logger."""
        return self.__logger


@final
class _ClientAPI(AsyncDatagramClient[_ResponseT]):
    __slots__ = (
        "__server_ref",
        "__socket_proxy",
        "__send_lock",
        "__address",
        "__h",
        "__logger",
    )

    def __init__(
        self,
        address: SocketAddress,
        server: lowlevel_datagram_server.AsyncDatagramServer[Any, _ResponseT, Any],
        send_lock: ILock,
        logger: logging.Logger,
    ) -> None:
        super().__init__()
        self.__server_ref: weakref.ref[lowlevel_datagram_server.AsyncDatagramServer[Any, _ResponseT, Any]] = weakref.ref(server)
        self.__socket_proxy: SocketProxy = SocketProxy(server.extra(INETSocketAttribute.socket))
        self.__h: int | None = None
        self.__send_lock: ILock = send_lock
        self.__logger: logging.Logger = logger
        self.__address: SocketAddress = address

    def __repr__(self) -> str:
        return f"<client with address {self.__address} at {id(self):#x}>"

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((_ClientAPI, self.__server_ref, self.__address, 0xFF))
        return h

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClientAPI):
            return NotImplemented
        return self.__server_ref == other.__server_ref and self.__address == other.__address

    def is_closing(self) -> bool:
        return (server := self.__server_ref()) is None or server.is_closing()

    async def send_packet(self, packet: _ResponseT, /) -> None:
        self.__logger.debug("A datagram will be sent to %s", self.__address)
        async with self.__send_lock:
            server = self.__check_closed()
            await server.send_packet_to(packet, self.__address)
            _utils.check_real_socket_state(self.__socket_proxy)
            self.__logger.debug("Datagram successfully sent to %s.", self.__address)

    def __check_closed(self) -> lowlevel_datagram_server.AsyncDatagramServer[Any, _ResponseT, Any]:
        server = self.__server_ref()
        if server is None or server.is_closing():
            raise ClientClosedError("Closed client")
        return server

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        server_ref = self.__server_ref()
        if server_ref is None:  # pragma: no cover
            return {}
        server = server_ref
        del server_ref
        return server.extra_attributes | {
            INETClientAttribute.socket: lambda: self.__socket_proxy,
            INETClientAttribute.local_address: lambda: new_socket_address(
                server.extra(INETSocketAttribute.sockname),
                server.extra(INETSocketAttribute.family),
            ),
            INETClientAttribute.remote_address: lambda: self.__address,
        }
