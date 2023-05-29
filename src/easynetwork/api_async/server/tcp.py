# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = ["AsyncTCPNetworkServer"]

import contextlib as _contextlib
import errno as _errno
import logging as _logging
from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Generic,
    Iterator,
    Literal,
    Mapping,
    Sequence,
    TypeVar,
    final,
)

from ...exceptions import ClientClosedError, StreamProtocolParseError
from ...protocol import StreamProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    concatenate_chunks as _concatenate_chunks,
    set_tcp_nodelay as _set_tcp_nodelay,
)
from ...tools.socket import (
    ACCEPT_CAPACITY_ERRNOS,
    ACCEPT_CAPACITY_ERROR_SLEEP_TIME,
    MAX_STREAM_BUFSIZE,
    SSL_HANDSHAKE_TIMEOUT,
    SSL_SHUTDOWN_TIMEOUT,
    SocketAddress,
    SocketProxy,
    new_socket_address,
)
from ...tools.stream import StreamDataConsumer, StreamDataProducer
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from .abc import AbstractAsyncNetworkServer
from .handler import AsyncBaseRequestHandler, AsyncClientInterface, AsyncStreamRequestHandler

if TYPE_CHECKING:
    from ssl import SSLContext as _SSLContext

    from ..backend.abc import (
        AbstractAcceptedSocket,
        AbstractAsyncBackend,
        AbstractAsyncListenerSocketAdapter,
        AbstractAsyncStreamSocketAdapter,
        AbstractTask,
        AbstractTaskGroup,
    )


