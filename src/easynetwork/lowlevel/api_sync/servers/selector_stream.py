# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Low-level stream servers module.

.. versionadded:: NEXT_VERSION
"""

from __future__ import annotations

__all__ = ["ConnectedStreamClient", "SelectorStreamServer"]

import concurrent.futures
import contextlib
import contextvars
import dataclasses
import errno as _errno
import functools
import logging
import math
import selectors
import threading
import time
import types
import warnings
import weakref
from collections.abc import Callable, Generator, Mapping
from typing import Any, Generic, Literal, NamedTuple, Self, TypeAlias, TypeVar, assert_never

from ...._typevars import _T_Request, _T_Response
from ....protocol import AnyStreamProtocolType
from ... import _stream, _utils, _wakeup_socketpair
from ..transports import abc as _transports, base_selector as _selector_transports

_T_Return = TypeVar("_T_Return")


class ConnectedStreamClient(_transports.BaseTransport, Generic[_T_Response]):
    """
    Write-end of the connected client.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = (
        "__transport",
        "__producer",
        "__close_lock",
        "__closing_event",
        "__reader_condvar",
        "__reader_done",
        "__wakeup_socketpair",
    )

    def __init__(
        self,
        *,
        _transport: _transports.StreamWriteTransport,
        _transport_close_lock: threading.Lock,
        _producer: _stream.StreamDataProducer[_T_Response],
        _reader_condvar: threading.Condition,
        _reader_done: _utils.Flag,
        _wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
    ) -> None:
        super().__init__()

        self.__transport: _transports.StreamWriteTransport = _transport
        self.__producer: _stream.StreamDataProducer[_T_Response] = _producer
        self.__close_lock = _transport_close_lock
        self.__closing_event = threading.Event()
        self.__reader_condvar = _reader_condvar
        self.__reader_done = _reader_done
        self.__wakeup_socketpair = _wakeup_socketpair

    def is_closed(self) -> bool:
        """
        Checks if :meth:`close` has been called. Thread-safe.

        Returns:
            :data:`True` if the endpoint is closed.
        """
        with self.__close_lock:
            return self.__transport.is_closed()

    def is_closing(self) -> bool:
        """
        Checks if the endpoint is closed or in the process of being closed.

        Returns:
            :data:`True` if the endpoint is closing.
        """
        return self.__closing_event.is_set()

    def abort(self) -> None:
        """
        Abruptly closes the transport. Thread-safe.
        """
        self.__close_impl(abort=True)

    def close(self) -> None:
        """
        Closes the endpoint. Thread-safe.
        """
        self.__close_impl(abort=False)

    def __close_impl(self, *, abort: bool) -> None:
        with self.__close_lock:
            self.__closing_event.set()
            with self.__reader_condvar:
                reader_is_done = self.__reader_done.is_set
                while not reader_is_done():
                    self.__wakeup_socketpair.wakeup_thread_and_signal_safe()
                    self.__reader_condvar.wait_for(reader_is_done, timeout=1.0)
            if abort:
                self.__transport.abort()
            else:
                self.__transport.close()

    def send_packet(self, packet: _T_Response, *, timeout: float | None = None) -> None:
        """
        Sends `packet` to the remote endpoint.  Thread-safe.

        Warning:
            A timeout on a send operation is unusual unless you have a SSL/TLS context.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.
            This would leave the connection in an inconsistent state.

        Parameters:
            packet: the Python object to send.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the send operation does not end up after `timeout` seconds.
        """
        with self.__close_lock:
            if timeout is None:
                timeout = math.inf
            self.__transport.send_all_from_iterable(self.__producer.generate(packet), timeout)

    @property
    @_utils.inherit_doc(_transports.BaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__transport.extra_attributes


class SelectorStreamServer(_transports.BaseTransport, Generic[_T_Request, _T_Response]):
    """
    Stream listener interface.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = (
        "__listener",
        "__protocol",
        "__max_recv_size",
        "__selector_factory",
        "__serve_guard",
        "__is_shut_down",
        "__shutdown_request",
        "__wakeup_socketpair",
        "__close_lock",
        "__active_tasks",
    )

    def __init__(
        self,
        listener: _selector_transports.SelectorListener[_selector_transports.SelectorStreamTransport],
        protocol: AnyStreamProtocolType[_T_Response, _T_Request],
        max_recv_size: int,
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            listener: the transport implementation to wrap.
            protocol: The :term:`protocol object` to use.
            max_recv_size: Read buffer size.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
                              Otherwise, the selector used by default is :class:`selectors.DefaultSelector`.
        """
        from ....lowlevel._stream import _check_any_protocol

        if not isinstance(listener, _selector_transports.SelectorListener):
            raise TypeError(f"Expected a SelectorListener object, got {listener!r}")

        _check_any_protocol(protocol)

        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")
        if selector_factory is None:
            selector_factory = selectors.DefaultSelector

        self.__wakeup_socketpair = _wakeup_socketpair.WakeupSocketPair()
        self.__active_tasks = _utils.AtomicUIntCounter(value=1)
        self.__listener = _ThreadSafeListener(
            listener,
            self.__wakeup_socketpair,
            _utils.weak_method_proxy(self.__detach_server, default=None),
        )
        self.__protocol: AnyStreamProtocolType[_T_Response, _T_Request] = protocol
        self.__max_recv_size: int = max_recv_size
        self.__selector_factory: Callable[[], selectors.BaseSelector] = selector_factory
        self.__serve_guard = _utils.ThreadSafeResourceGuard("another task is currently accepting new connections")
        self.__is_shut_down = threading.Event()
        self.__is_shut_down.set()
        self.__shutdown_request = threading.Event()
        self.__close_lock = threading.RLock()

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        with contextlib.suppress(Exception):
            self.__wakeup_socketpair.close()
        try:
            listener = self.__listener
        except AttributeError:
            return
        if not listener.is_closed():
            _warn(f"unclosed server {self!r}", ResourceWarning, source=self)
            listener.close()

    def is_closed(self) -> bool:
        """
        Checks if :meth:`close` has been called.

        Returns:
            :data:`True` if the server is closed.
        """
        return self.__listener.is_closed()

    def close(self) -> None:
        """
        Closes the server.
        """
        with self.__close_lock:
            self.__listener.close()

    def shutdown(self, timeout: float | None = None) -> None:
        """
        Asks for the server to stop. Thread-safe.

        All active client tasks will be cancelled.

        Warning:
            Do not call this method in the :meth:`serve` thread; it will cause a deadlock.

        Parameters:
            timeout: The maximum amount of seconds to wait.
        """
        self.__ask_server_shutdown()
        self.__is_shut_down.wait(timeout)

    def serve(
        self,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], Generator[float | None, _T_Request]],
        executor: concurrent.futures.Executor,
        *,
        worker_strategy: Literal["clients", "requests"] = "requests",
        disconnect_error_filter: Callable[[Exception], bool] | None = None,
    ) -> None:
        """
        Accept incoming connections as they come in and start tasks to handle them.

        Parameters:
            client_connected_cb: a callable that will be used to handle each accepted connection.
            executor: will be used to start tasks for handling each accepted connection.
            worker_strategy: Decides how to manage the executor.
            disconnect_error_filter: a callable that returns :data:`True` if the exception is the result of a pipe disconnect.
        """
        with self.__serve_guard, contextlib.ExitStack() as stack:
            self.__is_shut_down.clear()
            try:
                selector = stack.enter_context(self.__selector_factory())
                with self.__close_lock:
                    if self.__listener.is_closed():
                        raise _utils.error_from_errno(_errno.EBADF, "{strerror} (Server is closed)")
                    selector.register(self.__wakeup_socketpair, selectors.EVENT_READ)
                    self.__wakeup_socketpair.drain()

                server_is_shutting_down = threading.Event()
                stack.callback(server_is_shutting_down.set)

                match worker_strategy:
                    case "clients":
                        self.__serve_clients(
                            selector=selector,
                            client_connected_cb=client_connected_cb,
                            executor=executor,
                            disconnect_error_filter=disconnect_error_filter,
                            server_is_shutting_down=server_is_shutting_down.is_set,
                        )
                    case "requests":
                        self.__serve_requests(
                            selector=selector,
                            client_connected_cb=client_connected_cb,
                            executor=executor,
                            disconnect_error_filter=disconnect_error_filter,
                            server_is_shutting_down=server_is_shutting_down.is_set,
                        )
                    case _:
                        assert_never(worker_strategy)
            finally:
                self.__is_shut_down.set()
                self.__shutdown_request.clear()
                if not self.__active_tasks.value:
                    self.__wakeup_socketpair.close()

    ################################################################################
    ########################## "requests" worker strategy ##########################
    ################################################################################

    def __serve_requests(
        self,
        *,
        selector: selectors.BaseSelector,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], Generator[float | None, _T_Request]],
        executor: concurrent.futures.Executor,
        disconnect_error_filter: Callable[[Exception], bool] | None,
        server_is_shutting_down: Callable[[], bool],
    ) -> None:
        with _SelectorToken(selector=selector) as selector_token:
            handler = functools.partial(
                self.__serve_requests__start_new_client,
                default_context=contextvars.copy_context(),
                selector_token=selector_token,
                client_connected_cb=client_connected_cb,
                executor=executor,
                disconnect_error_filter=disconnect_error_filter,
                server_is_shutting_down=server_is_shutting_down,
            )
            self.__serve_forever_impl(selector_token=selector_token, handler=handler, executor=executor)

    def __serve_requests__start_new_client(
        self,
        transport: _selector_transports.SelectorStreamTransport,
        /,
        *,
        default_context: contextvars.Context,
        selector_token: _SelectorToken,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], Generator[float | None, _T_Request]],
        executor: concurrent.futures.Executor,
        disconnect_error_filter: Callable[[Exception], bool] | None,
        server_is_shutting_down: Callable[[], bool],
    ) -> None:
        request_handler_context = default_context.copy()
        del default_context

        with contextlib.ExitStack() as task_exit_stack:
            self.__attach_server()
            task_exit_stack.callback(self.__detach_server)

            task_exit_stack.push(self.__unhandled_exception_log)

            # By default, abort the connection at the end of the task.
            transport_close_exit_stack = task_exit_stack.enter_context(contextlib.ExitStack())
            transport_close_exit_stack.callback(transport.abort)

            producer = _stream.StreamDataProducer(self.__protocol)
            request_receiver = self.__new_request_receiver(transport, disconnect_error_filter, server_is_shutting_down)

            # NOTE: It is safe to clear the consumer before the transport here.
            #       There is no task reading the transport at this point.
            task_exit_stack.callback(request_receiver.consumer.clear)

            client = ConnectedStreamClient(
                _transport=transport,
                _transport_close_lock=request_receiver.transport_close_lock,
                _producer=producer,
                _reader_condvar=request_receiver.reader_condvar,
                _reader_done=request_receiver.reader_done,
                _wakeup_socketpair=self.__wakeup_socketpair,
            )
            request_handler_generator = request_handler_context.run(client_connected_cb, client)

            # Use thread-safe abort from now on.
            transport_close_exit_stack.pop_all()
            transport_close_exit_stack.callback(client.abort)

            task_exit_stack.callback(request_handler_context.run, request_handler_generator.close)

            timeout: float | None
            try:
                timeout = request_handler_context.run(next, request_handler_generator)
            except StopIteration:
                return

            client_data = _ClientData(
                client=client,
                request_receiver=request_receiver,
                request_handler_generator=request_handler_generator,
                request_handler_context=request_handler_context,
                transport_close_exit_stack=transport_close_exit_stack,
            )
            task_exit_stack = task_exit_stack.pop_all()
            self.__serve_requests__schedule_next_client_handle(
                None,
                client_data=client_data,
                receive_timeout=timeout,
                selector_token=selector_token,
                executor=executor,
                task_exit_stack=task_exit_stack,
            )

    def __serve_requests__handle_client_request(
        self,
        reader_future: concurrent.futures.Future[float] | None,
        /,
        *,
        client_data: _ClientData[_T_Request, _T_Response],
        selector_token: _SelectorToken,
        executor: concurrent.futures.Executor,
        task_exit_stack: contextlib.ExitStack,
        receive_timeout: float | None,
    ) -> None:
        try:
            with task_exit_stack.pop_all() as task_exit_stack:
                client = client_data.client
                request: _T_Request | None
                try:
                    if client.is_closing():
                        return
                    if reader_future is None:
                        receive_timeout = _utils.validate_optional_timeout_delay(receive_timeout, positive_check=True)
                    else:
                        try:
                            elapsed_time = reader_future.result(timeout=0)
                        except concurrent.futures.CancelledError:
                            return
                        # receive_timeout is already a valid timeout
                        receive_timeout = math.inf if receive_timeout is None else receive_timeout
                        receive_timeout = max(receive_timeout - elapsed_time, 0.0)

                    request_handler_context = client_data.request_handler_context
                    request_handler_generator = client_data.request_handler_generator
                    try:
                        request = client_data.request_receiver.next(first_try=(reader_future is None))
                    except (_selector_transports.WouldBlockOnRead, _selector_transports.WouldBlockOnWrite) as exc:
                        reader_future = selector_token.register(
                            transport=client,
                            fileno=exc.fileno,
                            events=_selector_event_from_exc(exc),
                            deadline=_get_current_time() + receive_timeout,
                            wakeup_socketpair=self.__wakeup_socketpair,
                            reader_condvar=client_data.request_receiver.reader_condvar,
                            reader_done=client_data.request_receiver.reader_done,
                        )
                        reader_future.add_done_callback(
                            functools.partial(
                                self.__serve_requests__schedule_next_client_handle,
                                client_data=client_data,
                                selector_token=selector_token,
                                executor=executor,
                                task_exit_stack=task_exit_stack.pop_all(),
                                receive_timeout=receive_timeout,
                            )
                        )
                        return
                    except StopIteration:
                        raise
                    except BaseException as exc:
                        receive_timeout = request_handler_context.run(request_handler_generator.throw, exc)
                    else:
                        receive_timeout = request_handler_context.run(request_handler_generator.send, request)
                except StopIteration:
                    # Request handler stopped normally, attempt a graceful close.
                    client_data.transport_close_exit_stack.pop_all()
                    client_data.transport_close_exit_stack.push(contextlib.closing(client))
                    return
                finally:
                    reader_future = request = None

                self.__serve_requests__schedule_next_client_handle(
                    None,
                    client_data=client_data,
                    receive_timeout=receive_timeout,
                    selector_token=selector_token,
                    executor=executor,
                    task_exit_stack=task_exit_stack,
                )
        finally:
            reader_future = None  # Break reference cycle with future on error.

    def __serve_requests__schedule_next_client_handle(
        self,
        reader_future: concurrent.futures.Future[float] | None,
        /,
        *,
        client_data: _ClientData[_T_Request, _T_Response],
        selector_token: _SelectorToken,
        executor: concurrent.futures.Executor,
        task_exit_stack: contextlib.ExitStack,
        receive_timeout: float | None,
    ) -> None:
        task_exit_stack = task_exit_stack.pop_all()
        try:
            handler_future = executor.submit(
                self.__serve_requests__handle_client_request,
                reader_future,
                client_data=client_data,
                receive_timeout=receive_timeout,
                selector_token=selector_token,
                executor=executor,
                task_exit_stack=task_exit_stack,
            )
        except RuntimeError:
            handler_future = concurrent.futures.Future()
            _cancel_future_and_notify(handler_future)
        else:
            handler_future.add_done_callback(self.__shutdown_on_handler_exception)
        handler_future.add_done_callback(
            functools.partial(
                self.__serve_requests__close_task_exit_stack_on_future_cancellation,
                task_exit_stack=task_exit_stack,
            )
        )

    def __serve_requests__close_task_exit_stack_on_future_cancellation(
        self,
        future: concurrent.futures.Future[Any],
        /,
        task_exit_stack: contextlib.ExitStack,
    ) -> None:
        if future.cancelled():
            task_exit_stack.close()

    ###############################################################################
    ########################## "clients" worker strategy ##########################
    ###############################################################################

    def __serve_clients(
        self,
        *,
        selector: selectors.BaseSelector,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], Generator[float | None, _T_Request]],
        executor: concurrent.futures.Executor,
        disconnect_error_filter: Callable[[Exception], bool] | None,
        server_is_shutting_down: Callable[[], bool],
    ) -> None:
        with _SelectorToken(selector=selector) as selector_token:

            default_context = contextvars.copy_context()

            def client_task(transport: _selector_transports.SelectorStreamTransport, /) -> None:
                context = default_context.copy()
                try:
                    return context.run(
                        self.__serve_clients__client_task,
                        transport,
                        client_connected_cb,
                        disconnect_error_filter,
                        server_is_shutting_down,
                    )
                finally:
                    del context

            self.__serve_forever_impl(selector_token=selector_token, handler=client_task, executor=executor)

    def __serve_clients__client_task(
        self,
        transport: _selector_transports.SelectorStreamTransport,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], Generator[float | None, _T_Request]],
        disconnect_error_filter: Callable[[Exception], bool] | None,
        server_is_shutting_down: Callable[[], bool],
    ) -> None:
        if not isinstance(transport, _selector_transports.SelectorStreamTransport):
            raise TypeError(f"Expected a SelectorStreamTransport object, got {transport!r}")

        with contextlib.ExitStack() as task_exit_stack:
            self.__attach_server()
            task_exit_stack.callback(self.__detach_server)

            task_exit_stack.push(self.__unhandled_exception_log)
            wakeup_socketpair_fd = self.__wakeup_socketpair.fileno()

            # By default, abort the connection at the end of the task.
            transport_close_exit_stack = task_exit_stack.enter_context(contextlib.ExitStack())
            transport_close_exit_stack.callback(transport.abort)

            producer = _stream.StreamDataProducer(self.__protocol)
            request_receiver = self.__new_request_receiver(transport, disconnect_error_filter, server_is_shutting_down)

            # NOTE: It is safe to clear the consumer before the transport here.
            #       There is no task reading the transport at this point.
            task_exit_stack.callback(request_receiver.consumer.clear)

            client = ConnectedStreamClient(
                _transport=transport,
                _transport_close_lock=request_receiver.transport_close_lock,
                _producer=producer,
                _reader_condvar=request_receiver.reader_condvar,
                _reader_done=request_receiver.reader_done,
                _wakeup_socketpair=self.__wakeup_socketpair,
            )
            request_handler_generator = client_connected_cb(client)

            # Use thread-safe abort from now on.
            transport_close_exit_stack.pop_all()
            transport_close_exit_stack.callback(client.abort)

            timeout: float | None
            try:
                timeout = next(request_handler_generator)
            except StopIteration:
                return
            else:
                try:
                    request: _T_Request | None
                    _validate_timeout_delay = _utils.validate_optional_timeout_delay
                    _EVENT_READ = selectors.EVENT_READ
                    _wait_for_fd = _selector_transports._wait_for_fd
                    while not client.is_closing():
                        try:
                            timeout = _validate_timeout_delay(timeout, positive_check=True)
                            first_recv_try: bool = True
                            while True:
                                try:
                                    request = request_receiver.next(first_try=first_recv_try)
                                except (_selector_transports.WouldBlockOnRead, _selector_transports.WouldBlockOnWrite) as exc:
                                    fileno = exc.fileno
                                    event = _selector_event_from_exc(exc)
                                else:
                                    break
                                finally:
                                    first_recv_try = False

                                with request_receiver:
                                    if client.is_closing():
                                        return
                                    available, timeout = _wait_for_fd(
                                        transport,
                                        {fileno: event, wakeup_socketpair_fd: _EVENT_READ},
                                        timeout,
                                    )
                                    if not available:
                                        raise _utils.error_from_errno(_errno.ETIMEDOUT)
                        except StopIteration:
                            raise
                        except BaseException as exc:
                            timeout = request_handler_generator.throw(exc)
                        else:
                            timeout = request_handler_generator.send(request)
                        finally:
                            request = None
                except StopIteration:
                    # Request handler stopped normally, attempt a graceful close.
                    transport_close_exit_stack.pop_all()
                    transport_close_exit_stack.push(contextlib.closing(client))
                    return
            finally:
                request_handler_generator.close()

    #################################################################################
    ########################## common functions for server ##########################
    #################################################################################

    def __new_request_receiver(
        self,
        transport: _selector_transports.SelectorStreamTransport,
        disconnect_error_filter: Callable[[Exception], bool] | None,
        server_is_shutting_down: Callable[[], bool],
    ) -> _AnyRequestReceiver[_T_Request]:
        from ....protocol import BufferedStreamProtocol, StreamProtocol

        consumer: _stream.StreamDataConsumer[_T_Request] | _stream.BufferedStreamDataConsumer[_T_Request]
        match self.__protocol:
            case BufferedStreamProtocol():
                consumer = _stream.BufferedStreamDataConsumer(self.__protocol, self.__max_recv_size)
                return _BufferedRequestReceiver(
                    transport=transport,
                    consumer=consumer,
                    disconnect_error_filter=disconnect_error_filter,
                    server_is_shutting_down=server_is_shutting_down,
                )
            case StreamProtocol():
                consumer = _stream.StreamDataConsumer(self.__protocol)
                return _RequestReceiver(
                    transport=transport,
                    consumer=consumer,
                    max_recv_size=self.__max_recv_size,
                    disconnect_error_filter=disconnect_error_filter,
                    server_is_shutting_down=server_is_shutting_down,
                )
            case _:  # pragma: no cover
                assert_never(self.__protocol)

    def __ask_server_shutdown(self) -> None:
        if not self.__is_shut_down.is_set():
            self.__shutdown_request.set()
            with contextlib.suppress(OSError):
                self.__wakeup_socketpair.wakeup_thread_and_signal_safe()

    def __serve_forever_impl(
        self,
        *,
        selector_token: _SelectorToken,
        handler: Callable[[_selector_transports.SelectorStreamTransport], None],
        executor: concurrent.futures.Executor,
    ) -> None:
        selector = selector_token.selector
        selector_state_lock = selector_token.state_lock
        listener = self.__listener
        shutdown_requested = self.__shutdown_request.is_set

        while not shutdown_requested():
            if (accept_future := listener.try_accepting_new_connection(selector_token, handler, executor)) is not None:
                accept_future.add_done_callback(self.__shutdown_on_handler_exception)
                del accept_future

            selector_wait_deadline = min(listener.ready_at_deadline(), selector_token.get_min_deadline())

            selector_wait_timeout: float = selector_wait_deadline - _get_current_time()
            if selector_wait_timeout < 0:
                selector_wait_timeout = 0.0
            else:
                # Do not wait more than 24h.
                selector_wait_timeout = min(selector_wait_timeout, 86400.0)

            ready = selector.select(selector_wait_timeout)

            # shutdown() called during select(), exit immediately.
            if shutdown_requested():
                break

            del selector_wait_timeout

            # Notify threads for ready file descriptors
            self.__handle_events(selector, selector_state_lock, ready)
            self.__handle_pending_transports(selector, selector_state_lock)

            ready.clear()

    def __handle_events(
        self,
        selector: selectors.BaseSelector,
        state_lock: threading.RLock,
        events: list[tuple[selectors.SelectorKey, int]],
    ) -> None:
        wakeup_socketpair = self.__wakeup_socketpair
        now = _get_current_time()
        for key, _ in events:
            if key.fileobj is wakeup_socketpair:
                wakeup_socketpair.drain()
                continue

            selector_key_data: _SelectorKeyData = key.data
            with state_lock:
                try:
                    selector.unregister(key.fileobj)
                except KeyError:
                    pass
                finally:
                    _set_future_result_unless_cancelled(selector_key_data.future, now - selector_key_data.start_time)

    def __handle_pending_transports(self, selector: selectors.BaseSelector, state_lock: threading.RLock) -> None:
        # Either:
        # - Cancel pending futures if transport has been closed asynchronously
        # - Set timeout error if deadline has been reached
        with state_lock:
            now = _get_current_time()

            for key in list(selector.get_map().values()):
                match key.data:
                    case _SelectorKeyData(transport=transport, future=task_future) if transport.is_closing():
                        selector.unregister(key.fileobj)
                        _cancel_future_and_notify(task_future)
                    case _SelectorKeyData(deadline=deadline, future=task_future) if deadline < now:
                        selector.unregister(key.fileobj)
                        _set_future_exception_unless_cancelled(task_future, _utils.error_from_errno(_errno.ETIMEDOUT))

    def __attach_server(self) -> None:
        self.__active_tasks.increment()

    def __detach_server(self) -> None:
        active_tasks = self.__active_tasks.decrement()
        if not active_tasks:
            if self.__is_shut_down.is_set():
                self.__wakeup_socketpair.close()
            else:
                self.__ask_server_shutdown()

    def __shutdown_on_handler_exception(self, future: concurrent.futures.Future[Any], /) -> None:
        if not future.cancelled() and (exc := future.exception()) is not None:
            self.__unhandled_exception_log(type(exc), exc, exc.__traceback__)
            del exc
            self.__ask_server_shutdown()

    @classmethod
    def __unhandled_exception_log(
        cls,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
        /,
    ) -> bool:
        if exc_type is not None and issubclass(exc_type, Exception):
            logger = logging.getLogger(__name__)
            logger.error("Unhandled exception: %s", exc_val, exc_info=(exc_type, exc_val or exc_type(), exc_tb))
            return True
        return False

    @property
    @_utils.inherit_doc(_transports.BaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _ClientData(Generic[_T_Request, _T_Response]):
    client: ConnectedStreamClient[_T_Response]
    request_receiver: _AnyRequestReceiver[_T_Request]
    request_handler_generator: Generator[float | None, _T_Request]
    request_handler_context: contextvars.Context
    transport_close_exit_stack: contextlib.ExitStack


class _ThreadSafeListener(_transports.BaseTransport):
    __slots__ = (
        "__listener",
        "__close_lock",
        "__closing_event",
        "__ready_for_reading",
        "__ready_at_deadline",
        "__reader_condvar",
        "__reader_done",
        "__wakeup_socketpair",
        "__finalizer",
    )

    def __init__(
        self,
        listener: _selector_transports.SelectorListener[_selector_transports.SelectorStreamTransport],
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
        detach_server: Callable[[], None],
    ) -> None:
        self.__listener: _selector_transports.SelectorListener[_selector_transports.SelectorStreamTransport] = listener
        self.__close_lock = threading.Lock()
        self.__closing_event = threading.Event()
        self.__ready_for_reading = threading.Event()
        self.__ready_for_reading.set()
        self.__ready_at_deadline: float = _get_current_time()
        self.__reader_condvar = threading.Condition()
        self.__reader_done = _utils.Flag()
        self.__reader_done.set()
        self.__wakeup_socketpair = wakeup_socketpair
        self.__finalizer = weakref.finalize(self, detach_server)

    def is_closed(self) -> bool:
        with self.__close_lock:
            return self.__listener.is_closed()

    def is_closing(self) -> bool:
        return self.__closing_event.is_set()

    def close(self) -> None:
        with self.__close_lock:
            self.__closing_event.set()
            with self.__reader_condvar:
                reader_is_done = self.__reader_done.is_set
                while not reader_is_done():
                    self.__wakeup_socketpair.wakeup_thread_and_signal_safe()
                    self.__reader_condvar.wait_for(reader_is_done, timeout=1.0)
            try:
                self.__listener.close()
            finally:
                self.__finalizer()

    def ready_at_deadline(self) -> float:
        return self.__ready_at_deadline if self.__ready_for_reading.is_set() else math.inf

    def try_accepting_new_connection(
        self,
        selector_token: _SelectorToken,
        handler: Callable[[_selector_transports.SelectorStreamTransport], _T_Return],
        executor: concurrent.futures.Executor,
    ) -> concurrent.futures.Future[_T_Return] | None:
        if not self.__ready_for_reading.is_set() or _get_current_time() < self.__ready_at_deadline:
            return None

        with self.__close_lock:
            self.__ready_for_reading.clear()
            try:
                if self.__listener.is_closed():
                    # server.close() called in another thread.
                    # keep flag to False forever.
                    return None
                handler = functools.partial(self.__in_executor, handler)
                accept_future = self.__listener.accept_noblock(handler, executor)
            except (_selector_transports.WouldBlockOnRead, _selector_transports.WouldBlockOnWrite) as exc:
                listener_wait_future = selector_token.register(
                    transport=self,
                    fileno=exc.fileno,
                    events=_selector_event_from_exc(exc),
                    deadline=math.inf,
                    wakeup_socketpair=self.__wakeup_socketpair,
                    reader_condvar=self.__reader_condvar,
                    reader_done=self.__reader_done,
                )
                listener_wait_future.add_done_callback(self.__on_listener_wait_future_done)
                return None
            except Exception as exc:
                if self.__listener.is_accept_capacity_error(exc):
                    sleep_time = self.__listener.accept_capacity_error_sleep_time()
                    self.__ready_at_deadline = _get_current_time() + sleep_time
                    return None
                else:
                    raise
            else:
                accept_future.add_done_callback(self.__on_client_future_running_or_cancelled)
                return accept_future

    def __in_executor(
        self,
        handler: Callable[[_selector_transports.SelectorStreamTransport], _T_Return],
        transport: _selector_transports.SelectorStreamTransport,
    ) -> _T_Return:
        self.__on_client_future_running_or_cancelled(None)
        return handler(transport)

    def __on_client_future_running_or_cancelled(self, future: concurrent.futures.Future[Any] | None) -> None:
        if future is None or future.cancelled():
            self.__ready_for_reading.set()
            self.__wakeup_socketpair.wakeup_thread_and_signal_safe()

    def __on_listener_wait_future_done(self, future: concurrent.futures.Future[Any]) -> None:
        if future.done() and not future.cancelled():
            self.__ready_for_reading.set()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, frozen=True, eq=False, slots=True)
