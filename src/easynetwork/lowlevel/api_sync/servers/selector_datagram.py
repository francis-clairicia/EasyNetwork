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
"""Low-level datagram servers module.

.. versionadded:: NEXT_VERSION"""

from __future__ import annotations

__all__ = ["DatagramClientContext", "SelectorDatagramServer"]

import concurrent.futures
import contextlib
import contextvars
import dataclasses
import enum
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
from collections.abc import Callable, Generator, Hashable, Mapping
from queue import Empty as _QueueEmpty, SimpleQueue as _Queue
from typing import Any, Generic, NamedTuple, Self, TypeVar, assert_never

from ...._typevars import _T_Request, _T_Response
from ....exceptions import DatagramProtocolParseError
from ....protocol import DatagramProtocol
from ... import _utils, _wakeup_socketpair
from ..transports import abc as _transports, base_selector as _selector_transports

_T_Address = TypeVar("_T_Address", bound=Hashable)
_T_Return = TypeVar("_T_Return")


# Python 3.12.3 regression for weakref slots on generics
# See https://github.com/python/cpython/issues/118033
# @dataclasses.dataclass(frozen=True, unsafe_hash=True, slots=True, weakref_slot=True)


@dataclasses.dataclass(frozen=True, unsafe_hash=True)
class DatagramClientContext(Generic[_T_Response, _T_Address]):
    """
    Contains information about the remote endpoint which sends a datagram.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = (
        "address",
        "server",
        "__weakref__",
    )

    address: _T_Address
    """The client address."""

    server: SelectorDatagramServer[Any, _T_Response, _T_Address]
    """The server which receives the datagram."""


class SelectorDatagramServer(_transports.BaseTransport, Generic[_T_Request, _T_Response, _T_Address]):
    """
    Datagram packet listener interface.

    .. versionadded:: NEXT_VERSION
    """

    __slots__ = (
        "__listener",
        "__protocol",
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
        listener: _selector_transports.SelectorDatagramListener[_T_Address],
        protocol: DatagramProtocol[_T_Response, _T_Request],
        *,
        selector_factory: Callable[[], selectors.BaseSelector] | None = None,
    ) -> None:
        """
        Parameters:
            listener: the transport implementation to wrap.
            protocol: The :term:`protocol object` to use.
            selector_factory: If given, the callable object to use to create a new :class:`selectors.BaseSelector` instance.
                              Otherwise, the selector used by default is :class:`selectors.DefaultSelector`.
        """

        if not isinstance(listener, _selector_transports.SelectorDatagramListener):
            raise TypeError(f"Expected a SelectorDatagramListener object, got {listener!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        if selector_factory is None:
            selector_factory = selectors.DefaultSelector

        self.__wakeup_socketpair = _wakeup_socketpair.WakeupSocketPair()
        self.__active_tasks = _utils.AtomicUIntCounter(value=1)
        self.__listener = _ThreadSafeListener(
            listener,
            self.__wakeup_socketpair,
            _utils.weak_method_proxy(self.__detach_server, default=None),
        )
        self.__protocol: DatagramProtocol[_T_Response, _T_Request] = protocol
        self.__selector_factory: Callable[[], selectors.BaseSelector] = selector_factory
        self.__serve_guard = _utils.ThreadSafeResourceGuard("another task is currently receiving datagrams")
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

    def send_packet_to(self, packet: _T_Response, address: _T_Address, *, timeout: float | None = None) -> None:
        """
        Sends `packet` to the remote endpoint `address`.

        If `timeout` is not :data:`None`, the entire send operation will take at most `timeout` seconds.

        Warning:
            A timeout on a send operation is unusual.

            In the case of a timeout, it is impossible to know if all the packet data has been sent.

        Important:
            The lock acquisition time is included in the `timeout`.

            This means that you may get a :exc:`TimeoutError` because it took too long to get the lock.

        Parameters:
            packet: the Python object to send.
            address: the remote endpoint address.
            timeout: the allowed time (in seconds) for blocking operations.

        Raises:
            TimeoutError: the send operation does not end up after `timeout` seconds.
        """
        try:
            datagram: bytes = self.__protocol.make_datagram(packet)
        except Exception as exc:
            raise RuntimeError("protocol.make_datagram() crashed") from exc

        if timeout is None:
            timeout = math.inf

        return self.__listener.send_to(datagram, address, timeout)

    def serve(
        self,
        datagram_received_cb: Callable[[DatagramClientContext[_T_Response, _T_Address]], Generator[float | None, _T_Request]],
        executor: concurrent.futures.Executor,
        *,
        datagram_receiver_thread_name: str = "",
    ) -> None:
        """
        Receive incoming datagrams as they come in and start tasks to handle them.

        Important:
            There will always be only one active generator per client.
            All the pending datagrams received while the generator is running are queued.

            This behavior is designed to act like a stream request handler.

        Note:
            If the generator returns before the first :keyword:`yield` statement, the received datagram is discarded.

            This is useful when a client that you do not expect to see sends something; the datagrams are parsed only when
            the generator hits a :keyword:`yield` statement.

        Parameters:
            datagram_received_cb: a callable that will be used to handle each received datagram.
            executor: will be used to start tasks for handling each accepted connection.
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

                datagram_receiver_thread_name = datagram_receiver_thread_name.strip() or "datagram_receiver"
                self.__serve_requests(
                    selector=selector,
                    datagram_received_cb=datagram_received_cb,
                    executor=executor,
                    datagram_receiver_thread_name=datagram_receiver_thread_name,
                )
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
        datagram_received_cb: Callable[[DatagramClientContext[_T_Response, _T_Address]], Generator[float | None, _T_Request]],
        executor: concurrent.futures.Executor,
        datagram_receiver_thread_name: str,
    ) -> None:
        default_context = contextvars.copy_context()

        with (
            _SelectorToken(selector=selector) as selector_token,
            _ClientHandlerToken(
                server=self, datagram_received_cb=datagram_received_cb, default_context=default_context
            ) as client_handler_token,
        ):

            def handler(datagram: bytes, address: _T_Address, /) -> None:
                client_data = client_handler_token.get_client_data(address)

                with client_data.state_lock:
                    client_data.datagram_queue.put(datagram)
                    if client_data.state is None:
                        self.__serve_requests__start_new_client_task(
                            client_handler_token.get_client_ref(address),
                            client_data,
                            client_handler_token=client_handler_token,
                            executor=executor,
                        )
                    elif (waiter_key := client_handler_token.pop_waiter(address)) is not None:
                        _set_future_result_unless_cancelled(waiter_key.future, None)

            datagram_receiver_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=datagram_receiver_thread_name,
            )
            try:
                self.__serve_forever_impl(
                    selector_token=selector_token,
                    client_handler_token=client_handler_token,
                    handler=handler,
                    executor=datagram_receiver_executor,
                )
            finally:
                datagram_receiver_executor.shutdown(cancel_futures=True)

    def __serve_requests__start_new_client_task(
        self,
        client_ctx: DatagramClientContext[_T_Response, _T_Address],
        client_data: _ClientData,
        /,
        *,
        client_handler_token: _ClientHandlerToken[_T_Request, _T_Response, _T_Address],
        executor: concurrent.futures.Executor,
    ) -> None:
        client_data.mark_pending()
        try:
            client_task_future = executor.submit(
                self.__serve_requests__handle_new_client,
                client_ctx,
                client_data,
                client_handler_token=client_handler_token,
                executor=executor,
            )
        except RuntimeError:
            client_task_future = concurrent.futures.Future()
            _cancel_future_and_notify(client_task_future)

        client_task_future.add_done_callback(self.__shutdown_on_handler_exception)
        client_data.register_new_client_task(client_task_future)

    def __serve_requests__handle_new_client(
        self,
        client_ctx: DatagramClientContext[_T_Response, _T_Address],
        client_data: _ClientData,
        /,
        *,
        client_handler_token: _ClientHandlerToken[_T_Request, _T_Response, _T_Address],
        executor: concurrent.futures.Executor,
    ) -> None:
        self.__attach_server()
        try:
            client_data.mark_running()
            should_restart_handle = _utils.Flag(default_value=True)

            with contextlib.ExitStack() as task_exit_stack:
                task_exit_stack.push(
                    functools.partial(
                        self.__serve_requests__on_client_task_done,
                        client_ctx=client_ctx,
                        client_data=client_data,
                        client_handler_token=client_handler_token,
                        executor=executor,
                        should_restart_handle=should_restart_handle,
                    )
                )
                task_exit_stack.push(self.__unhandled_exception_log)
                task_exit_stack.callback(client_data.mark_done)

                return self.__serve_requests__handle_client_request(
                    None,
                    client_ctx=client_ctx,
                    client_data=client_data,
                    request_handler_context=client_handler_token.default_context.copy(),
                    request_handler_generator=None,
                    client_handler_token=client_handler_token,
                    task_exit_stack=task_exit_stack,
                    executor=executor,
                    should_restart_handle=should_restart_handle,
                )

        finally:
            self.__detach_server()

    def __serve_requests__on_client_task_done(
        self,
        exc_type: type[BaseException] | None,
        /,
        *_: Any,
        client_ctx: DatagramClientContext[_T_Response, _T_Address],
        client_data: _ClientData,
        client_handler_token: _ClientHandlerToken[_T_Request, _T_Response, _T_Address],
        executor: concurrent.futures.Executor,
        should_restart_handle: _utils.Flag,
    ) -> None:
        if not should_restart_handle.is_set():
            return
        if exc_type is not None:
            assert not issubclass(exc_type, Exception)  # nosec assert_used
            return
        try:
            with client_data.state_lock:
                if not client_data.datagram_queue.empty() and client_data.state is None:
                    self.__serve_requests__start_new_client_task(
                        client_ctx,
                        client_data,
                        client_handler_token=client_handler_token,
                        executor=executor,
                    )
        except Exception as exc:
            self.__unhandled_exception_log(type(exc), exc, exc.__traceback__)

    def __serve_requests__handle_client_request(
        self,
        waiter_future: concurrent.futures.Future[None] | None,
        /,
        *,
        client_ctx: DatagramClientContext[_T_Response, _T_Address],
        client_data: _ClientData,
        request_handler_context: contextvars.Context,
        request_handler_generator: Generator[float | None, _T_Request] | None,
        client_handler_token: _ClientHandlerToken[_T_Request, _T_Response, _T_Address],
        task_exit_stack: contextlib.ExitStack,
        executor: concurrent.futures.Executor,
        should_restart_handle: _utils.Flag,
    ) -> None:
        self.__attach_server()
        try:
            with task_exit_stack.pop_all() as task_exit_stack:
                timeout: float | None = None

                if request_handler_generator is None:
                    request_handler_generator = request_handler_context.run(client_handler_token.datagram_received_cb, client_ctx)
                    task_exit_stack.callback(request_handler_context.run, request_handler_generator.close)
                    try:
                        timeout = request_handler_context.run(next, request_handler_generator)
                    except BaseException as exc:
                        # Drop received datagram
                        if not client_data.datagram_queue.empty():  # pragma: no branch
                            client_data.datagram_queue.get_nowait()
                        if isinstance(exc, StopIteration):
                            return

                request: _T_Request | None
                try:
                    try:
                        if waiter_future is not None:
                            assert waiter_future.done()  # nosec assert_used
                            if waiter_future.cancelled():
                                should_restart_handle.clear()
                                return
                            # Raises error to throw if needed.
                            waiter_future.result(timeout=0)

                        try:
                            datagram: bytes = client_data.datagram_queue.get_nowait()
                        except _QueueEmpty as exc:  # pragma: no cover
                            raise client_data.inconsistent_state_error() from exc
                        if timeout is not None:
                            _utils.validate_timeout_delay(timeout, positive_check=True)
                        # Ignore sent timeout here, we already have the datagram.
                        try:
                            request = self.__protocol.build_packet_from_datagram(datagram)
                        except DatagramProtocolParseError:
                            raise
                        except Exception as exc:
                            raise RuntimeError("protocol.build_packet_from_datagram() crashed") from exc
                        finally:
                            del datagram
                    except BaseException as exc:
                        timeout = request_handler_context.run(request_handler_generator.throw, exc)
                    else:
                        timeout = request_handler_context.run(request_handler_generator.send, request)
                    finally:
                        request = None
                except StopIteration:
                    return

                try:
                    timeout = _utils.validate_optional_timeout_delay(timeout, positive_check=True)
                except BaseException as exc:
                    waiter_future = concurrent.futures.Future()
                    waiter_future.set_exception(exc)
                else:
                    with client_data.state_lock:
                        if client_data.datagram_queue.empty():
                            waiter_future = client_handler_token.register_waiter(
                                address=client_ctx.address,
                                deadline=_get_current_time() + timeout,
                                wakeup_socketpair=self.__wakeup_socketpair,
                            )
                        else:
                            waiter_future = None

                if waiter_future is None:
                    return self.__serve_requests__schedule_client_handler(
                        None,
                        client_ctx=client_ctx,
                        client_data=client_data,
                        request_handler_context=request_handler_context,
                        request_handler_generator=request_handler_generator,
                        client_handler_token=client_handler_token,
                        task_exit_stack=task_exit_stack,
                        executor=executor,
                        should_restart_handle=should_restart_handle,
                    )

                task_exit_stack = task_exit_stack.pop_all()
                waiter_future.add_done_callback(
                    functools.partial(
                        self.__serve_requests__schedule_client_handler,
                        client_ctx=client_ctx,
                        client_data=client_data,
                        request_handler_context=request_handler_context,
                        request_handler_generator=request_handler_generator,
                        client_handler_token=client_handler_token,
                        task_exit_stack=task_exit_stack,
                        executor=executor,
                        should_restart_handle=should_restart_handle,
                    )
                )
        finally:
            waiter_future = None  # Break reference cycle with request future on error.
            self.__detach_server()

    def __serve_requests__schedule_client_handler(
        self,
        waiter_future: concurrent.futures.Future[None] | None,
        /,
        *,
        client_ctx: DatagramClientContext[_T_Response, _T_Address],
        client_data: _ClientData,
        request_handler_context: contextvars.Context,
        request_handler_generator: Generator[float | None, _T_Request],
        client_handler_token: _ClientHandlerToken[_T_Request, _T_Response, _T_Address],
        task_exit_stack: contextlib.ExitStack,
        executor: concurrent.futures.Executor,
        should_restart_handle: _utils.Flag,
    ) -> None:
        task_exit_stack = task_exit_stack.pop_all()
        try:
            handler_future = executor.submit(
                self.__serve_requests__handle_client_request,
                waiter_future,
                client_ctx=client_ctx,
                client_data=client_data,
                request_handler_context=request_handler_context,
                request_handler_generator=request_handler_generator,
                client_handler_token=client_handler_token,
                task_exit_stack=task_exit_stack,
                executor=executor,
                should_restart_handle=should_restart_handle,
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

    #################################################################################
    ########################## common functions for server ##########################
    #################################################################################

    def __ask_server_shutdown(self) -> None:
        if not self.__is_shut_down.is_set():
            self.__shutdown_request.set()
            with contextlib.suppress(OSError):
                self.__wakeup_socketpair.wakeup_thread_and_signal_safe()

    def __serve_forever_impl(
        self,
        *,
        selector_token: _SelectorToken,
        client_handler_token: _ClientHandlerToken[_T_Request, _T_Response, _T_Address],
        handler: Callable[[bytes, _T_Address], None],
        executor: concurrent.futures.Executor,
    ) -> None:
        selector = selector_token.selector
        listener = self.__listener
        shutdown_requested = self.__shutdown_request.is_set

        while not shutdown_requested():
            if (datagram_received_future := listener.try_to_receive_datagram(selector_token, handler, executor)) is not None:
                datagram_received_future.add_done_callback(self.__shutdown_on_handler_exception)
                del datagram_received_future

            selector_wait_timeout: float
            if listener.is_ready_for_reading():
                selector_wait_timeout = 0.0
            elif (selector_wait_timeout := client_handler_token.get_min_deadline() - _get_current_time()) < 0:
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
            self.__handle_events(selector, ready)
            self.__handle_pending_transports(selector)
            client_handler_token.handle_pending_waiters()

            ready.clear()

    def __handle_events(
        self,
        selector: selectors.BaseSelector,
        events: list[tuple[selectors.SelectorKey, int]],
    ) -> None:
        wakeup_socketpair = self.__wakeup_socketpair
        for key, _ in events:
            if key.fileobj is wakeup_socketpair:
                wakeup_socketpair.drain()
                continue

            selector_key_data: _SelectorKeyData = key.data
            try:
                selector.unregister(key.fileobj)
            except KeyError:
                pass
            finally:
                _set_future_result_unless_cancelled(selector_key_data.future, None)

    def __handle_pending_transports(self, selector: selectors.BaseSelector) -> None:
        # Cancel pending futures if transport has been closed asynchronously
        for key in list(selector.get_map().values()):
            match key.data:
                case _SelectorKeyData(transport=transport, future=task_future) if transport.is_closing():
                    selector.unregister(key.fileobj)
                    _cancel_future_and_notify(task_future)

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


class _ThreadSafeListener(_transports.BaseTransport, Generic[_T_Address]):
    __slots__ = (
        "__listener",
        "__close_lock",
        "__send_lock",
        "__closing_event",
        "__ready_for_reading",
        "__reader_condvar",
        "__reader_done",
        "__wakeup_socketpair",
        "__finalizer",
    )

    def __init__(
        self,
        listener: _selector_transports.SelectorDatagramListener[_T_Address],
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
        detach_server: Callable[[], None],
    ) -> None:
        self.__listener: _selector_transports.SelectorDatagramListener[_T_Address] = listener
        self.__close_lock = threading.Lock()
        self.__send_lock = threading.Lock()
        self.__closing_event = threading.Event()
        self.__ready_for_reading = threading.Event()
        self.__ready_for_reading.set()
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
        with self.__close_lock, self.__send_lock:
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

    def send_to(self, data: bytes | bytearray | memoryview, address: _T_Address, timeout: float) -> None:
        with _utils.lock_with_timeout(self.__send_lock, timeout) as timeout:
            return self.__listener.send_to(data, address, timeout)

    def is_ready_for_reading(self) -> bool:
        return self.__ready_for_reading.is_set()

    def try_to_receive_datagram(
        self,
        selector_token: _SelectorToken,
        handler: Callable[[bytes, _T_Address], _T_Return],
        executor: concurrent.futures.Executor,
    ) -> concurrent.futures.Future[_T_Return] | None:
        if not self.__ready_for_reading.is_set():
            return None

        with self.__close_lock:
            self.__ready_for_reading.clear()
            try:
                if self.__listener.is_closed():
                    # server.close() called in another thread.
                    # keep flag to False forever.
                    return None
                datagram_handler_future = self.__listener.recv_noblock_from(handler, executor)
            except (_selector_transports.WouldBlockOnRead, _selector_transports.WouldBlockOnWrite) as exc:
                listener_wait_future = selector_token.register(
                    transport=self,
                    fileno=exc.fileno,
                    events=_selector_event_from_exc(exc),
                    reader_condvar=self.__reader_condvar,
                    reader_done=self.__reader_done,
                )
                listener_wait_future.add_done_callback(self.__on_listener_wait_future_done)
                return None
            else:
                self.__ready_for_reading.set()
                return datagram_handler_future

    def __on_listener_wait_future_done(self, future: concurrent.futures.Future[Any]) -> None:
        if future.done() and not future.cancelled():
            self.__ready_for_reading.set()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, frozen=True, eq=False, slots=True)
