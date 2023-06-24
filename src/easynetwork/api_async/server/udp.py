# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncUDPNetworkServer"]

import contextlib as _contextlib
import logging as _logging
from collections import Counter, deque
from typing import TYPE_CHECKING, Any, AsyncGenerator, AsyncIterator, Callable, Generic, Iterator, Mapping, TypeVar, final
from weakref import WeakValueDictionary

from ...exceptions import ClientClosedError, DatagramProtocolParseError
from ...protocol import DatagramProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    recursively_clear_exception_traceback_frames as _recursively_clear_exception_traceback_frames,
)
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from .abc import AbstractAsyncNetworkServer
from .handler import AsyncBaseRequestHandler, AsyncClientInterface

if TYPE_CHECKING:
    from ..backend.abc import (
        AbstractAsyncBackend,
        AbstractAsyncDatagramSocketAdapter,
        AbstractTask,
        AbstractTaskGroup,
        ICondition,
        IEvent,
        ILock,
    )


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AsyncUDPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__socket",
        "__socket_factory",
        "__protocol",
        "__request_handler",
        "__is_shutdown",
        "__shutdown_asked",
        "__sendto_lock",
        "__client_manager",
        "__client_datagram_queue",
        "__mainloop_task",
        "__service_actions_interval",
        "__logger",
    )

    def __init__(
        self,
        host: str | None,
        port: int,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        *,
        reuse_port: bool = False,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        service_actions_interval: float | None = None,
        logger: _logging.Logger | None = None,
    ) -> None:
        super().__init__()

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        assert isinstance(protocol, DatagramProtocol)

        self.__socket_factory: SingleTaskRunner[AbstractAsyncDatagramSocketAdapter] | None
        self.__socket_factory = SingleTaskRunner(
            backend,
            backend.create_udp_endpoint,
            local_address=(host, port),
            remote_address=None,
            reuse_port=reuse_port,
        )

        if service_actions_interval is None:
            service_actions_interval = 0.1

        self.__service_actions_interval: float = max(service_actions_interval, 0)
        self.__backend: AbstractAsyncBackend = backend
        self.__socket: AbstractAsyncDatagramSocketAdapter | None = None
        self.__protocol: DatagramProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_shutdown: IEvent = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__shutdown_asked: bool = False
        self.__sendto_lock: ILock = backend.create_lock()
        self.__mainloop_task: AbstractTask[None] | None = None
        self.__logger: _logging.Logger = logger or _logging.getLogger(__name__)
        self.__client_manager: _ClientAPIManager[_ResponseT] = _ClientAPIManager(
            self.__backend,
            self.__protocol,
            self.__sendto_lock,
            self.__logger,
        )
        self.__client_datagram_queue: dict[_ClientAPI[_ResponseT], deque[bytes]] = {}

    def is_serving(self) -> bool:
        return self.__socket is not None

    async def server_close(self) -> None:
        if self.__socket_factory is not None:
            self.__socket_factory.cancel()
            self.__socket_factory = None
        self.__stop_mainloop()
        await self.__close_socket()

    async def __close_socket(self) -> None:
        async with self.__sendto_lock:
            socket, self.__socket = self.__socket, None
            if socket is None:
                return
            await socket.aclose()

    async def shutdown(self) -> None:
        self.__stop_mainloop()
        self.__shutdown_asked = True
        try:
            await self.__is_shutdown.wait()
        finally:
            self.__shutdown_asked = False

    def __stop_mainloop(self) -> None:
        if self.__mainloop_task is not None:
            self.__mainloop_task.cancel()
            self.__mainloop_task = None

    async def serve_forever(self, *, is_up_event: IEvent | None = None) -> None:
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Server is already running")

        async with _contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)
            if is_up_event is not None:
                # Force is_up_event to be set, in order not to stuck the waiting task
                server_exit_stack.callback(is_up_event.set)
            ################

            # Bind and activate
            assert self.__socket is None
            if self.__socket_factory is None:
                raise RuntimeError("Closed server")
            self.__socket = await self.__socket_factory.run()
            self.__socket_factory = None
            ###################

            # Final teardown
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            server_exit_stack.push_async_callback(lambda: self.__backend.ignore_cancellation(self.server_close()))
            ################

            # Initialize request handler
            self.__request_handler.set_async_backend(self.__backend)
            await self.__request_handler.service_init()
            server_exit_stack.callback(self.__client_manager.clear)
            server_exit_stack.push_async_callback(self.__request_handler.service_quit)
            server_exit_stack.push_async_callback(self.__close_socket)
            ############################

            # Setup task group
            task_group: AbstractTaskGroup = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable socket
            self.__logger.info("Start serving at %s", self.get_address())
            #################

            # Server is up
            if is_up_event is not None:
                is_up_event.set()
            task_group.start_soon(self.__service_actions_task)
            ##############

            # Main loop
            self.__mainloop_task = task_group.start_soon(self.__receive_datagrams_task, self.__socket, task_group)
            if self.__shutdown_asked:
                self.__mainloop_task.cancel()
            try:
                await self.__mainloop_task.join()
            finally:
                self.__mainloop_task = None

    async def __receive_datagrams_task(
        self,
        socket: AbstractAsyncDatagramSocketAdapter,
        task_group: AbstractTaskGroup,
    ) -> None:
        socket_family: int = socket.socket().family
        datagram_received_task = self.__datagram_received_task
        logger = self.__logger
        while True:
            datagram, client_address = await socket.recvfrom()
            client_address = new_socket_address(client_address, socket_family)
            logger.debug("Received a datagram from %s", client_address)
            task_group.start_soon(datagram_received_task, socket, datagram, client_address, task_group)
            del datagram, client_address

    async def __service_actions_task(self) -> None:
        request_handler = self.__request_handler
        backend = self.__backend
        if self.__service_actions_interval == float("+inf"):
            return
        while True:
            await backend.sleep(self.__service_actions_interval)
            try:
                await request_handler.service_actions()
            except Exception:
                self.__logger.exception("Error occurred in request_handler.service_actions()")

    async def __datagram_received_task(
        self,
        socket: AbstractAsyncDatagramSocketAdapter,
        datagram: bytes,
        client_address: SocketAddress,
        task_group: AbstractTaskGroup,
    ) -> None:
        client = self.__client_manager.get(socket, client_address)
        backend = self.__backend

        async with self.__client_manager.lock(client) as condition:
            datagram_queue: deque[bytes] | None = self.__client_datagram_queue.get(client)
            if datagram_queue is not None:
                datagram_queue.append(datagram)
                condition.notify()
                del client
                return
            request_handler_generator: AsyncGenerator[None, _RequestT] | None = None
            datagram_queue = deque()  # Add datagram after creating the generator
            with self.__suppress_and_log_remaining_exception(client_address):
                try:
                    request_handler_generator = await self.__new_request_handler(client)
                    datagram_queue.append(datagram)
                    while True:
                        if not datagram_queue:
                            self.__client_datagram_queue[client] = datagram_queue
                            try:
                                await condition.wait()
                            finally:
                                del self.__client_datagram_queue[client]
                            assert len(datagram_queue) > 0, f"{len(datagram_queue)=}"
                        datagram = datagram_queue.popleft()
                        try:
                            request: _RequestT = self.__protocol.build_packet_from_datagram(datagram)
                        except DatagramProtocolParseError as exc:
                            self.__logger.debug("Malformed request sent by %s", client.address)
                            try:
                                _recursively_clear_exception_traceback_frames(exc)
                            except RecursionError:
                                self.__logger.warning("Recursion depth reached when clearing exception's traceback frames")
                            await self.__request_handler.bad_request(client, exc)
                            await backend.coro_yield()
                            continue
                        finally:
                            del datagram

                        self.__logger.debug("Processing request sent by %s", client.address)
                        try:
                            await request_handler_generator.asend(request)
                        except StopAsyncIteration:
                            request_handler_generator = None
                            return
                        except BaseException:
                            request_handler_generator = None
                            raise
                        finally:
                            del request
                        await backend.coro_yield()
                except (Exception, self.__backend.get_cancelled_exc_class()) as exc:
                    await self.__throw_error(request_handler_generator, exc)
                    raise
                finally:
                    del client
                    async with (
                        _contextlib.aclosing(request_handler_generator)
                        if request_handler_generator is not None
                        else _contextlib.nullcontext()
                    ):
                        datagram_received_task = self.__datagram_received_task
                        for datagram in datagram_queue:
                            task_group.start_soon(datagram_received_task, socket, datagram, client_address, task_group)

    async def __new_request_handler(self, client: AsyncClientInterface[_ResponseT]) -> AsyncGenerator[None, _RequestT]:
        request_handler_generator = self.__request_handler.handle(client)
        try:
            await anext(request_handler_generator)
        except StopAsyncIteration:
            raise RuntimeError("request_handler.handle() async generator did not yield") from None
        return request_handler_generator

    async def __throw_error(self, request_handler_generator: AsyncGenerator[None, _RequestT] | None, exc: BaseException) -> None:
        try:
            if request_handler_generator is not None:
                with _contextlib.suppress(StopAsyncIteration):
                    await request_handler_generator.athrow(exc)
        finally:
            del exc

    @_contextlib.contextmanager
    def __suppress_and_log_remaining_exception(self, client_address: SocketAddress) -> Iterator[None]:
        try:
            yield
        except Exception:
            self.__logger.error("-" * 40)
            self.__logger.exception("Exception occurred during processing of request from %s", client_address)
            self.__logger.error("-" * 40)

    def get_address(self) -> SocketAddress | None:
        if (socket := self.__socket) is None or socket.is_closing():
            return None
        return new_socket_address(socket.get_local_address(), socket.socket().family)

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    def get_protocol(self) -> DatagramProtocol[_ResponseT, _RequestT]:
        return self.__protocol

    @property
    def socket(self) -> SocketProxy | None:
        if (socket := self.__socket) is None:
            return None
        return SocketProxy(socket.socket())

    @property
    def logger(self) -> _logging.Logger:
        return self.__logger


