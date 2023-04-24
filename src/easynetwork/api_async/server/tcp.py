# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkServer"]

import contextlib as _contextlib
import logging as _logging
from collections import deque
from typing import TYPE_CHECKING, Any, AsyncGenerator, Generic, Literal, Mapping, Self, Sequence, TypeVar, final

from ...exceptions import ClientClosedError, StreamProtocolParseError
from ...protocol import StreamProtocol
from ...tools._utils import check_real_socket_state as _check_real_socket_state, concatenate_chunks as _concatenate_chunks
from ...tools.socket import (
    ACCEPT_CAPACITY_ERRNOS,
    ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
    MAX_STREAM_BUFSIZE,
    SocketAddress,
    SocketProxy,
    new_socket_address,
)
from ...tools.stream import StreamDataConsumer, StreamDataProducer
from ..backend.factory import AsyncBackendFactory
from .abc import AbstractAsyncNetworkServer
from .handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncStreamRequestHandler

if TYPE_CHECKING:
    from ..backend.abc import (
        AbstractAsyncBackend,
        AbstractAsyncListenerSocketAdapter,
        AbstractAsyncStreamSocketAdapter,
        AbstractTask,
        AbstractTaskGroup,
    )


logger = _logging.getLogger(__name__)


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AsyncTCPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__listeners",
        "__listener_addresses",
        "__protocol",
        "__request_handler",
        "__is_up",
        "__is_shutdown",
        "__max_recv_size",
        "__listener_tasks",
        "__mainloop_task",
        "__service_actions_interval",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        listeners: Sequence[AbstractAsyncListenerSocketAdapter],
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        max_recv_size: int | None = None,
        service_actions_interval: float = 0.1,
    ) -> None:
        super().__init__()

        if not listeners:
            raise OSError("empty listeners list")
        if max_recv_size is None:
            max_recv_size = MAX_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        assert isinstance(protocol, StreamProtocol)

        self.__service_actions_interval: float = max(service_actions_interval, 0)
        self.__backend: AbstractAsyncBackend = backend
        self.__listeners: tuple[AbstractAsyncListenerSocketAdapter, ...] | None = tuple(listeners)
        self.__listener_addresses: tuple[SocketAddress, ...] = tuple(
            new_socket_address(listener.get_local_address(), listener.socket().family) for listener in listeners
        )
        self.__protocol: StreamProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_up = self.__backend.create_event()
        self.__is_shutdown = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__max_recv_size: int = max_recv_size
        self.__listener_tasks: deque[AbstractTask[None]] = deque()
        self.__mainloop_task: AbstractTask[None] | None = None

    @classmethod
    async def listen(
        cls,
        host: str | None | Sequence[str],
        port: int,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        *,
        family: int = 0,
        backlog: int | None = None,
        reuse_port: bool = False,
        max_recv_size: int | None = None,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        service_actions_interval: float = 0.1,
    ) -> Self:
        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        if backlog is None:
            backlog = 100

        listeners: Sequence[AbstractAsyncListenerSocketAdapter] = await backend.create_tcp_listeners(
            host,
            port,
            family=family,
            backlog=backlog,
            reuse_port=reuse_port,
        )

        return cls(backend, listeners, protocol, request_handler, max_recv_size, service_actions_interval)

    def is_serving(self) -> bool:
        return self.__listeners is not None and self.__is_up.is_set()

    async def wait_for_server_to_be_up(self) -> Literal[True]:
        if not self.__is_up.is_set():
            if self.__listeners is None:
                raise RuntimeError("Closed server")
            await self.__is_up.wait()
        return True

    async def stop_listening(self) -> None:
        for listener_task in self.__listener_tasks:
            if not listener_task.done():
                listener_task.cancel()
        listeners: Sequence[AbstractAsyncListenerSocketAdapter] | None = self.__listeners
        if listeners is None:
            return
        self.__listeners = None
        async with _contextlib.AsyncExitStack() as exit_stack:
            for listener in listeners:
                exit_stack.push_async_callback(listener.abort)
                exit_stack.push_async_callback(listener.aclose)

    async def server_close(self) -> None:
        await self.stop_listening()

        if self.__mainloop_task is not None and not self.__mainloop_task.done():
            self.__mainloop_task.cancel()

        await self.__is_shutdown.wait()

    async def serve_forever(self) -> None:
        if (listeners := self.__listeners) is None:
            raise RuntimeError("Closed server")
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Server is already running")

        async with _contextlib.AsyncExitStack() as server_exit_stack:
            # Final teardown
            server_exit_stack.callback(logger.info, "Server stopped")
            server_exit_stack.push_async_callback(self.server_close)
            ###########

            # Wake up server
            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)
            ################

            # Initialize request handler
            await self.__request_handler.service_init(self.__backend)
            server_exit_stack.push_async_callback(self.__request_handler.service_quit)
            ############################

            # Setup task group
            server_exit_stack.callback(self.__listener_tasks.clear)
            task_group = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            for listener in listeners:
                self.__listener_tasks.append(task_group.start_soon(self.__listener_task, listener, task_group))
            logger.info("Start serving at %s", ", ".join(map(str, self.__listener_addresses)))
            #################

            # Server is up
            self.__is_up.set()
            server_exit_stack.callback(self.__is_up.clear)
            task_group.start_soon(self.__service_actions_task)
            ##############

            # Main loop
            self.__mainloop_task = task_group.start_soon(self.__backend.sleep_forever)
            try:
                await self.__mainloop_task.join()
            except self.__backend.get_cancelled_exc_class():
                try:
                    await self.stop_listening()
                finally:
                    raise
            finally:
                self.__mainloop_task = None

    async def __service_actions_task(self) -> None:
        request_handler = self.__request_handler
        backend = self.__backend
        while True:
            try:
                await request_handler.service_actions()
            except Exception:
                logger.exception("Error occured in request_handler.service_actions()")
            await backend.sleep(self.__service_actions_interval)

    async def __listener_task(self, listener: AbstractAsyncListenerSocketAdapter, task_group: AbstractTaskGroup) -> None:
        backend: AbstractAsyncBackend = self.__backend
        while True:
            try:
                client_socket = await listener.accept()
            except OSError as exc:
                import errno
                import os

                if exc.errno in ACCEPT_CAPACITY_ERRNOS:
                    logger.error(
                        "accept returned %s (%s); retrying in %s seconds",
                        errno.errorcode[exc.errno],
                        os.strerror(exc.errno),
                        ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
                        exc_info=True,
                    )
                    await backend.sleep(ACCEPT_CAPACITY_ERROR_SLEEP_TIME)
                else:
                    raise
            else:
                task_group.start_soon(self.__client_task, client_socket)
                del client_socket

    async def __client_task(self, socket: AbstractAsyncStreamSocketAdapter) -> None:
        async with _contextlib.AsyncExitStack() as client_exit_stack:
            client_exit_stack.push_async_callback(socket.abort)
            await client_exit_stack.enter_async_context(socket)

            request_handler = self.__request_handler
            backend = self.__backend
            address: SocketAddress = new_socket_address(socket.get_remote_address(), socket.socket().family)
            producer = StreamDataProducer(self.__protocol)
            consumer = StreamDataConsumer(self.__protocol)
            client = _ConnectedClientAPI(backend, socket, address, producer, request_handler)
            assert client.address == address

            client_exit_stack.callback(consumer.clear)
            client_exit_stack.callback(producer.clear)

            logger.info("Accepted new connection (address = %s)", address)

            if isinstance(request_handler, AsyncStreamRequestHandler):
                await request_handler.on_connection(client)
            await client_exit_stack.enter_async_context(_contextlib.aclosing(client))

            recv_bufsize: int = self.__max_recv_size

            try:
                while True:
                    data: bytes = await socket.recv(recv_bufsize)
                    if not data:  # Closed connection (EOF)
                        raise ConnectionAbortedError
                    logger.debug("Received %d bytes from %s", len(data), address)
                    consumer.feed(data)
                    del data

                    async with _contextlib.aclosing(self.__iter_received_packets(consumer, client)) as request_generator:
                        async for request in request_generator:
                            logger.debug("Processing request sent by %s", address)
                            await request_handler.handle(request, client)
                            del request
                            await backend.coro_yield()
                            if client.is_closing():
                                raise ClientClosedError
            except ConnectionError:
                return
            except OSError as exc:
                try:
                    await client.aclose()
                finally:
                    await self.__handle_error(client, exc)
                return
            except Exception as exc:
                await self.__handle_error(client, exc)
                return

    async def __iter_received_packets(
        self,
        consumer: StreamDataConsumer[_RequestT],
        client: AsyncClientInterface[_ResponseT],
    ) -> AsyncGenerator[_RequestT, None]:
        while True:
            try:
                for request in consumer:
                    yield request
                return
            except StreamProtocolParseError as exc:
                logger.debug("Malformed request sent by %s", client.address)
                await self.__request_handler.bad_request(client, exc.with_traceback(None))
                await self.__backend.coro_yield()

    async def __handle_error(self, client: AsyncClientInterface[_ResponseT], exc: Exception) -> None:
        try:
            if await self.__request_handler.handle_error(client, exc):
                return

            logger.error("-" * 40)
            logger.error("Exception occurred during processing of request from %s", client.address, exc_info=exc)
            logger.error("-" * 40)
        finally:
            del exc

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    def get_addresses(self) -> Sequence[SocketAddress]:
        return self.__listener_addresses