class _SelectorToken:
    selector: selectors.BaseSelector
    __closed: _utils.Flag = dataclasses.field(init=False, default_factory=_utils.Flag)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
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
        transport: _ThreadSafeListener[Any],
        fileno: int,
        events: selectors._EventMask,
        reader_condvar: threading.Condition,
        reader_done: _utils.Flag,
        _future_factory: Callable[[], concurrent.futures.Future[Any]] = concurrent.futures.Future,
    ) -> concurrent.futures.Future[None]:
        assert reader_done.is_set()  # nosec assert_used

        future: concurrent.futures.Future[None] = _future_factory()

        with reader_condvar:
            if self.__closed.is_set() or transport.is_closing():
                _cancel_future_and_notify(future)
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
                data=_SelectorKeyData(transport=transport, future=future),
            )
            future.add_done_callback(functools.partial(self.__unregister_on_future_cancel, key=key))
        except BaseException:
            future.cancel()
            raise
        return future

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
    ) -> None:
        if future.cancelled():
            try:
                self.selector.unregister(key.fileobj)
            except KeyError:
                pass


class _SelectorKeyData(NamedTuple):
    transport: _ThreadSafeListener[Any]
    future: concurrent.futures.Future[None]


@dataclasses.dataclass(kw_only=True, frozen=True, eq=False, slots=True)
class _ClientHandlerToken(Generic[_T_Request, _T_Response, _T_Address]):
    server: SelectorDatagramServer[Any, _T_Response, _T_Address]
    datagram_received_cb: Callable[[DatagramClientContext[_T_Response, _T_Address]], Generator[float | None, _T_Request]]
    default_context: contextvars.Context

    __waiters: dict[_T_Address, _ClientHandlerKeyData] = dataclasses.field(init=False, default_factory=dict)
    __waiters_lock: threading.RLock = dataclasses.field(init=False, default_factory=threading.RLock)
    __client_data_cache: weakref.WeakValueDictionary[_T_Address, _ClientData] = dataclasses.field(
        init=False, default_factory=weakref.WeakValueDictionary
    )
    __client_ctx_cache: weakref.WeakValueDictionary[_T_Address, DatagramClientContext[_T_Response, _T_Address]] = (
        dataclasses.field(init=False, default_factory=weakref.WeakValueDictionary)
    )
    __closed: _utils.Flag = dataclasses.field(init=False, default_factory=_utils.Flag)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        with self.__waiters_lock:
            self.__closed.set()

            waiters = self.__waiters.copy()
            self.__waiters.clear()

            # Cancel pending futures
            for key in waiters.values():
                _cancel_future_and_notify(key.future)

    def get_client_data(self, address: _T_Address) -> _ClientData:
        try:
            client_data = self.__client_data_cache[address]
        except KeyError:
            self.__client_data_cache[address] = client_data = _ClientData()
        return client_data

    def get_client_ref(self, address: _T_Address) -> DatagramClientContext[_T_Response, _T_Address]:
        try:
            client_ctx = self.__client_ctx_cache[address]
        except KeyError:
            self.__client_ctx_cache[address] = client_ctx = DatagramClientContext(address, self.server)
        return client_ctx

    def get_min_deadline(self) -> float:
        min_deadline: float = math.inf
        with self.__waiters_lock:
            for key in self.__waiters.values():
                if (deadline := key.deadline) < min_deadline:
                    min_deadline = deadline
        return min_deadline

    def pop_waiter(self, address: _T_Address) -> _ClientHandlerKeyData | None:
        with self.__waiters_lock:
            return self.__waiters.pop(address, None)

    def register_waiter(
        self,
        *,
        address: _T_Address,
        deadline: float,
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
        _future_factory: Callable[[], concurrent.futures.Future[Any]] = concurrent.futures.Future,
    ) -> concurrent.futures.Future[None]:
        with self.__waiters_lock:
            future: concurrent.futures.Future[None] = _future_factory()
            if self.__closed.is_set():
                _cancel_future_and_notify(future)
                return future

            start_time = _get_current_time()
            if deadline <= start_time:
                future.set_exception(_utils.error_from_errno(_errno.ETIMEDOUT))
                return future

            try:
                if address in self.__waiters:
                    raise AssertionError(f"{address} already registered")
                self.__waiters[address] = _ClientHandlerKeyData(future=future, deadline=deadline)
                future.add_done_callback(
                    functools.partial(self.__unregister_on_future_cancel, address=address, wakeup_socketpair=wakeup_socketpair)
                )
                wakeup_socketpair.wakeup_thread_and_signal_safe()
            except BaseException:
                future.cancel()
                raise
            return future

    def handle_pending_waiters(self) -> None:
        # Set timeout error if deadline has been reached
        with self.__waiters_lock:
            now = _get_current_time()

            for address, key in list(self.__waiters.items()):
                if key.deadline < now:
                    del self.__waiters[address]
                    _set_future_exception_unless_cancelled(key.future, _utils.error_from_errno(_errno.ETIMEDOUT))

    def __unregister_on_future_cancel(
        self,
        future: concurrent.futures.Future[Any],
        /,
        *,
        address: _T_Address,
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
    ) -> None:
        if future.cancelled():
            with self.__waiters_lock:
                try:
                    del self.__waiters[address]
                except KeyError:
                    pass
                else:
                    with contextlib.suppress(OSError):
                        wakeup_socketpair.wakeup_thread_and_signal_safe()