class _SelectorToken:
    selector: selectors.BaseSelector
    state_lock: threading.RLock = dataclasses.field(default_factory=threading.RLock)
    tid: int = dataclasses.field(default_factory=threading.get_ident)
    __closed: _utils.Flag = dataclasses.field(init=False, default_factory=_utils.Flag)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        with self.state_lock:
            self.__closed.set()
            selector_keys = list(self.selector.get_map().values())

            # Cancel pending futures
            for key in selector_keys:
                match key.data:
                    case _SelectorKeyData(future=client_task_future):
                        self.selector.unregister(key.fileobj)
                        _cancel_future_and_notify(client_task_future)
                    case _:
                        continue

    def register(
        self,
        *,
        transport: ConnectedStreamClient[Any] | _ThreadSafeListener,
        fileno: int,
        events: selectors._EventMask,
        deadline: float,
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
        reader_condvar: threading.Condition,
        reader_done: _utils.Flag,
        _get_thread_id: Callable[[], int] = threading.get_ident,
        _future_factory: Callable[[], concurrent.futures.Future[Any]] = concurrent.futures.Future,
    ) -> concurrent.futures.Future[float]:
        assert reader_done.is_set()  # nosec assert_used

        with self.state_lock:
            future: concurrent.futures.Future[float] = _future_factory()

            with reader_condvar:
                if self.__closed.is_set() or transport.is_closing():
                    _cancel_future_and_notify(future)
                    return future
                start_time = _get_current_time()
                if deadline <= start_time:
                    future.set_exception(_utils.error_from_errno(_errno.ETIMEDOUT))
                    return future
                reader_done.clear()
                future.add_done_callback(
                    functools.partial(
                        self.__wakeup_waiter_on_future_done,
                        reader_condvar=reader_condvar,
                        reader_done=reader_done,
                    )
                )

            try:
                key = self.selector.register(
                    fileno,
                    events,
                    data=_SelectorKeyData(transport=transport, future=future, deadline=deadline, start_time=start_time),
                )
                future.add_done_callback(
                    functools.partial(self.__unregister_on_future_cancel, key=key, wakeup_socketpair=wakeup_socketpair)
                )
                if _get_thread_id() != self.tid:
                    wakeup_socketpair.wakeup_thread_and_signal_safe()
            except BaseException:
                future.cancel()
                raise
            return future

    def get_min_deadline(self) -> float:
        min_deadline: float = math.inf
        with self.state_lock:
            for key in self.selector.get_map().values():
                match key.data:
                    case _SelectorKeyData(deadline=deadline) if deadline < min_deadline:
                        min_deadline = deadline
        return min_deadline

    @staticmethod
    def __wakeup_waiter_on_future_done(
        _: concurrent.futures.Future[Any],
        /,
        *,
        reader_condvar: threading.Condition,
        reader_done: _utils.Flag,
    ) -> None:
        with reader_condvar:
            reader_done.set()
            reader_condvar.notify_all()

    def __unregister_on_future_cancel(
        self,
        future: concurrent.futures.Future[Any],
        /,
        *,
        key: selectors.SelectorKey,
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
    ) -> None:
        if future.cancelled():
            with self.state_lock:
                try:
                    self.selector.unregister(key.fileobj)
                except KeyError:
                    pass
                else:
                    with contextlib.suppress(OSError):
                        wakeup_socketpair.wakeup_thread_and_signal_safe()