_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AsyncTCPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__listeners",
        "__listeners_factory",
        "__protocol",
        "__request_handler",
        "__is_up",
        "__is_shutdown",
        "__shutdown_asked",
        "__max_recv_size",
        "__listener_tasks",
        "__mainloop_task",
        "__service_actions_interval",
        "__logger",
    )

    def __init__(
        self,
        host: str | None | Sequence[str],
        port: int,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        *,
        ssl: _SSLContext | None = None,
        ssl_handshake_timeout: float | None = None,
        ssl_shutdown_timeout: float | None = None,
        family: int = 0,
        backlog: int | None = None,
        reuse_port: bool = False,
        max_recv_size: int | None = None,
        service_actions_interval: float = 0.1,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        logger: _logging.Logger | None = None,
    ) -> None:
        super().__init__()

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        if backlog is None:
            backlog = 100

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if ssl_shutdown_timeout is not None and not ssl:
            raise ValueError("ssl_shutdown_timeout is only meaningful with ssl")

        def _value_or_default(value: float | None, default: float) -> float:
            return value if value is not None else default

        self.__listeners_factory: SingleTaskRunner[Sequence[AbstractAsyncListenerSocketAdapter]] | None
        if ssl:
            self.__listeners_factory = SingleTaskRunner(
                backend,
                backend.create_ssl_over_tcp_listeners,
                host,
                port,
                backlog=backlog,
                ssl_context=ssl,
                ssl_handshake_timeout=_value_or_default(ssl_handshake_timeout, SSL_HANDSHAKE_TIMEOUT),
                ssl_shutdown_timeout=_value_or_default(ssl_shutdown_timeout, SSL_SHUTDOWN_TIMEOUT),
                family=family,
                reuse_port=reuse_port,
            )
        else:
            self.__listeners_factory = SingleTaskRunner(
                backend,
                backend.create_tcp_listeners,
                host,
                port,
                backlog=backlog,
                family=family,
                reuse_port=reuse_port,
            )
        if max_recv_size is None:
            max_recv_size = MAX_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        assert isinstance(protocol, StreamProtocol)

        self.__service_actions_interval: float = max(service_actions_interval, 0)
        self.__backend: AbstractAsyncBackend = backend
        self.__listeners: tuple[AbstractAsyncListenerSocketAdapter, ...] | None = None
        self.__protocol: StreamProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__is_up = self.__backend.create_event()
        self.__is_shutdown = self.__backend.create_event()
        self.__is_shutdown.set()
        self.__shutdown_asked: bool = False
        self.__max_recv_size: int = max_recv_size
        self.__listener_tasks: deque[AbstractTask[None]] = deque()
        self.__mainloop_task: AbstractTask[None] | None = None
        self.__logger: _logging.Logger = logger or _logging.getLogger(__name__)

    def is_serving(self) -> bool:
        return self.__listeners is not None and all(not listener.is_closing() for listener in self.__listeners)

    async def wait_for_server_to_be_up(self) -> Literal[True]:
        if not self.__is_up.is_set():
            if self.__listeners is None and self.__listeners_factory is None:
                raise RuntimeError("Closed server")
            await self.__is_up.wait()
        return True

    def stop_listening(self) -> None:
        with _contextlib.ExitStack() as exit_stack:
            for listener_task in self.__listener_tasks:
                exit_stack.callback(listener_task.cancel)
            self.__listener_tasks.clear()

    async def server_close(self) -> None:
        if self.__listeners_factory is not None:
            self.__listeners_factory.cancel()
            self.__listeners_factory = None
        listeners: Sequence[AbstractAsyncListenerSocketAdapter] | None = self.__listeners
        if listeners is None:
            return
        self.stop_listening()
        await self.__backend.coro_yield()
        async with _contextlib.AsyncExitStack() as exit_stack:
            for listener in listeners:
                exit_stack.push_async_callback(listener.aclose)

    async def shutdown(self) -> None:
        if self.__mainloop_task is not None:
            self.__mainloop_task.cancel()
            self.__mainloop_task = None
        self.__shutdown_asked = True
        try:
            await self.__is_shutdown.wait()
        finally:
            self.__shutdown_asked = False

    async def serve_forever(self) -> None:
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Server is already running")

        async with _contextlib.AsyncExitStack() as server_exit_stack:
            # Wake up server
            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)
            ################

            # Bind and activate
            assert self.__listeners is None
            if self.__listeners_factory is None:
                raise RuntimeError("Closed server")
            self.__listeners = tuple(await self.__listeners_factory.run())
            self.__listeners_factory = None
            if not self.__listeners:
                self.__listeners = None
                raise OSError("empty listeners list")
            ###################

            # Final teardown
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            server_exit_stack.push_async_callback(self.server_close)
            ###########

            # Initialize request handler
            await self.__request_handler.service_init(self.__backend)
            server_exit_stack.push_async_callback(self.__request_handler.service_quit)
            if isinstance(self.__request_handler, AsyncStreamRequestHandler):
                self.__request_handler.set_stop_listening_callback(self.__make_stop_listening_callback())
            ############################

            # Setup task group
            server_exit_stack.callback(self.__listener_tasks.clear)
            task_group = await server_exit_stack.enter_async_context(self.__backend.create_task_group())
            server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for remaining tasks...")
            ##################

            # Enable listener
            addresses: list[SocketAddress] = []
            for listener in self.__listeners:
                self.__listener_tasks.append(task_group.start_soon(self.__listener_task, listener, task_group))
                addresses.append(new_socket_address(listener.get_local_address(), listener.socket().family))
            self.__logger.info("Start serving at %s", ", ".join(map(str, addresses)))
            del addresses
            #################

            # Server is up
            self.__is_up.set()
            server_exit_stack.callback(self.__is_up.clear)
            task_group.start_soon(self.__service_actions_task)
            ##############

            # Main loop
            self.__mainloop_task = task_group.start_soon(self.__backend.sleep_forever)
            if self.__shutdown_asked:
                self.__mainloop_task.cancel()
            try:
                await self.__mainloop_task.join()
            except self.__backend.get_cancelled_exc_class():
                try:
                    self.stop_listening()
                finally:
                    raise
            finally:
                self.__mainloop_task = None

    def __make_stop_listening_callback(self) -> Callable[[], None]:
        import weakref

        selfref = weakref.ref(self)

        def stop_listening() -> None:
            self = selfref()
            return self.stop_listening() if self is not None else None

        return stop_listening

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

    async def __listener_task(self, listener: AbstractAsyncListenerSocketAdapter, task_group: AbstractTaskGroup) -> None:
        backend: AbstractAsyncBackend = self.__backend
        client_task = self.__client_task
        async with listener:
            while not listener.is_closing():
                try:
                    client_socket: AbstractAcceptedSocket = await listener.accept()
                except OSError as exc:
                    import errno
                    import os

                    if exc.errno in ACCEPT_CAPACITY_ERRNOS:
                        self.__logger.error(
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
                    task_group.start_soon(client_task, client_socket)
                    del client_socket

    async def __client_task(self, accepted_socket: AbstractAcceptedSocket) -> None:
        async with _contextlib.AsyncExitStack() as client_exit_stack:
            client_exit_stack.enter_context(self.__suppress_and_log_remaining_exception())
            client_exit_stack.enter_context(self.__suppress_ignorable_socket_errors())

            try:
                socket: AbstractAsyncStreamSocketAdapter = await accepted_socket.connect()
            finally:
                del accepted_socket

            await client_exit_stack.enter_async_context(socket)

            logger: _logging.Logger = self.__logger
            backend = self.__backend
            producer = StreamDataProducer(self.__protocol)
            consumer = StreamDataConsumer(self.__protocol)
            client = _ConnectedClientAPI(backend, socket, producer, self.__request_handler, logger)
            request_receiver = _RequestReceiver(
                backend,
                consumer,
                socket,
                self.__max_recv_size,
                client,
                self.__request_handler,
                logger,
            )

            client_exit_stack.callback(consumer.clear)
            client_exit_stack.callback(producer.clear)

            _set_tcp_nodelay(client.socket)

            logger.info("Accepted new connection (address = %s)", client.address)

            if isinstance(self.__request_handler, AsyncStreamRequestHandler):
                await self.__request_handler.on_connection(client)
            await client_exit_stack.enter_async_context(_contextlib.aclosing(client))

            request_handler_generator: AsyncGenerator[None, _RequestT] | None = None
            try:
                request_handler_generator = await self.__new_request_handler(client)
                async for request in request_receiver:
                    logger.debug("Processing request sent by %s", client.address)
                    try:
                        await request_handler_generator.asend(request)
                    except StopAsyncIteration:
                        request_handler_generator = None
                    except BaseException:
                        request_handler_generator = None
                        raise
                    finally:
                        del request
                    await backend.coro_yield()
                    if client.is_closing():
                        raise ClientClosedError
                    if request_handler_generator is None:
                        request_handler_generator = await self.__new_request_handler(client)
            except ConnectionError:
                return
            except OSError as exc:
                try:
                    await client.aclose()
                finally:
                    await self.__handle_error(request_handler_generator, client, exc)
                return
            except Exception as exc:
                await self.__handle_error(request_handler_generator, client, exc)
                return
            finally:
                if request_handler_generator is not None:
                    await request_handler_generator.aclose()

    async def __new_request_handler(self, client: AsyncClientInterface[_ResponseT]) -> AsyncGenerator[None, _RequestT]:
        request_handler_generator = self.__request_handler.handle(client)
        try:
            await anext(request_handler_generator)
        except StopAsyncIteration:
            raise RuntimeError("request_handler.handle() async generator did not yield") from None
        return request_handler_generator

    async def __handle_error(
        self,
        request_handler_generator: AsyncGenerator[None, _RequestT] | None,
        client: AsyncClientInterface[_ResponseT],
        exc: Exception,
    ) -> None:
        try:
            if request_handler_generator is not None:
                try:
                    await request_handler_generator.athrow(exc)
                except StopAsyncIteration:  # Clean shutdown, do not log
                    return
                except ConnectionError:
                    pass
                except Exception as _:
                    exc = _

            self.__logger.error("-" * 40)
            self.__logger.error("Exception occurred during processing of request from %s", client.address, exc_info=exc)
            self.__logger.error("-" * 40)
        finally:
            del exc

    @_contextlib.contextmanager
    def __suppress_ignorable_socket_errors(self) -> Iterator[None]:
        try:
            yield
        except ConnectionError:
            return
        except OSError as exc:
            if exc.errno not in {_errno.ENOTCONN, _errno.ENOTSOCK}:
                self.__logger.exception("Error in client task")
            return

    @_contextlib.contextmanager
    def __suppress_and_log_remaining_exception(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            self.__logger.exception("Error in client task")
            return

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

    def get_protocol(self) -> StreamProtocol[_ResponseT, _RequestT]:
        return self.__protocol

    @property
    def sockets(self) -> Sequence[SocketProxy]:
        if (listeners := self.__listeners) is None:
            return ()
        return tuple(SocketProxy(listener.socket()) for listener in listeners)

    @property
    def logger(self) -> _logging.Logger:
        return self.__logger


class _RequestReceiver(Generic[_RequestT, _ResponseT]):
    __slots__ = ("__backend", "__consumer", "__socket", "__max_recv_size", "__api", "__request_handler", "__logger")

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        consumer: StreamDataConsumer[_RequestT],
        socket: AbstractAsyncStreamSocketAdapter,
        max_recv_size: int,
        api: _ConnectedClientAPI[Any],
        request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT],
        logger: _logging.Logger,
    ) -> None:
        assert max_recv_size > 0, f"{max_recv_size=}"
        self.__backend: AbstractAsyncBackend = backend
        self.__consumer: StreamDataConsumer[_RequestT] = consumer
        self.__socket: AbstractAsyncStreamSocketAdapter = socket
        self.__max_recv_size: int = max_recv_size
        self.__api: _ConnectedClientAPI[Any] = api
        self.__request_handler: AsyncBaseRequestHandler[_RequestT, _ResponseT] = request_handler
        self.__logger: _logging.Logger = logger

    def __aiter__(self) -> AsyncIterator[_RequestT]:
        return self

    async def __anext__(self) -> _RequestT:
        consumer: StreamDataConsumer[_RequestT] = self.__consumer
        socket: AbstractAsyncStreamSocketAdapter = self.__socket
        client: _ConnectedClientAPI[Any] = self.__api
        logger: _logging.Logger = self.__logger
        while True:
            try:
                return next(consumer)
            except StreamProtocolParseError as exc:
                logger.debug("Malformed request sent by %s", client.address)
                await self.__request_handler.bad_request(client, exc.with_traceback(None))
                await self.__backend.coro_yield()
                continue
            except StopIteration:
                pass
            data: bytes = await socket.recv(self.__max_recv_size) if not socket.is_closing() else b""
            if not data:  # Closed connection (EOF)
                break
            logger.debug("Received %d bytes from %s", len(data), client.address)
            consumer.feed(data)
            del data
        raise StopAsyncIteration