class _ClientHandlerKeyData(NamedTuple):
    future: concurrent.futures.Future[None]
    deadline: float


@enum.unique
class _ClientState(enum.Enum):
    TASK_PENDING = enum.auto()
    TASK_RUNNING = enum.auto()


class _ClientData:
    __slots__ = (
        "__state_lock",
        "__state",
        "__datagram_queue",
        "__weakref__",
    )

    def __init__(self) -> None:
        self.__state_lock: threading.RLock = threading.RLock()
        self.__state: _ClientState | None = None
        self.__datagram_queue: _Queue[bytes] = _Queue()

    @property
    def datagram_queue(self) -> _Queue[bytes]:
        return self.__datagram_queue

    @property
    def state_lock(self) -> threading.RLock:
        return self.__state_lock

    @property
    def state(self) -> _ClientState | None:
        return self.__state

    def register_new_client_task(self, client_task_future: concurrent.futures.Future[None]) -> None:
        client_task_future.add_done_callback(self.__on_client_handler_future_cancellation)

    def __on_client_handler_future_cancellation(self, client_task_future: concurrent.futures.Future[None], /) -> None:
        if client_task_future.cancelled():
            self.mark_done_by_cancellation()

    def mark_pending(self) -> None:
        with self.__state_lock:
            if self.__state is not None:
                raise self.inconsistent_state_error()
            self.__state = _ClientState.TASK_PENDING

    def mark_done(self) -> None:
        with self.__state_lock:
            if self.__state is not _ClientState.TASK_RUNNING:
                raise self.inconsistent_state_error()
            self.__state = None

    def mark_done_by_cancellation(self) -> None:
        with self.__state_lock:
            if self.__state is not _ClientState.TASK_PENDING:
                raise self.inconsistent_state_error()
            self.__state = None

    def mark_running(self) -> None:
        with self.__state_lock:
            if self.__state is not _ClientState.TASK_PENDING:
                raise self.inconsistent_state_error()
            self.__state = _ClientState.TASK_RUNNING

    @staticmethod
    def inconsistent_state_error() -> RuntimeError:
        msg = "The server has created too many tasks and ends up in an inconsistent state."
        note = "Please fill an issue (https://github.com/francis-clairicia/EasyNetwork/issues)"
        return _utils.exception_with_notes(RuntimeError(msg), note)


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
