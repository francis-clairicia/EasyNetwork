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

from ..._typevars import _T_Request, _T_Response
from ...exceptions import ClientClosedError, ServerAlreadyRunning, ServerClosedError
from ...lowlevel import _asyncgen, _utils
from ...lowlevel._final import runtime_final_class
from ...lowlevel.api_async.backend.factory import current_async_backend
from ...lowlevel.api_async.servers import datagram as _datagram_server
from ...lowlevel.api_async.transports.abc import AsyncDatagramListener
from ...lowlevel.socket import INETSocketAttribute, SocketAddress, SocketProxy, new_socket_address
from ...protocol import DatagramProtocol
from .abc import AbstractAsyncNetworkServer, SupportsEventSet
from .handler import AsyncDatagramClient, AsyncDatagramRequestHandler, INETClientAttribute

if TYPE_CHECKING:
    from ...lowlevel.api_async.backend.abc import CancelScope, IEvent, ILock, Task, TaskGroup


class AsyncUDPNetworkServer(AbstractAsyncNetworkServer, Generic[_T_Request, _T_Response]):
    """
    An asynchronous network server for UDP communication.
    """

    __slots__ = (
        "__servers",
        "__server_families",
        "__listeners_factory",
        "__listeners_factory_scope",
        "__protocol",
        "__request_handler",
        "__is_shutdown",
        "__clients_cache",
        "__send_locks_cache",
        "__servers_tasks",
        "__server_run_scope",
        "__logger",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: DatagramProtocol[_T_Response, _T_Request],
        request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response],
        *,
        reuse_port: bool = False,
        logger: logging.Logger | None = None,
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
        """
        super().__init__()

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
        if not isinstance(request_handler, AsyncDatagramRequestHandler):
            raise TypeError(f"Expected an AsyncDatagramRequestHandler object, got {request_handler!r}")

        backend = current_async_backend()

        self.__listeners_factory: Callable[[], Coroutine[Any, Any, Sequence[AsyncDatagramListener[tuple[Any, ...]]]]] | None
        self.__listeners_factory = _utils.make_callback(
            backend.create_udp_listeners,
            host,
            port,
            reuse_port=reuse_port,
        )
        self.__listeners_factory_scope: CancelScope | None = None
        self.__server_run_scope: CancelScope | None = None

        self.__servers: tuple[_datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]], ...] | None
        self.__servers = None
        self.__protocol: DatagramProtocol[_T_Response, _T_Request] = protocol
        self.__request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response] = request_handler
        self.__is_shutdown: IEvent = backend.create_event()
        self.__is_shutdown.set()
        self.__servers_tasks: deque[Task[NoReturn]] = deque()
        self.__logger: logging.Logger = logger or logging.getLogger(__name__)
        self.__clients_cache: defaultdict[
            _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
            weakref.WeakValueDictionary[tuple[Any, ...], _ClientAPI[_T_Response]],
        ]
        self.__send_locks_cache: defaultdict[
            _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
            weakref.WeakValueDictionary[tuple[Any, ...], ILock],
        ]
        self.__clients_cache = defaultdict(weakref.WeakValueDictionary)
        self.__send_locks_cache = defaultdict(weakref.WeakValueDictionary)
        self.__server_families: dict[_datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]], int] = {}

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def is_serving(self) -> bool:
        return self.__servers is not None and all(not server.is_closing() for server in self.__servers)

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def server_close(self) -> None:
        if self.__listeners_factory_scope is not None:
            self.__listeners_factory_scope.cancel()
        self.__listeners_factory = None
        await self.__close_servers()

    async def __close_servers(self) -> None:
        async with contextlib.AsyncExitStack() as exit_stack:
            server_close_group = await exit_stack.enter_async_context(current_async_backend().create_task_group())

            servers, self.__servers = self.__servers, None
            if servers is not None:
                exit_stack.push_async_callback(current_async_backend().cancel_shielded_coro_yield)
                for server in servers:
                    exit_stack.callback(server_close_group.start_soon, server.aclose)
                    del server

            for server_task in self.__servers_tasks:
                server_task.cancel()
                exit_stack.push_async_callback(server_task.wait)
                del server_task

            if self.__server_run_scope is not None:
                self.__server_run_scope.cancel()

            await current_async_backend().cancel_shielded_coro_yield()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def shutdown(self) -> None:
        if self.__server_run_scope is not None:
            self.__server_run_scope.cancel()
        await self.__is_shutdown.wait()

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> None:
        async with contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")
            self.__is_shutdown = is_shutdown = current_async_backend().create_event()
            server_exit_stack.callback(is_shutdown.set)
            self.__server_run_scope = server_exit_stack.enter_context(current_async_backend().open_cancel_scope())

            def reset_scope() -> None:
                self.__server_run_scope = None

            server_exit_stack.callback(reset_scope)
            ################

            # Bind and activate
            assert self.__servers is None  # nosec assert_used
            assert self.__listeners_factory_scope is None  # nosec assert_used
            if self.__listeners_factory is None:
                raise ServerClosedError("Closed server")
            listeners: list[AsyncDatagramListener[tuple[Any, ...]]] = []
            try:
                with current_async_backend().open_cancel_scope() as self.__listeners_factory_scope:
                    await current_async_backend().coro_yield()
                    listeners.extend(await self.__listeners_factory())
                if self.__listeners_factory_scope.cancelled_caught():
                    raise ServerClosedError("Server has been closed during task setup")
            finally:
                self.__listeners_factory_scope = None
            if not listeners:
                raise OSError("empty listeners list")
            self.__servers = tuple(_datagram_server.AsyncDatagramServer(listener, self.__protocol) for listener in listeners)
            del listeners

            self.__server_families = {s: s.extra(INETSocketAttribute.family) for s in self.__servers}
            server_exit_stack.callback(self.__server_families.clear)
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
            task_group: TaskGroup = await server_exit_stack.enter_async_context(current_async_backend().create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            self.__servers_tasks.extend(
                [
                    await task_group.start(server.serve, self.__datagram_received_coroutine, task_group)
                    for server in self.__servers
                ]
            )
            self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
            #################

            # Server is up
            if is_up_event is not None:
                is_up_event.set()
            ##############

            # Main loop
            try:
                await current_async_backend().sleep_forever()
            finally:
                reset_scope()

    async def __datagram_received_coroutine(
        self,
        address: tuple[Any, ...],
        server: _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
    ) -> AsyncGenerator[None, _T_Request]:
        with self.__suppress_and_log_remaining_exception(address, server):
            request_handler_generator = self.__request_handler.handle(self.__get_client(server, address))
            async with contextlib.aclosing(request_handler_generator):
                try:
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    return

                action: _asyncgen.AsyncGenAction[None, _T_Request]
                while True:
                    try:
                        action = _asyncgen.SendAction((yield))
                    except BaseException as exc:
                        action = _asyncgen.ThrowAction(_utils.remove_traceback_frames_in_place(exc, 1))
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        return
                    except BaseException as exc:
                        # Remove action.asend() frames
                        _utils.remove_traceback_frames_in_place(exc, 2)
                        raise
                    finally:
                        del action

    @contextlib.contextmanager
    def __suppress_and_log_remaining_exception(
        self,
        client_address: tuple[Any, ...],
        server: _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
    ) -> Iterator[None]:
        try:
            try:
                yield
            except* ClientClosedError as excgrp:
                _utils.remove_traceback_frames_in_place(excgrp, 1)  # Removes the 'yield' frame just above
                self.__logger.warning(
                    "There have been attempts to do operation on closed client %s",
                    new_socket_address(client_address, self.__server_families[server]),
                    exc_info=excgrp,
                )
        except Exception as exc:
            _utils.remove_traceback_frames_in_place(exc, 1)  # Removes the 'yield' frame just above
            self.__logger.error("-" * 40)
            self.__logger.error(
                "Exception occurred during processing of request from %s",
                new_socket_address(client_address, self.__server_families[server]),
                exc_info=exc,
            )
            self.__logger.error("-" * 40)

    def __get_client_lock(
        self,
        server: _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
        address: tuple[Any, ...],
    ) -> ILock:
        send_locks_cache = self.__send_locks_cache[server]
        try:
            send_lock = send_locks_cache[address]
        except KeyError:
            send_locks_cache[address] = send_lock = current_async_backend().create_lock()
        return send_lock

    def __get_client(
        self,
        server: _datagram_server.AsyncDatagramServer[_T_Request, _T_Response, tuple[Any, ...]],
        address: tuple[Any, ...],
    ) -> _ClientAPI[_T_Response]:
        clients_cache = self.__clients_cache[server]
        try:
            client = clients_cache[address]
        except KeyError:
            clients_cache[address] = client = _ClientAPI(address, server, self.__get_client_lock(server, address))
        return client

    @_utils.inherit_doc(AbstractAsyncNetworkServer)
    def get_addresses(self) -> Sequence[SocketAddress]:
        if (servers := self.__servers) is None:
            return ()
        return tuple(
            new_socket_address(server.extra(INETSocketAttribute.sockname), server.extra(INETSocketAttribute.family))
            for server in servers
            if not server.is_closing()
        )

    def get_sockets(self) -> Sequence[SocketProxy]:
        """Gets the listeners sockets.

        Returns:
            a read-only sequence of :class:`.SocketProxy` objects.

            If the server is not running, an empty sequence is returned.
        """
        if (servers := self.__servers) is None:
            return ()
        return tuple(SocketProxy(server.extra(INETSocketAttribute.socket)) for server in servers)


@final
@runtime_final_class
class _ClientAPI(AsyncDatagramClient[_T_Response]):
    __slots__ = (
        "__server",
        "__send_lock",
        "__address",
        "__h",
        "__extra_attributes_cache",
    )

    def __init__(
        self,
        address: tuple[Any, ...],
        server: _datagram_server.AsyncDatagramServer[Any, _T_Response, Any],
        send_lock: ILock,
    ) -> None:
        super().__init__()
        self.__server: _datagram_server.AsyncDatagramServer[Any, _T_Response, Any] = server
        self.__h: int | None = None
        self.__send_lock: ILock = send_lock
        self.__address: tuple[Any, ...] = address
        self.__extra_attributes_cache: Mapping[Any, Callable[[], Any]] | None = None

    def __repr__(self) -> str:
        return f"<client with address {self.__address} at {id(self):#x}>"

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((_ClientAPI, self.__server, self.__address, 0xFF))
        return h

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClientAPI):
            return NotImplemented
        return self.__server == other.__server and self.__address == other.__address

    def is_closing(self) -> bool:
        return self.__server.is_closing()

    async def send_packet(self, packet: _T_Response, /) -> None:
        async with self.__send_lock:
            server = self.__server
            if server.is_closing():
                raise ClientClosedError("Closed client")
            await server.send_packet_to(packet, self.__address)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        if (extra_attributes_cache := self.__extra_attributes_cache) is not None:
            return extra_attributes_cache
        server = self.__server
        self.__extra_attributes_cache = extra_attributes_cache = {
            **server.extra_attributes,
            INETClientAttribute.socket: lambda: SocketProxy(server.extra(INETSocketAttribute.socket)),
            INETClientAttribute.local_address: lambda: new_socket_address(
                server.extra(INETSocketAttribute.sockname),
                server.extra(INETSocketAttribute.family),
            ),
            INETClientAttribute.remote_address: lambda: new_socket_address(
                self.__address,
                server.extra(INETSocketAttribute.family),
            ),
        }
        return extra_attributes_cache