class _SelectorKeyData(NamedTuple):
    transport: ConnectedStreamClient[Any] | _ThreadSafeListener
    future: concurrent.futures.Future[float]
    deadline: float
    start_time: float


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _BaseRequestReceiver(Generic[_T_Request]):
    transport: _selector_transports.SelectorStreamTransport
    server_is_shutting_down: Callable[[], bool]
    transport_close_lock: threading.Lock = dataclasses.field(init=False, default_factory=threading.Lock)
    reader_condvar: threading.Condition = dataclasses.field(init=False, default_factory=threading.Condition)
    reader_done: _utils.Flag = dataclasses.field(init=False, default_factory=functools.partial(_utils.Flag, True))

    def __enter__(self) -> None:
        with self.reader_condvar:
            self.reader_done.clear()

    def __exit__(self, *args: Any) -> None:
        with self.reader_condvar:
            self.reader_done.set()
            self.reader_condvar.notify()


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _RequestReceiver(_BaseRequestReceiver[_T_Request]):
    consumer: _stream.StreamDataConsumer[_T_Request]
    max_recv_size: int
    disconnect_error_filter: Callable[[Exception], bool] | None

    def __post_init__(self) -> None:
        assert self.max_recv_size > 0, f"{self.max_recv_size=}"  # nosec assert_used

    def next(self, *, first_try: bool) -> _T_Request:
        consumer = self.consumer
        if first_try:
            try:
                return consumer.next(None)
            except StopIteration:
                pass

        transport = self.transport
        while not self.server_is_shutting_down():
            with self.transport_close_lock:
                if transport.is_closed():
                    break
                try:
                    chunk: bytes = transport.recv_noblock(self.max_recv_size)
                except (_selector_transports.WouldBlockOnRead, _selector_transports.WouldBlockOnWrite):
                    raise
                except Exception as exc:
                    if self.disconnect_error_filter is not None and self.disconnect_error_filter(exc):
                        break
                    raise
            if not chunk:
                break
            try:
                return consumer.next(chunk)
            except StopIteration:
                pass
            finally:
                del chunk

        # Loop break
        raise StopIteration


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _BufferedRequestReceiver(_BaseRequestReceiver[_T_Request]):
    consumer: _stream.BufferedStreamDataConsumer[_T_Request]
    disconnect_error_filter: Callable[[Exception], bool] | None

    def next(self, *, first_try: bool) -> _T_Request:
        consumer = self.consumer
        if first_try:
            try:
                return consumer.next(None)
            except StopIteration:
                pass

        transport = self.transport
        nbytes: int
        while not self.server_is_shutting_down():
            with self.transport_close_lock:
                if transport.is_closed():
                    break
                with consumer.get_write_buffer() as buffer:
                    try:
                        nbytes = transport.recv_noblock_into(buffer)
                    except (_selector_transports.WouldBlockOnRead, _selector_transports.WouldBlockOnWrite):
                        raise
                    except Exception as exc:
                        if self.disconnect_error_filter is not None and self.disconnect_error_filter(exc):
                            break
                        raise
            if not nbytes:
                break
            try:
                return consumer.next(nbytes)
            except StopIteration:
                pass

        # Loop break
        raise StopIteration


_AnyRequestReceiver: TypeAlias = _RequestReceiver[_T_Request] | _BufferedRequestReceiver[_T_Request]


def _get_current_time() -> float:
    return time.perf_counter()


def _selector_event_from_exc(exc: _selector_transports.WouldBlockOnRead | _selector_transports.WouldBlockOnWrite) -> int:
    match exc:
        case _selector_transports.WouldBlockOnRead():
            return selectors.EVENT_READ
        case _selector_transports.WouldBlockOnWrite():
            return selectors.EVENT_WRITE
        case _:
            assert_never(exc)


def _cancel_future_and_notify(f: concurrent.futures.Future[Any]) -> None:
    if f.cancel():  # pragma: no branch
        f.set_running_or_notify_cancel()


def _set_future_result_unless_cancelled(f: concurrent.futures.Future[_T_Return], result: _T_Return) -> None:
    if f.set_running_or_notify_cancel():  # pragma: no branch
        f.set_result(result)


def _set_future_exception_unless_cancelled(f: concurrent.futures.Future[Any], exc: BaseException) -> None:
    if f.set_running_or_notify_cancel():  # pragma: no branch
        f.set_exception(exc)