@final
class _ConnectedClientAPI(AsyncClientInterface[_ResponseT]):
    __slots__ = (
        "__socket",
        "__producer",
        "__request_handler",
        "__send_lock",
        "__proxy",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        socket: AbstractAsyncStreamSocketAdapter,
        address: SocketAddress,
        producer: StreamDataProducer[_ResponseT],
        request_handler: AsyncBaseRequestHandler[Any, Any],
    ) -> None:
        super().__init__(address)

        self.__socket: AbstractAsyncStreamSocketAdapter | None = socket
        self.__producer: StreamDataProducer[_ResponseT] = producer
        self.__send_lock = backend.create_lock()
        self.__proxy: SocketProxy = SocketProxy(socket.socket())
        self.__request_handler: AsyncBaseRequestHandler[Any, Any] = request_handler

    def is_closing(self) -> bool:
        socket = self.__socket
        return socket is None or socket.is_closing()

    async def aclose(self) -> None:
        async with self.__send_lock:
            socket = self.__socket
            if socket is None:
                return
            self.__socket = None
            request_handler = self.__request_handler
            with _contextlib.suppress(Exception):
                async with _contextlib.AsyncExitStack() as stack:
                    stack.callback(logger.info, "%s disconnected", self.address)
                    if isinstance(request_handler, AsyncStreamRequestHandler):
                        stack.push_async_callback(self.__send_lock.acquire)  # Re-acquire lock after calling on_disconnection()
                        stack.push_async_callback(request_handler.on_disconnection, self)
                        stack.callback(self.__send_lock.release)  # Release lock before calling on_disconnection()
                    stack.push_async_callback(socket.aclose)

    async def send_packet(self, packet: _ResponseT) -> None:
        self.__check_closed()
        logger.debug("A response will be sent to %s", self.address)
        self.__producer.queue(packet)
        async with self.__send_lock:
            socket = self.__check_closed()
            data: bytes = _concatenate_chunks(self.__producer)
            try:
                await socket.sendall(data)
                _check_real_socket_state(self.__proxy)
                nb_bytes_sent: int = len(data)
            finally:
                del data
            logger.debug("%d byte(s) sent to %s", nb_bytes_sent, self.address)

    def __check_closed(self) -> AbstractAsyncStreamSocketAdapter:
        socket = self.__socket
        if socket is None or socket.is_closing():
            raise ClientClosedError("Closed client")
        return socket

    @property
    def socket(self) -> SocketProxy:
        return self.__proxy
