# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkServer"]

import contextlib as _contextlib
import logging as _logging
from typing import TYPE_CHECKING, Any, Generic, Literal, Mapping, Self, Sequence, TypeVar, final

from ...api_sync.server.handler import BaseRequestHandler
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
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        listeners: Sequence[AbstractAsyncListenerSocketAdapter],
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] | BaseRequestHandler[_RequestT, _ResponseT],
    ) -> None:
        super().__init__()

        if not listeners:
            raise OSError("empty listeners list")

        assert isinstance(protocol, StreamProtocol)
        if isinstance(request_handler, BaseRequestHandler):
            from .sync_bridge import AsyncStreamRequestHandlerBridge

            request_handler = AsyncStreamRequestHandlerBridge(backend, request_handler)

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

    @classmethod
    async def listen(
        cls,
        host: str | None | Sequence[str],
        port: int,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] | BaseRequestHandler[_RequestT, _ResponseT],
        *,
        family: int = 0,
        backlog: int | None = None,
        reuse_port: bool = False,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
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

        return cls(backend, listeners, protocol, request_handler)

    def is_serving(self) -> bool:
        return self.__listeners is not None and self.__is_up.is_set()

    async def wait_for_server_to_be_up(self) -> Literal[True]:
        await self.__is_up.wait()
        return True

    async def server_close(self) -> None:
        listeners: Sequence[AbstractAsyncListenerSocketAdapter] | None = self.__listeners
        if listeners is None:
            return
        self.__listeners = None
        async with _contextlib.AsyncExitStack() as exit_stack:
            for listener in listeners:
                exit_stack.push_async_callback(listener.abort)

    async def serve_forever(self) -> None:
        if (listeners := self.__listeners) is None:
            raise RuntimeError("Closed server")
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Server is already running")

        async with _contextlib.AsyncExitStack() as server_exit_stack:
            # Final log
            server_exit_stack.callback(logger.info, "Server stopped")
            ###########

            # Wake up server
            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)
            ################

            # Initialize request handler
            await self.__request_handler.service_init()
            server_exit_stack.push_async_callback(self.__request_handler.service_quit)
            ############################

            # Setup task group
            task_group = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            for listener in listeners:
                task_group.start_soon(self.__listener_task, listener, task_group)
            logger.info("Start serving at %s", ", ".join(map(str, self.__listener_addresses)))
            #################

            # Server is up
            self.__is_up.set()
            server_exit_stack.callback(self.__is_up.clear)
            ##############

            # Main loop
            await self.__backend.sleep_forever()

    async def __listener_task(self, listener: AbstractAsyncListenerSocketAdapter, task_group: AbstractTaskGroup) -> None:
        backend: AbstractAsyncBackend = self.__backend
        async with listener:
            while True:
                try:
                    client_socket, client_address = await listener.accept()
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
                    task_group.start_soon(self.__client_task, client_socket, client_address)

    async def __client_task(self, socket: AbstractAsyncStreamSocketAdapter, address: tuple[Any, ...]) -> None:
        async with _contextlib.AsyncExitStack() as client_exit_stack:
            await client_exit_stack.enter_async_context(socket)
            client_exit_stack.push_async_callback(socket.abort)

            request_handler = self.__request_handler
            backend = self.__backend
            address = new_socket_address(address, socket.socket().family)
            producer = StreamDataProducer(self.__protocol)
            consumer = StreamDataConsumer(self.__protocol)
            client = _ConnectedClientAPI(backend, socket, address, producer, request_handler)

            client_exit_stack.callback(consumer.clear)
            client_exit_stack.callback(producer.clear)

            logger.info("Accepted new connection (address = %s)", address)

            if isinstance(request_handler, AsyncStreamRequestHandler):
                await request_handler.on_connection(client)
            client_exit_stack.push_async_callback(client.close)

            while True:
                data: bytes
                try:
                    data = await socket.recv(MAX_STREAM_BUFSIZE)
                    if not data:  # Closed connection (EOF)
                        raise ConnectionAbortedError
                except ConnectionError:
                    return
                except OSError as exc:
                    await self.__request_error_handling_and_close(client, exc, close_client_before=True)
                    return
                logger.debug("Received %d bytes from %s", len(data), address)
                consumer.feed(data)
                del data

                while True:
                    try:
                        try:
                            request: _RequestT = next(consumer)
                        except StopIteration:  # Not enough data
                            break
                        except StreamProtocolParseError as exc:
                            logger.debug("Malformed request sent by %s", address)
                            await request_handler.bad_request(client, exc.error_type, exc.message, exc.error_info)
                        else:
                            logger.debug("Processing request sent by %s", address)
                            await request_handler.handle(request, client)
                        if client.is_closing():
                            raise ClientClosedError
                    except ConnectionError:
                        return
                    except OSError as exc:
                        await self.__request_error_handling_and_close(client, exc, close_client_before=True)
                        return
                    except Exception as exc:
                        await self.__request_error_handling_and_close(client, exc, close_client_before=False)
                        return
                    finally:
                        await backend.coro_yield()

    async def __request_error_handling_and_close(
        self,
        client: AsyncClientInterface[Any],
        exc: Exception,
        *,
        close_client_before: bool,
    ) -> None:
        try:
            if close_client_before:
                try:
                    await client.close()
                finally:
                    await self.__handle_error(client, exc)
            else:
                try:
                    await self.__handle_error(client, exc)
                finally:
                    await client.close()
        finally:
            del exc

    async def __handle_error(self, client: AsyncClientInterface[Any], exc: Exception) -> None:
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

    async def close(self) -> None:
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
                    stack.push_async_callback(socket.close)

    async def send_packet(self, packet: _ResponseT) -> None:
        self.__check_closed()
        logger.debug("A response will be sent to %s", self.address)
        self.__producer.queue(packet)
        async with self.__send_lock:
            socket = self.__check_closed()
            data: bytes = _concatenate_chunks(self.__producer)
            try:
                await socket.sendall(data)
                nb_bytes_sent: int = len(data)
            finally:
                del data
            _check_real_socket_state(self.__proxy)
            logger.debug("%d byte(s) sent to %s", nb_bytes_sent, self.address)

    def __check_closed(self) -> AbstractAsyncStreamSocketAdapter:
        socket = self.__socket
        if socket is None or socket.is_closing():
            raise ClientClosedError("Closed client")
        return socket

    @property
    def socket(self) -> SocketProxy:
        return self.__proxy
