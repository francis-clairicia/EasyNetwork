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

import contextlib as _contextlib
import contextvars
import logging as _logging
import math
import operator
import weakref
from collections import Counter, deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Coroutine, Iterator, Mapping
from typing import TYPE_CHECKING, Any, Generic, TypeVar, assert_never, final
from weakref import WeakValueDictionary

from ...exceptions import ClientClosedError, DatagramProtocolParseError, ServerAlreadyRunning, ServerClosedError
from ...protocol import DatagramProtocol
from ...tools._utils import (
    check_real_socket_state as _check_real_socket_state,
    make_callback as _make_callback,
    recursively_clear_exception_traceback_frames as _recursively_clear_exception_traceback_frames,
    remove_traceback_frames_in_place as _remove_traceback_frames_in_place,
)
from ...tools.constants import MAX_DATAGRAM_BUFSIZE
from ...tools.socket import SocketAddress, SocketProxy, new_socket_address
from ..backend.factory import AsyncBackendFactory
from ..backend.tasks import SingleTaskRunner
from ._tools.actions import ErrorAction as _ErrorAction, RequestAction as _RequestAction
from .abc import AbstractAsyncNetworkServer, SupportsEventSet
from .handler import AsyncDatagramClient, AsyncDatagramRequestHandler

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

_KT = TypeVar("_KT")
_VT = TypeVar("_VT")