@final
class _ConnectedClientAPI(AsyncClientInterface[_ResponseT]):
    __slots__ = (
        "__socket",
        "__producer",
        "__request_handler",
        "__send_lock",
        "__proxy",
        "__logger",
    )

    def __init__(
        self,
        backend: AbstractAsyncBackend,
        socket: AbstractAsyncStreamSocketAdapter,
        producer: StreamDataProducer[_ResponseT],
        request_handler: AsyncBaseRequestHandler[Any, Any],
        logger: _logging.Logger,
    ) -> None:
        super().__init__(new_socket_address(socket.get_remote_address(), socket.socket().family))

        self.__socket: AbstractAsyncStreamSocketAdapter | None = socket
        self.__producer: StreamDataProducer[_ResponseT] = producer
        self.__send_lock = backend.create_lock()
        self.__proxy: SocketProxy = SocketProxy(socket.socket())
        self.__request_handler: AsyncBaseRequestHandler[Any, Any] = request_handler
        self.__logger: _logging.Logger = logger

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
                    stack.callback(self.__logger.info, "%s disconnected", self.address)
                    if isinstance(request_handler, AsyncStreamRequestHandler):
                        stack.push_async_callback(self.__send_lock.acquire)  # Re-acquire lock after calling on_disconnection()
                        stack.push_async_callback(request_handler.on_disconnection, self)
                        stack.callback(self.__send_lock.release)  # Release lock before calling on_disconnection()
                    stack.push_async_callback(socket.aclose)

    async def send_packet(self, packet: _ResponseT, /) -> None:
        self.__check_closed()
        self.__logger.debug("A response will be sent to %s", self.address)
        self.__producer.queue(packet)
        async with self.__send_lock:
            socket = self.__check_closed()
            data: bytes = _concatenate_chunks(self.__producer)
            try:
                await socket.sendall(data)
                _check_real_socket_state(self.socket)
                nb_bytes_sent: int = len(data)
            finally:
                del data
            self.__logger.debug("%d byte(s) sent to %s", nb_bytes_sent, self.address)

    def __check_closed(self) -> AbstractAsyncStreamSocketAdapter:
        socket = self.__socket
        if socket is None or socket.is_closing():
            raise ClientClosedError("Closed client")
        return socket

    @property
    def socket(self) -> SocketProxy:
        return self.__proxy