class _ClientAPIManager(Generic[_ResponseT]):
    __slots__ = (
        "__clients",
        "__per_client_lock",
        "__per_client_lock_count",
        "__backend",
        "__protocol",
        "__send_lock",
        "__logger",
        "__weakref__",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        protocol: DatagramProtocol[_ResponseT, Any],
        send_lock: ILock,
        logger: _logging.Logger,
    ) -> None:
        super().__init__()

        self.__clients: WeakValueDictionary[tuple[AbstractAsyncDatagramSocketAdapter, SocketAddress], _ClientAPI[_ResponseT]]
        self.__clients = WeakValueDictionary()
        self.__backend: AbstractAsyncBackend = backend
        self.__protocol: DatagramProtocol[_ResponseT, Any] = protocol
        self.__send_lock: ILock = send_lock
        self.__logger: _logging.Logger = logger
        self.__per_client_lock: dict[_ClientAPI[_ResponseT], ICondition] = {}
        self.__per_client_lock_count: Counter[_ClientAPI[_ResponseT]] = Counter()

    def clear(self) -> None:
        self.__clients.clear()

    def get(self, socket: AbstractAsyncDatagramSocketAdapter, address: SocketAddress) -> _ClientAPI[_ResponseT]:
        key = (socket, address)
        try:
            return self.__clients[key]
        except KeyError:
            client = _ClientAPI(self.__backend, address, socket, self.__protocol, self.__send_lock, self.__logger)
            self.__clients[key] = client
            return client

    @_contextlib.asynccontextmanager
    async def lock(self, client: _ClientAPI[_ResponseT]) -> AsyncIterator[ICondition]:
        condition = self.__per_client_lock.get(client)
        if condition is None:
            self.__per_client_lock[client] = condition = self.__backend.create_condition_var()
        self.__per_client_lock_count[client] += 1
        try:
            async with condition:
                yield condition
        finally:
            self.__per_client_lock_count[client] -= 1
            assert self.__per_client_lock_count[client] >= 0, f"{self.__per_client_lock_count[client]=}"
            if self.__per_client_lock_count[client] == 0:
                del self.__per_client_lock_count[client], self.__per_client_lock[client]
            del client