class AsyncUDPNetworkServer(AbstractAsyncNetworkServer, Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__backend",
        "__socket",
        "__socket_factory",
        "__socket_factory_runner",
        "__protocol",
        "__request_handler",
        "__is_shutdown",
        "__shutdown_asked",
        "__sendto_lock",
        "__client_manager",
        "__clients_waiting_for_new_datagrams",
        "__client_task_running",
        "__mainloop_task",
        "__service_actions_interval",
        "__logger",
    )

    def __init__(
        self,
        host: str,
        port: int,
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        request_handler: AsyncDatagramRequestHandler[_RequestT, _ResponseT],
        *,
        reuse_port: bool = False,
        backend: str | AbstractAsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
        service_actions_interval: float | None = None,
        logger: _logging.Logger | None = None,
    ) -> None:
        super().__init__()

        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")
        if not isinstance(request_handler, AsyncDatagramRequestHandler):
            raise TypeError(f"Expected an AsyncDatagramRequestHandler object, got {request_handler!r}")

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        self.__socket_factory: Callable[[], Coroutine[Any, Any, AbstractAsyncDatagramSocketAdapter]] | None
        self.__socket_factory = _make_callback(
            backend.create_udp_endpoint,
            local_address=(host, port),
            remote_address=None,
            reuse_port=reuse_port,
        )
        self.__socket_factory_runner: SingleTaskRunner[AbstractAsyncDatagramSocketAdapter] | None = None

        if service_actions_interval is None:
            service_actions_interval = 1.0

        self.__service_actions_interval: float = max(service_actions_interval, 0)
        self.__backend: AbstractAsyncBackend = backend
        self.__socket: AbstractAsyncDatagramSocketAdapter | None = None
        self.__protocol: DatagramProtocol[_ResponseT, _RequestT] = protocol
        self.__request_handler: AsyncDatagramRequestHandler[_RequestT, _ResponseT] = request_handler
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
        self.__clients_waiting_for_new_datagrams: set[_ClientAPI[_ResponseT]] = set()
        self.__client_task_running: set[_ClientAPI[_ResponseT]] = set()

    def is_serving(self) -> bool:
        return (socket := self.__socket) is not None and not socket.is_closing()

    async def server_close(self) -> None:
        self.__kill_socket_factory_runner()
        self.__socket_factory = None
        await self.__close_socket()

    async def __close_socket(self) -> None:
        async with _contextlib.AsyncExitStack() as exit_stack:
            socket, self.__socket = self.__socket, None
            if socket is not None:

                async def close_socket(socket: AbstractAsyncDatagramSocketAdapter) -> None:
                    with _contextlib.suppress(OSError):
                        await socket.aclose()

                exit_stack.push_async_callback(close_socket, socket)

            if self.__mainloop_task is not None:
                self.__mainloop_task.cancel()
                exit_stack.push_async_callback(self.__mainloop_task.wait)

    async def shutdown(self) -> None:
        self.__kill_socket_factory_runner()
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

    def __kill_socket_factory_runner(self) -> None:
        if self.__socket_factory_runner is not None:
            self.__socket_factory_runner.cancel()

    async def serve_forever(self, *, is_up_event: SupportsEventSet | None = None) -> None:
        async with _contextlib.AsyncExitStack() as server_exit_stack:
            if is_up_event is not None:
                # Force is_up_event to be set, in order not to stuck the waiting task
                server_exit_stack.callback(is_up_event.set)

            # Wake up server
            if not self.__is_shutdown.is_set():
                raise ServerAlreadyRunning("Server is already running")
            self.__is_shutdown = is_shutdown = self.__backend.create_event()
            server_exit_stack.callback(is_shutdown.set)
            ################

            # Bind and activate
            assert self.__socket is None  # nosec assert_used
            assert self.__socket_factory_runner is None  # nosec assert_used
            if self.__socket_factory is None:
                raise ServerClosedError("Closed server")
            try:
                self.__socket_factory_runner = SingleTaskRunner(self.__backend, self.__socket_factory)
                self.__socket = await self.__socket_factory_runner.run()
            finally:
                self.__socket_factory_runner = None
            ###################

            # Final teardown
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            server_exit_stack.push_async_callback(lambda: self.__backend.ignore_cancellation(self.__close_socket()))
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
            self.__mainloop_task = task_group.start_soon(self.__receive_datagrams, self.__socket, task_group)
            if self.__shutdown_asked:
                self.__mainloop_task.cancel()
            try:
                await self.__mainloop_task.join()
            finally:
                self.__mainloop_task = None

    async def __receive_datagrams(
        self,
        socket: AbstractAsyncDatagramSocketAdapter,
        task_group: AbstractTaskGroup,
    ) -> None:
        backend = self.__backend
        socket_family: int = socket.socket().family
        datagram_received_task_method = self.__datagram_received_coroutine
        logger: _logging.Logger = self.__logger
        bufsize: int = MAX_DATAGRAM_BUFSIZE
        client_manager: _ClientAPIManager[_ResponseT] = self.__client_manager
        client_task_running_set: set[_ClientAPI[_ResponseT]] = self.__client_task_running
        clients_waiting_for_new_datagrams: set[_ClientAPI[_ResponseT]] = self.__clients_waiting_for_new_datagrams
        while True:
            datagram, client_address = await socket.recvfrom(bufsize)
            try:
                client = client_manager.get(socket, new_socket_address(client_address, socket_family))
            finally:
                del client_address
            try:
                logger.debug("Received a datagram from %s", client.address)
                with client_manager.datagram_queue(client) as datagram_queue:
                    datagram_queue.append(datagram)

                    # datagram_received_task() is running (or will be run) if datagram_queue was not empty
                    # Therefore, start a new task only if there was no previous datagrams
                    if len(datagram_queue) == 1:
                        if client not in client_task_running_set or client in clients_waiting_for_new_datagrams:
                            task_group.start_soon(datagram_received_task_method, client, task_group)

                del datagram_queue
            finally:
                del datagram, client

            await backend.coro_yield()

    async def __service_actions_task(self) -> None:
        request_handler = self.__request_handler
        backend = self.__backend
        service_actions_interval = self.__service_actions_interval
        if math.isinf(service_actions_interval):
            return
        while True:
            await backend.sleep(service_actions_interval)
            try:
                await request_handler.service_actions()
            except Exception:
                self.__logger.exception("Error occurred in request_handler.service_actions()")

    async def __datagram_received_coroutine(
        self,
        client: _ClientAPI[_ResponseT],
        task_group: AbstractTaskGroup,
    ) -> None:
        backend = self.__backend

        async with self.__client_manager.lock(client) as condition:
            if client in self.__clients_waiting_for_new_datagrams:
                condition.notify()
                return
            request_handler_generator: AsyncGenerator[None, _RequestT] | None = None
            logger: _logging.Logger = self.__logger
            with (
                self.__suppress_and_log_remaining_exception(client.address),
                self.__client_manager.datagram_queue(client) as datagram_queue,
                self.__enqueue_task_at_end(client, datagram_queue, task_group),
                self.__client_task_running_context(client),
            ):
                self.__check_datagram_queue_not_empty(datagram_queue)
                try:
                    request_handler_generator = await self.__new_request_handler(client)
                except BaseException:
                    # In case of failure, deque the 1st datagram; it must not be handled
                    del datagram_queue[0]
                    raise
                if request_handler_generator is None:
                    del datagram_queue[0]
                    return
                try:
                    while True:
                        action: _RequestAction[_RequestT] | _ErrorAction
                        try:
                            if not datagram_queue:
                                self.__clients_waiting_for_new_datagrams.add(client)
                                try:
                                    await condition.wait()
                                finally:
                                    self.__clients_waiting_for_new_datagrams.discard(client)
                                self.__check_datagram_queue_not_empty(datagram_queue)
                            datagram = datagram_queue.popleft()
                            try:
                                action = _RequestAction(self.__protocol.build_packet_from_datagram(datagram))
                            finally:
                                del datagram
                        except BaseException as exc:
                            action = _ErrorAction(exc)

                        try:
                            match action:
                                case _RequestAction(request):
                                    logger.debug("Processing request sent by %s", client.address)
                                    try:
                                        await request_handler_generator.asend(request)
                                    except StopAsyncIteration:
                                        request_handler_generator = None
                                        return
                                    finally:
                                        del request
                                case _ErrorAction(DatagramProtocolParseError() as exception):
                                    exception.sender_address = client.address
                                    logger.debug("Malformed request sent by %s", client.address)
                                    try:
                                        try:
                                            _recursively_clear_exception_traceback_frames(exception)
                                        except RecursionError:
                                            logger.warning("Recursion depth reached when clearing exception's traceback frames")
                                        should_close_handle = not (await self.__request_handler.bad_request(client, exception))
                                        if should_close_handle:
                                            try:
                                                await request_handler_generator.aclose()
                                            finally:
                                                request_handler_generator = None
                                            return
                                    finally:
                                        del exception
                                case _ErrorAction(exception):
                                    try:
                                        await request_handler_generator.athrow(exception)
                                    except StopAsyncIteration:
                                        request_handler_generator = None
                                        return
                                    finally:
                                        del exception
                                case _:  # pragma: no cover
                                    assert_never(action)
                        finally:
                            del action

                        await backend.cancel_shielded_coro_yield()
                finally:
                    if request_handler_generator is not None:
                        await request_handler_generator.aclose()

    async def __new_request_handler(self, client: _ClientAPI[_ResponseT]) -> AsyncGenerator[None, _RequestT] | None:
        request_handler_generator = self.__request_handler.handle(client)
        try:
            await anext(request_handler_generator)
        except StopAsyncIteration:
            return None
        return request_handler_generator

    @staticmethod
    def __check_datagram_queue_not_empty(datagram_queue: deque[bytes]) -> None:
        if len(datagram_queue) == 0:  # pragma: no cover
            msg = "The server has created too many tasks and ends up in an inconsistent state."
            try:
                raise RuntimeError(msg)
            except RuntimeError as exc:
                exc.add_note("Please fill an issue (https://github.com/francis-clairicia/EasyNetwork/issues)")
                raise

    @_contextlib.contextmanager
    def __suppress_and_log_remaining_exception(self, client_address: SocketAddress) -> Iterator[None]:
        try:
            try:
                yield
            except* ClientClosedError as excgrp:
                _remove_traceback_frames_in_place(excgrp, 1)  # Removes the 'yield' frame just above
                self.__logger.warning(
                    "There have been attempts to do operation on closed client %s",
                    client_address,
                    exc_info=True,
                )
        except Exception as exc:
            _remove_traceback_frames_in_place(exc, 1)  # Removes the 'yield' frame just above
            self.__logger.error("-" * 40)
            self.__logger.exception("Exception occurred during processing of request from %s", client_address)
            self.__logger.error("-" * 40)

    @_contextlib.contextmanager
    def __enqueue_task_at_end(
        self,
        client: _ClientAPI[_ResponseT],
        datagram_queue: deque[bytes],
        task_group: AbstractTaskGroup,
    ) -> Iterator[None]:
        default_context: contextvars.Context = contextvars.copy_context()
        try:
            yield
        finally:
            if datagram_queue:
                try:
                    task_group.start_soon_with_context(default_context, self.__datagram_received_coroutine, client, task_group)
                except NotImplementedError:
                    default_context.run(task_group.start_soon, self.__datagram_received_coroutine, client, task_group)  # type: ignore[arg-type]

    @_contextlib.contextmanager
    def __client_task_running_context(self, client: _ClientAPI[_ResponseT]) -> Iterator[None]:
        assert client not in self.__client_task_running  # nosec assert_used
        self.__client_task_running.add(client)
        try:
            yield
        finally:
            self.__client_task_running.discard(client)
            del client

    def get_address(self) -> SocketAddress | None:
        if (socket := self.__socket) is None or socket.is_closing():
            return None
        return new_socket_address(socket.get_local_address(), socket.socket().family)

    def get_backend(self) -> AbstractAsyncBackend:
        return self.__backend

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
        "__client_lock",
        "__client_queue",
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
        self.__protocol: DatagramProtocol[_ResponseT, Any] = protocol
        self.__send_lock: ILock = send_lock
        self.__logger: _logging.Logger = logger
        self.__client_lock: _TemporaryValue[_ClientAPI[_ResponseT], ICondition] = _TemporaryValue(backend.create_condition_var)
        self.__client_queue: _TemporaryValue[_ClientAPI[_ResponseT], deque[bytes]] = _TemporaryValue(
            deque,
            must_delete_value=operator.not_,  # delete if and only if the deque is empty
        )

    def clear(self) -> None:
        self.__clients.clear()

    def get(self, socket: AbstractAsyncDatagramSocketAdapter, address: SocketAddress) -> _ClientAPI[_ResponseT]:
        key = (socket, address)
        try:
            return self.__clients[key]
        except KeyError:
            client = _ClientAPI(address, socket, self.__protocol, self.__send_lock, self.__logger)
            self.__clients[key] = client
            return client

    @_contextlib.asynccontextmanager
    async def lock(self, client: _ClientAPI[_ResponseT]) -> AsyncIterator[ICondition]:
        with self.__client_lock.get(client) as condition:
            del client
            async with condition:
                yield condition

    @_contextlib.contextmanager
    def datagram_queue(self, client: _ClientAPI[_ResponseT]) -> Iterator[deque[bytes]]:
        with self.__client_queue.get(client) as datagram_queue:
            del client
            yield datagram_queue


