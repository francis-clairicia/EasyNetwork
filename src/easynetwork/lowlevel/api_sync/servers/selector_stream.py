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
"""Low-level stream servers module."""

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
from collections.abc import Callable, Generator, Mapping
from typing import Any, Generic, Literal, Self, TypeVar, assert_never

from ...._typevars import _T_Request, _T_Response
from ....protocol import AnyStreamProtocolType
from ... import _stream, _utils, _wakeup_socketpair
from ..transports import abc as _transports, base_selector as _selector_transports

_T_Return = TypeVar("_T_Return")


class ConnectedStreamClient(_transports.BaseTransport, Generic[_T_Response]):
    """
    Write-end of the connected client.
    """

    __slots__ = (
        "__transport",
        "__producer",
        "__send_lock",
        "__closing_event",
        "__reader_condvar",
        "__reader_done",
        "__wakeup_socketpair",
    )

    def __init__(
        self,
        *,
        _transport: _transports.StreamWriteTransport,
        _producer: _stream.StreamDataProducer[_T_Response],
        _reader_condvar: threading.Condition,
        _reader_done: _utils.Flag,
        _wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
    ) -> None:
        super().__init__()

        self.__transport: _transports.StreamWriteTransport = _transport
        self.__producer: _stream.StreamDataProducer[_T_Response] = _producer
        self.__send_lock = threading.Lock()
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
        with self.__send_lock:
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
        with self.__send_lock:
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
        with self.__send_lock:
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
        self.__listener = _ThreadSafeListener(listener, self.__wakeup_socketpair)
        self.__protocol: AnyStreamProtocolType[_T_Response, _T_Request] = protocol
        self.__max_recv_size: int = max_recv_size
        self.__selector_factory: Callable[[], selectors.BaseSelector] = selector_factory
        self.__serve_guard = _utils.ThreadSafeResourceGuard("another task is currently accepting new connections")
        self.__is_shut_down = threading.Event()
        self.__is_shut_down.set()
        self.__shutdown_request = threading.Event()

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
        self.__listener.close()

    def shutdown(self, timeout: float | None = None) -> None:
        """
        Asks for the server to stop. Thread-safe.

        All active client tasks will be cancelled.

        Warning:
            Do not call this method in the :meth:`serve_forever` thread; it will cause a deadlock.

        Parameters:
            timeout: The maximum amount of seconds to wait.
        """
        if not self.__is_shut_down.is_set():
            self.__shutdown_request.set()
            self.__wakeup_socketpair.wakeup_thread_and_signal_safe()
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
            worker_strategy: Decides whether
            disconnect_error_filter: a callable that returns :data:`True` if the exception is the result of a pipe disconnect.
        """
        with self.__serve_guard, contextlib.ExitStack() as stack:
            self.__is_shut_down.clear()
            try:
                selector = stack.enter_context(self.__selector_factory())
                stack.callback(self.__wakeup_socketpair_drain_without_errors)
                match worker_strategy:
                    case "clients":
                        self.__serve_clients(
                            selector=selector,
                            client_connected_cb=client_connected_cb,
                            executor=executor,
                            disconnect_error_filter=disconnect_error_filter,
                        )
                    case "requests":
                        self.__serve_requests(
                            selector=selector,
                            client_connected_cb=client_connected_cb,
                            executor=executor,
                            disconnect_error_filter=disconnect_error_filter,
                        )
                    case _:
                        assert_never(worker_strategy)
            finally:
                self.__is_shut_down.set()
                self.__shutdown_request.clear()

    def __wakeup_socketpair_drain_without_errors(self) -> None:
        with contextlib.suppress(Exception):
            self.__wakeup_socketpair.drain()

    ################################################################################
    ########################## "requests" worker strategy ##########################
    ################################################################################

    def __serve_requests(
        self,
        *,
        selector: selectors.BaseSelector,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], Generator[float | None, _T_Request]],
        executor: concurrent.futures.Executor,
        disconnect_error_filter: Callable[[Exception], bool] | None = None,
    ) -> None:
        raise NotImplementedError

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
    ) -> None:
        with _ThreadSafeSelectorToken(selector=selector) as selector_token:

            default_context = contextvars.copy_context()

            def handler(transport: _selector_transports.SelectorStreamTransport, /) -> None:
                context = default_context.copy()
                try:
                    return context.run(
                        self.__serve_clients__client_task,
                        transport,
                        selector_token,
                        client_connected_cb,
                        disconnect_error_filter,
                    )
                except BaseException as exc:
                    _utils.remove_traceback_frames_in_place(exc, 1)
                    raise
                finally:
                    del context

            self.__serve_forever_impl(selector_token=selector_token, handler=handler, executor=executor)

    def __serve_clients__client_task(
        self,
        transport: _selector_transports.SelectorStreamTransport,
        selector_token: _ThreadSafeSelectorToken,
        client_connected_cb: Callable[[ConnectedStreamClient[_T_Response]], Generator[float | None, _T_Request]],
        disconnect_error_filter: Callable[[Exception], bool] | None,
    ) -> None:
        if not isinstance(transport, _selector_transports.SelectorStreamTransport):
            raise TypeError(f"Expected a SelectorStreamTransport object, got {transport!r}")

        # wakeup_socketpair = self.__wakeup_socketpair

        # from ....protocol import BufferedStreamProtocol, StreamProtocol

        with contextlib.ExitStack() as task_exit_stack:
            task_exit_stack.push(self.__unhandled_exception_log)

            # By default, abort the connection at the end of the task.
            transport_close_exit_stack = task_exit_stack.enter_context(contextlib.ExitStack())
            transport_close_exit_stack.callback(transport.abort)

        raise NotImplementedError

    #################################################################################
    ########################## common functions for server ##########################
    #################################################################################

    def __serve_forever_impl(
        self,
        *,
        selector_token: _ThreadSafeSelectorToken,
        handler: Callable[[_selector_transports.SelectorStreamTransport], None],
        executor: concurrent.futures.Executor,
    ) -> None:
        selector = selector_token.selector
        wakeup_socketpair = self.__wakeup_socketpair

        selector.register(wakeup_socketpair, selectors.EVENT_READ)

        while not self.__shutdown_request.is_set():
            if accept_future := self.__listener.try_accepting_new_connection(selector_token, handler, executor):
                accept_future.add_done_callback(self.__shutdown_on_handler_exception)
                del accept_future

            selector_wait_deadline = min(self.__listener.ready_at_deadline(), selector_token.get_min_deadline())

            selector_wait_timeout: float = selector_wait_deadline - time.monotonic()
            if selector_wait_timeout < 0:
                selector_wait_timeout = 0.0
            else:
                # Do not wait more than 24h.
                selector_wait_timeout = min(selector_wait_timeout, 86400.0)

            ready = selector.select(selector_wait_timeout)

            # shutdown() called during select(), exit immediately.
            if self.__shutdown_request.is_set():
                break

            del selector_wait_timeout

            with selector_token.state_lock:

                # Notify threads for ready file descriptors
                self.__handle_events(selector, ready)
                self.__handle_pending_transports(selector)

                ready.clear()

    def __handle_events(self, selector: selectors.BaseSelector, events: list[tuple[selectors.SelectorKey, int]]) -> None:
        wakeup_socketpair = self.__wakeup_socketpair
        now = time.monotonic()
        for key, _ in events:
            if key.fileobj is wakeup_socketpair:
                wakeup_socketpair.drain()
                continue

            match key.data:
                case _SelectorKeyData(future=task_future, start_time=start_time):
                    with contextlib.suppress(KeyError):
                        selector.unregister(key.fileobj)
                    if task_future.set_running_or_notify_cancel():  # pragma: no branch
                        task_future.set_result(now - start_time)
                    del task_future, start_time
                case _:  # pragma: no cover
                    raise AssertionError(f"Expected code to be unreachable, but got: {key.data!r}")

    def __handle_pending_transports(self, selector: selectors.BaseSelector) -> None:
        # Either:
        # - Cancel pending futures if transport has been closed asynchronously
        # - Set timeout error if deadline has been reached
        now = time.monotonic()
        for key in list(selector.get_map().values()):
            match key.data:
                case _SelectorKeyData(transport=transport, future=task_future) if transport.is_closing():
                    selector.unregister(key.fileobj)
                    _cancel_future_and_notify(task_future)
                case _SelectorKeyData(deadline=deadline, future=task_future) if deadline < now:
                    selector.unregister(key.fileobj)
                    if task_future.set_running_or_notify_cancel():  # pragma: no branch
                        task_future.set_exception(_utils.error_from_errno(_errno.ETIMEDOUT))

    def __shutdown_on_handler_exception(self, future: concurrent.futures.Future[Any], /) -> None:
        if not future.cancelled() and (exc := future.exception()) is not None:
            self.__unhandled_exception_log(type(exc), exc, exc.__traceback__)
            del exc
            self.__shutdown_request.set()
            self.__wakeup_socketpair.wakeup_thread_and_signal_safe()

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


class _ThreadSafeListener(_transports.BaseTransport):
    __slots__ = (
        "__listener",
        "__accept_lock",
        "__closing_event",
        "__ready_for_reading",
        "__ready_at_deadline",
        "__reader_condvar",
        "__reader_done",
        "__wakeup_socketpair",
    )

    def __init__(
        self,
        listener: _selector_transports.SelectorListener[_selector_transports.SelectorStreamTransport],
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
    ) -> None:
        self.__listener: _selector_transports.SelectorListener[_selector_transports.SelectorStreamTransport] = listener
        self.__accept_lock = threading.Lock()
        self.__closing_event = threading.Event()
        self.__ready_for_reading = threading.Event()
        self.__ready_for_reading.set()
        self.__ready_at_deadline: float = time.monotonic()
        self.__reader_condvar = threading.Condition()
        self.__reader_done = _utils.Flag()
        self.__reader_done.set()
        self.__wakeup_socketpair = wakeup_socketpair

    def is_closed(self) -> bool:
        with self.__accept_lock:
            return self.__listener.is_closed()

    def is_closing(self) -> bool:
        return self.__closing_event.is_set()

    def close(self) -> None:
        with self.__accept_lock:
            self.__closing_event.set()
            with self.__reader_condvar:
                reader_is_done = self.__reader_done.is_set
                while not reader_is_done():
                    self.__wakeup_socketpair.wakeup_thread_and_signal_safe()
                    self.__reader_condvar.wait_for(reader_is_done, timeout=1.0)
            self.__listener.close()

    def ready_at_deadline(self) -> float:
        return self.__ready_at_deadline if self.__ready_for_reading.is_set() else math.inf

    def try_accepting_new_connection(
        self,
        selector_token: _ThreadSafeSelectorToken,
        handler: Callable[[_selector_transports.SelectorStreamTransport], _T_Return],
        executor: concurrent.futures.Executor,
    ) -> concurrent.futures.Future[_T_Return] | None:
        if not self.__ready_for_reading.is_set() or time.monotonic() < self.__ready_at_deadline:
            return None

        with self.__accept_lock:
            try:
                if self.__listener.is_closed():
                    # server.close() called in another thread.
                    # keep flag to False forever.
                    self.__ready_for_reading.clear()
                    return None
                accept_future = self.__listener.accept_noblock(handler, executor)
            except (_selector_transports.WouldBlockOnRead, _selector_transports.WouldBlockOnWrite) as exc:
                self.__ready_for_reading.clear()
                listener_wait_future = selector_token.register(
                    transport=self,
                    fileno=exc.fileno,
                    events=_selector_event_from_exc(exc),
                    deadline=math.inf,
                    wakeup_socketpair=self.__wakeup_socketpair,
                    wakeup_now=False,
                    reader_condvar=self.__reader_condvar,
                    reader_done=self.__reader_done,
                )
                listener_wait_future.add_done_callback(self.__on_listener_wait_future_done)
                return None
            except Exception as exc:
                if self.__listener.is_accept_capacity_error(exc):
                    sleep_time = self.__listener.accept_capacity_error_sleep_time()
                    self.__ready_at_deadline = time.monotonic() + sleep_time
                    return None
                else:
                    raise
            else:
                return accept_future

    def __on_listener_wait_future_done(self, future: concurrent.futures.Future[Any]) -> None:
        if future.done() and not future.cancelled():
            self.__ready_for_reading.set()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, frozen=True, eq=False, slots=True)
class _ThreadSafeSelectorToken:
    selector: selectors.BaseSelector
    state_lock: threading.RLock = dataclasses.field(default_factory=threading.RLock)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        del args  # Break reference cycle with given exception.
        with self.state_lock:
            selector_keys = list(self.selector.get_map().values())

            # Cancel pending futures
            for key in selector_keys:
                match key.data:
                    case _SelectorKeyData(future=client_task_future):
                        self.selector.unregister(key.fileobj)
                        _cancel_future_and_notify(client_task_future)

            # Close all clients
            close_client_futures: list[concurrent.futures.Future[Any]] = []
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(selector_keys) or 1,
                thread_name_prefix="client-close",
            ) as close_client_executor:
                for key in selector_keys:
                    match key.data:
                        case _SelectorKeyData(transport=ConnectedStreamClient() as client):
                            close_client_futures.append(close_client_executor.submit(client.close))
            errors: list[BaseException] = [exc for f in close_client_futures if (exc := f.exception())]
            if errors:
                try:
                    raise BaseExceptionGroup("Some clients raised an error on close", errors)
                finally:
                    errors = []

    def register(
        self,
        *,
        transport: ConnectedStreamClient[Any] | _ThreadSafeListener,
        fileno: int,
        events: selectors._EventMask,
        deadline: float,
        wakeup_socketpair: _wakeup_socketpair.WakeupSocketPair,
        wakeup_now: bool,
        reader_condvar: threading.Condition,
        reader_done: _utils.Flag,
    ) -> concurrent.futures.Future[float]:
        assert reader_done.is_set()  # nosec assert_used

        with self.state_lock:
            future: concurrent.futures.Future[float] = concurrent.futures.Future()

            with reader_condvar:
                if transport.is_closing():
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
                    data=_SelectorKeyData(transport=transport, future=future, deadline=deadline, start_time=time.monotonic()),
                )
                future.add_done_callback(
                    functools.partial(self.__unregister_on_future_cancel, key=key, wakeup_socketpair=wakeup_socketpair)
                )
                if wakeup_now:
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


@dataclasses.dataclass(kw_only=True, frozen=True, eq=False, slots=True)
class _SelectorKeyData:
    transport: ConnectedStreamClient[Any] | _ThreadSafeListener
    future: concurrent.futures.Future[float]
    deadline: float
    start_time: float


# @dataclasses.dataclass(kw_only=True, eq=False, slots=True)
# class _RequestReceiver(Generic[_T_Request]):
#     transport: _selector_transports.SelectorStreamTransport
#     consumer: _stream.StreamDataConsumer[_T_Request]
#     max_recv_size: int
#     disconnect_error_filter: Callable[[Exception], bool] | None
#     selector_token: _ClientSelectorToken
#     _eof_reached: bool = dataclasses.field(init=False, default=False)

#     def __post_init__(self) -> None:
#         assert self.max_recv_size > 0, f"{self.max_recv_size=}"  # nosec assert_used

#     def next(self, timeout: float | None) -> _T_Request:
#         consumer = self.consumer
#         try:
#             return consumer.next(None)
#         except StopIteration:
#             pass

#         if timeout is None:
#             timeout = math.inf

#         while not self._eof_reached:
#             with _utils.ElapsedTime() as elapsed:
#                 chunk: bytes = transport.recv(bufsize, timeout)
#             if not chunk:
#                 self._eof_reached = True
#                 continue
#             try:
#                 return consumer.next(chunk)
#             except StopIteration:
#                 if timeout > 0:
#                     timeout = elapsed.recompute_timeout(timeout)
#                 elif len(chunk) < self.max_recv_size:
#                     break
#             finally:
#                 del chunk
#         # Loop break
#         if self._eof_reached:
#             raise StopIteration
#         raise _utils.error_from_errno(_errno.ETIMEDOUT)

#     # def __receive(self, timeout: float) -> bytes:
#     #     while True:
#     #         try:


# @dataclasses.dataclass(kw_only=True, eq=False, slots=True)
# class _BufferedRequestReceiver(Generic[_T_Request]):
#     transport: _selector_transports.SelectorStreamTransport
#     consumer: _stream.BufferedStreamDataConsumer[_T_Request]
#     disconnect_error_filter: Callable[[Exception], bool] | None
#     selector_token: _ClientSelectorToken

#     async def next(self, timeout: float | None) -> _T_Request:
#         consumer = self.consumer
#         with self.__null_timeout_ctx if timeout is None else self.__backend.timeout(timeout):
#             nbytes: int | None = None
#             while True:
#                 try:
#                     request = consumer.next(nbytes)
#                 except StopIteration:
#                     pass
#                 else:
#                     if nbytes is None:
#                         await self.__backend.cancel_shielded_coro_yield()
#                     return request
#                 with consumer.get_write_buffer() as buffer:
#                     try:
#                         nbytes = await self.transport.recv_into(buffer)
#                     except Exception as exc:
#                         if self.disconnect_error_filter is not None and self.disconnect_error_filter(exc):
#                             break
#                         raise
#                 if not nbytes:
#                     break

#         raise StopAsyncIteration


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