@final
class _ClientAPI(AsyncClientInterface[_ResponseT]):
    __slots__ = (
        "__backend",
        "__socket_ref",
        "__socket_proxy",
        "__protocol",
        "__send_lock",
        "__h",
        "__logger",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        address: SocketAddress,
        socket: AbstractAsyncDatagramSocketAdapter,
        protocol: DatagramProtocol[_ResponseT, Any],
        send_lock: ILock,
        logger: _logging.Logger,
    ) -> None:
        super().__init__(address)

        import weakref

        self.__backend: AbstractAsyncBackend = backend
        self.__socket_ref: Callable[[], AbstractAsyncDatagramSocketAdapter | None] = weakref.ref(socket)
        self.__socket_proxy: SocketProxy = SocketProxy(socket.socket())
        self.__h: int | None = None
        self.__protocol: DatagramProtocol[_ResponseT, Any] = protocol
        self.__send_lock: ILock = send_lock
        self.__logger: _logging.Logger = logger

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((_ClientAPI, self.address, 0xFF))
        return h

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClientAPI):
            return NotImplemented
        return self.address == other.address

    def is_closing(self) -> bool:
        return (socket := self.__socket_ref()) is None or socket.is_closing()

    async def aclose(self) -> None:
        await self.__backend.coro_yield()

    async def send_packet(self, packet: _ResponseT, /) -> None:
        async with self.__send_lock:
            socket = self.__check_closed()
            datagram: bytes = self.__protocol.make_datagram(packet)
            try:
                del packet
                self.__logger.debug("A datagram will be sent to %s", self.address)
                await socket.sendto(datagram, self.address)
                _check_real_socket_state(self.socket)
                self.__logger.debug("Datagram successfully sent to %s.", self.address)
            finally:
                del datagram

    def __check_closed(self) -> AbstractAsyncDatagramSocketAdapter:
        socket = self.__socket_ref()
        if socket is None or socket.is_closing():
            raise ClientClosedError("Closed client")
        return socket

    @property
    def socket(self) -> SocketProxy:
        return self.__socket_proxy