class _TemporaryValue(Generic[_KT, _VT]):
    __slots__ = ("__values", "__counter", "__value_factory", "__must_delete_value")

    def __init__(self, value_factory: Callable[[], _VT], must_delete_value: Callable[[_VT], bool] | None = None) -> None:
        super().__init__()

        if must_delete_value is None:
            must_delete_value = lambda _: True

        self.__values: dict[_KT, _VT] = {}
        self.__counter: Counter[_KT] = Counter()
        self.__value_factory: Callable[[], _VT] = value_factory
        self.__must_delete_value: Callable[[_VT], bool] = must_delete_value

    @_contextlib.contextmanager
    def get(self, key: _KT) -> Iterator[_VT]:
        try:
            value: _VT = self.__values[key]
        except KeyError:
            self.__values[key] = value = self.__value_factory()
        self.__counter[key] += 1
        try:
            yield value
        finally:
            self.__counter[key] -= 1
            assert self.__counter[key] >= 0, f"{self.__counter[key]=}"  # nosec assert_used
            if self.__counter[key] == 0 and self.__must_delete_value(value):
                del self.__counter[key], self.__values[key]
            del key, value


@final
class _ClientAPI(AsyncDatagramClient[_ResponseT]):
    __slots__ = (
        "__socket_ref",
        "__socket_proxy",
        "__protocol",
        "__send_lock",
        "__h",
        "__logger",
    )

    def __init__(
        self,
        address: SocketAddress,
        socket: AbstractAsyncDatagramSocketAdapter,
        protocol: DatagramProtocol[_ResponseT, Any],
        send_lock: ILock,
        logger: _logging.Logger,
    ) -> None:
        super().__init__(address)

        self.__socket_ref: weakref.ref[AbstractAsyncDatagramSocketAdapter] = weakref.ref(socket)
        self.__socket_proxy: SocketProxy = SocketProxy(socket.socket())
        self.__h: int | None = None
        self.__protocol: DatagramProtocol[_ResponseT, Any] = protocol
        self.__send_lock: ILock = send_lock
        self.__logger: _logging.Logger = logger

    def __hash__(self) -> int:
        if (h := self.__h) is None:
            self.__h = h = hash((_ClientAPI, self.__socket_ref, self.address, 0xFF))
        return h

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClientAPI):
            return NotImplemented
        return self.__socket_ref == other.__socket_ref and self.address == other.address

    def is_closing(self) -> bool:
        return (socket := self.__socket_ref()) is None or socket.is_closing()

    async def send_packet(self, packet: _ResponseT, /) -> None:
        async with self.__send_lock:
            socket = self.__check_closed()
            try:
                datagram: bytes = self.__protocol.make_datagram(packet)
            finally:
                del packet
            try:
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
