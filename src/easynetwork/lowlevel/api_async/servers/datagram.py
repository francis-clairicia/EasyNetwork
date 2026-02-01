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
"""Low-level asynchronous datagram servers module."""

from __future__ import annotations

__all__ = ["AsyncDatagramServer", "DatagramClientContext"]

import contextlib
import contextvars
import dataclasses
import enum
import logging
import math
import warnings
import weakref
from collections import deque
from collections.abc import AsyncGenerator, Callable, Hashable, Mapping
from typing import Any, Generic, NoReturn, TypeVar

from ...._typevars import _T_Request, _T_Response
from ....exceptions import DatagramProtocolParseError, UnsupportedOperation
from ....protocol import DatagramProtocol
from ... import _utils
from ...request_handler import RecvAncillaryDataParams, RecvParams
from ..backend.abc import AsyncBackend, ICondition, TaskGroup
from ..transports import abc as _transports

_T_Address = TypeVar("_T_Address", bound=Hashable)


# Python 3.12.3 regression for weakref slots on generics
# See https://github.com/python/cpython/issues/118033
# @dataclasses.dataclass(frozen=True, unsafe_hash=True, slots=True, weakref_slot=True)


@dataclasses.dataclass(frozen=True, unsafe_hash=True)
class DatagramClientContext(Generic[_T_Response, _T_Address]):
    """
    Contains information about the remote endpoint which sends a datagram.
    """

    __slots__ = (
        "address",
        "server",
        "__weakref__",
    )

    address: _T_Address
    """The client address."""

    server: AsyncDatagramServer[Any, _T_Response, _T_Address]
    """The server which receives the datagram."""

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.server.backend()


class AsyncDatagramServer(_transports.AsyncBaseTransport, Generic[_T_Request, _T_Response, _T_Address]):
    """
    Datagram packet listener interface.
    """

    __slots__ = (
        "__listener",
        "__protocol",
        "__serve_guard",
    )

    def __init__(
        self,
        listener: _transports.AsyncDatagramListener[_T_Address],
        protocol: DatagramProtocol[_T_Response, _T_Request],
    ) -> None:
        """
        Parameters:
            listener: the transport implementation to wrap.
            protocol: The :term:`protocol object` to use.
        """
        if not isinstance(listener, _transports.AsyncDatagramListener):
            raise TypeError(f"Expected an AsyncDatagramListener object, got {listener!r}")
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__listener: _transports.AsyncDatagramListener[_T_Address] = listener
        self.__protocol: DatagramProtocol[_T_Response, _T_Request] = protocol
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receiving datagrams")

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            listener = self.__listener
        except AttributeError:
            return
        if not listener.is_closing():
            msg = f"unclosed server {self!r} pointing to {listener!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

    def is_closing(self) -> bool:
        """
        Checks if the server is closed or in the process of being closed.

        Returns:
            :data:`True` if the server is closed.
        """
        return self.__listener.is_closing()

    async def aclose(self) -> None:
        """
        Closes the server.
        """
        await self.__listener.aclose()

    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def backend(self) -> AsyncBackend:
        return self.__listener.backend()

    async def send_packet_to(self, packet: _T_Response, address: _T_Address) -> None:
        """
        Sends `packet` to the remote endpoint `address`.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
            address: the remote endpoint address.
        """
        try:
            datagram: bytes = self.__protocol.make_datagram(packet)
        except Exception as exc:
            raise RuntimeError("protocol.make_datagram() crashed") from exc

        await self.__listener.send_to(datagram, address)

    async def send_packet_with_ancillary_to(self, packet: _T_Response, ancillary_data: Any, address: _T_Address) -> None:
        """
        Sends `packet` to the remote endpoint `address` with ancillary data.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
            ancillary_data: The ancillary data to send along with the message.
            address: the remote endpoint address.
        """
        try:
            datagram: bytes = self.__protocol.make_datagram(packet)
        except Exception as exc:
            raise RuntimeError("protocol.make_datagram() crashed") from exc

        await self.__listener.send_with_ancillary_to(datagram, ancillary_data, address)

    async def serve(
        self,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | RecvParams | None, _T_Request]
        ],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        """
        Receive incoming datagrams as they come in and start tasks to handle them.

        .. versionchanged:: NEXT_VERSION
            The async generator returned by `datagram_received_cb` may yield a :class:`.RecvParams` object.

        .. deprecated:: NEXT_VERSION
            If the async generator returned by `datagram_received_cb` yields a number, a :exc:`DeprecationWarning` will be emitted.
            Use :class:`.RecvParams` instead.

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
            task_group: the task group that will be used to start tasks for handling each received datagram.
        """
        await self.__serve_impl(datagram_received_cb, task_group)

    async def serve_with_ancillary(
        self,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | RecvParams | None, _T_Request]
        ],
        ancillary_bufsize: int,
        ancillary_data_unused: Callable[[Any, _T_Address], object] | None = None,
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        """
        Receive incoming datagrams with ancillary data as they come in and start tasks to handle them.

        See :meth:`serve` methods for more information.

        .. deprecated:: NEXT_VERSION
            If the async generator returned by `datagram_received_cb` yields a number, a :exc:`DeprecationWarning` will be emitted.
            Use :class:`.RecvParams` instead.

        Parameters:
            datagram_received_cb: a callable that will be used to handle each received datagram.
            ancillary_bufsize: the maximum buffer size for ancillary data.
            ancillary_data_unused: Action to perform if the request handler did not claim the received ancillary data.
            task_group: the task group that will be used to start tasks for handling each received datagram.
        """
        if not isinstance(ancillary_bufsize, int) or ancillary_bufsize <= 0:
            raise ValueError("ancillary_bufsize must be a strictly positive integer")

        await self.__serve_impl(
            datagram_received_cb,
            task_group,
            ancillary_data_params=_ServerAncillaryDataParams(
                bufsize=ancillary_bufsize,
                data_unused=ancillary_data_unused,
            ),
        )

    async def __serve_impl(
        self,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | RecvParams | None, _T_Request]
        ],
        task_group: TaskGroup | None,
        *,
        ancillary_data_params: _ServerAncillaryDataParams[_T_Address] | None = None,
    ) -> NoReturn:
        with self.__serve_guard:
            listener = self.__listener
            backend = listener.backend()

            client_data_cache: weakref.WeakValueDictionary[_T_Address, _ClientData] = weakref.WeakValueDictionary()
            client_ctx_cache: weakref.WeakValueDictionary[_T_Address, DatagramClientContext[_T_Response, _T_Address]] = (
                weakref.WeakValueDictionary()
            )

            default_context = contextvars.copy_context()

            async with backend.create_task_group() if task_group is None else contextlib.nullcontext(task_group) as task_group:

                # The responsibility for ordering datagram reception is shifted to the listener.
                async def handler(datagram: bytes, address: _T_Address, ancillary_data: Any | None = None, /) -> None:
                    try:
                        client_data = client_data_cache[address]
                    except KeyError:
                        client_data_cache[address] = client_data = _ClientData(backend)

                    nb_datagrams_in_queue = await client_data.push_datagram(datagram, ancillary_data)
                    del datagram

                    if client_data.state is None and nb_datagrams_in_queue > 0:
                        try:
                            client_ctx = client_ctx_cache[address]
                        except KeyError:
                            client_ctx_cache[address] = client_ctx = DatagramClientContext(address, self)

                        client_data.mark_pending()
                        await self.__client_coroutine(
                            datagram_received_cb,
                            client_ctx,
                            client_data,
                            task_group,
                            ancillary_data_params,
                            default_context,
                        )

                if ancillary_data_params is None:
                    await listener.serve(handler, task_group)
                else:
                    await listener.serve_with_ancillary(
                        lambda datagram, ancillary_data, address: handler(datagram, address, ancillary_data),
                        ancillary_data_params.bufsize,
                        task_group,
                    )

    async def __client_coroutine(
        self,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | RecvParams | None, _T_Request]
        ],
        client_ctx: DatagramClientContext[_T_Response, _T_Address],
        client_data: _ClientData,
        task_group: TaskGroup,
        ancillary_data_params: _ServerAncillaryDataParams[_T_Address] | None,
        default_context: contextvars.Context,
    ) -> None:
        client_data.mark_running()
        try:
            await self.__client_coroutine_inner_loop(
                request_handler_generator=datagram_received_cb(client_ctx),
                client_data=client_data,
                client_address=client_ctx.address,
                server_ancillary_data_params=ancillary_data_params,
            )
        except Exception as exc:
            _utils.remove_traceback_frames_in_place(exc, 1)
            self.__unhandled_exception_log(exc)
        finally:
            client_data.mark_done()

        try:
            self.__on_client_coroutine_task_done(
                datagram_received_cb=datagram_received_cb,
                client_ctx=client_ctx,
                client_data=client_data,
                task_group=task_group,
                ancillary_data_params=ancillary_data_params,
                default_context=default_context,
            )
        except Exception as exc:
            self.__unhandled_exception_log(exc)

    @classmethod
    def __unhandled_exception_log(cls, exc: BaseException, /) -> None:
        logger = logging.getLogger(__name__)
        logger.error("Unhandled exception: %s", exc, exc_info=exc)

    async def __client_coroutine_inner_loop(
        self,
        *,
        request_handler_generator: AsyncGenerator[float | RecvParams | None, _T_Request],
        client_data: _ClientData,
        client_address: _T_Address,
        server_ancillary_data_params: _ServerAncillaryDataParams[_T_Address] | None,
    ) -> None:
        timeout: float
        recv_params: RecvParams
        datagram: bytes
        ancillary_data: Any | None = None
        try:
            datagram, ancillary_data = client_data.pop_datagram_no_wait()
            recv_params = _rcv(await anext(request_handler_generator))
        except StopAsyncIteration:
            self.__handle_ancillary_data(
                ancillary_data=ancillary_data,
                recv_with_ancillary=None,
                server_ancillary_data_params=server_ancillary_data_params,
                client_address=client_address,
            )
            return
        else:
            request: _T_Request | None
            try:
                try:
                    try:
                        _utils.validate_optional_timeout_delay(recv_params.timeout, positive_check=True)
                        # Ignore sent timeout here, we already have the datagram.
                    finally:
                        # Handle ancillary data in finally block for stack manipulation.
                        # The original error (invalid timeout) will appear even if the callback fails too.
                        self.__handle_ancillary_data(
                            ancillary_data=ancillary_data,
                            recv_with_ancillary=recv_params.recv_with_ancillary,
                            server_ancillary_data_params=server_ancillary_data_params,
                            client_address=client_address,
                        )
                    request = self.__parse_datagram(datagram, self.__protocol)
                except BaseException as exc:
                    recv_params = _rcv(await request_handler_generator.athrow(exc))
                else:
                    del datagram  # Drop datagram reference before proceeding.
                    recv_params = _rcv(await request_handler_generator.asend(request))
                finally:
                    request = ancillary_data = None
            except StopAsyncIteration:
                return

            _timeout_scope_ctx = client_data.backend.timeout
            _no_timeout_scope = contextlib.nullcontext()
            while True:
                try:
                    try:
                        match _utils.validate_optional_timeout_delay(recv_params.timeout, positive_check=True):
                            case math.inf:
                                timeout_scope = _no_timeout_scope
                            case timeout:
                                timeout_scope = _timeout_scope_ctx(timeout)
                        with timeout_scope:
                            datagram, ancillary_data = await client_data.pop_datagram()
                        self.__handle_ancillary_data(
                            ancillary_data=ancillary_data,
                            recv_with_ancillary=recv_params.recv_with_ancillary,
                            server_ancillary_data_params=server_ancillary_data_params,
                            client_address=client_address,
                        )
                        request = self.__parse_datagram(datagram, self.__protocol)
                    except BaseException as exc:
                        del recv_params
                        recv_params = _rcv(await request_handler_generator.athrow(exc))
                    else:
                        del datagram, recv_params
                        recv_params = _rcv(await request_handler_generator.asend(request))
                    finally:
                        request = ancillary_data = None
                except StopAsyncIteration:
                    break
        finally:
            await request_handler_generator.aclose()

    def __on_client_coroutine_task_done(
        self,
        *,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | RecvParams | None, _T_Request]
        ],
        client_ctx: DatagramClientContext[_T_Response, _T_Address],
        client_data: _ClientData,
        task_group: TaskGroup,
        ancillary_data_params: _ServerAncillaryDataParams[_T_Address] | None,
        default_context: contextvars.Context,
    ) -> None:
        if client_data.queue_is_empty():
            return

        client_data.mark_pending()

        # Why copy the context before calling run()?
        # Short answer: asyncio.eager_task_factory :)
        #
        # If asyncio's eager task is enabled in this event loop, there is a chance
        # to have a nested call if the request handler does not yield
        # and we end up with this error:
        # RuntimeError: cannot enter context: <_contextvars.Context object at ...> is already entered
        # To avoid that, we always use a new context. The performance cost is negligible.
        # See this functional test for a real situation:
        # test____serve_forever____too_many_datagrams_while_request_handle_is_performed
        default_context.copy().run(
            task_group.start_soon,
            self.__client_coroutine,
            datagram_received_cb,
            client_ctx,
            client_data,
            task_group,
            ancillary_data_params,
            default_context,
        )

    @staticmethod
    def __parse_datagram(
        datagram: bytes,
        protocol: DatagramProtocol[_T_Response, _T_Request],
    ) -> _T_Request:
        try:
            return protocol.build_packet_from_datagram(datagram)
        except DatagramProtocolParseError:
            raise
        except Exception as exc:
            raise RuntimeError("protocol.build_packet_from_datagram() crashed") from exc

    @staticmethod
    def __handle_ancillary_data(
        *,
        ancillary_data: Any | None,
        recv_with_ancillary: RecvAncillaryDataParams | None,
        server_ancillary_data_params: _ServerAncillaryDataParams[_T_Address] | None,
        client_address: _T_Address,
    ) -> None:
        if server_ancillary_data_params is None:
            if recv_with_ancillary is not None:
                raise UnsupportedOperation("The server is not configured to handle ancillary data.")
        elif ancillary_data is not None:
            if recv_with_ancillary is not None:
                try:
                    recv_with_ancillary.data_received(ancillary_data)
                except Exception as exc:
                    raise RuntimeError("RecvAncillaryDataParams.data_received() crashed") from exc
            elif (ancillary_data_unused := server_ancillary_data_params.data_unused) is not None:
                try:
                    ancillary_data_unused(ancillary_data, client_address)
                except Exception as exc:
                    raise RuntimeError("ancillary_data_unused() crashed") from exc

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@dataclasses.dataclass(kw_only=True, frozen=True, slots=True)
class _ServerAncillaryDataParams(Generic[_T_Address]):
    bufsize: int
    data_unused: Callable[[Any, _T_Address], object] | None


@enum.unique
class _ClientState(enum.Enum):
    TASK_PENDING = enum.auto()
    TASK_RUNNING = enum.auto()


class _ClientData:
    __slots__ = (
        "__backend",
        "__state",
        "_queue_condition",
        "_datagram_queue",
        "__weakref__",
    )

    def __init__(self, backend: AsyncBackend) -> None:
        self.__backend: AsyncBackend = backend
        self.__state: _ClientState | None = None
        self._queue_condition: ICondition = backend.create_condition_var()
        self._datagram_queue: deque[tuple[bytes, Any | None]] = deque()

    @property
    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def state(self) -> _ClientState | None:
        return self.__state

    def queue_is_empty(self) -> bool:
        return not self._datagram_queue

    async def push_datagram(self, datagram: bytes, ancillary_data: Any | None) -> int:
        self._datagram_queue.append((datagram, ancillary_data))

        # Do not need to notify anyone if state is None.
        if self.__state is not None:
            async with (queue_condition := self._queue_condition):
                queue_condition.notify()

        return len(self._datagram_queue)

    def pop_datagram_no_wait(self) -> tuple[bytes, Any | None]:
        return self._datagram_queue.popleft()

    async def pop_datagram(self) -> tuple[bytes, Any | None]:
        async with (queue_condition := self._queue_condition):
            queue = self._datagram_queue
            while not queue:
                await queue_condition.wait()
            return queue.popleft()

    def mark_pending(self) -> None:
        if self.__state is not None:
            self.handle_inconsistent_state_error()
        self.__state = _ClientState.TASK_PENDING

    def mark_done(self) -> None:
        if self.__state is not _ClientState.TASK_RUNNING:
            self.handle_inconsistent_state_error()
        self.__state = None

    def mark_running(self) -> None:
        if self.__state is not _ClientState.TASK_PENDING:
            self.handle_inconsistent_state_error()
        self.__state = _ClientState.TASK_RUNNING

    @staticmethod
    def handle_inconsistent_state_error() -> NoReturn:
        msg = "The server has created too many tasks and ends up in an inconsistent state."
        note = "Please fill an issue (https://github.com/francis-clairicia/EasyNetwork/issues)"
        raise _utils.exception_with_notes(RuntimeError(msg), note)


def _rcv(param: float | RecvParams | None, /) -> RecvParams:
    match param:
        case RecvParams():
            return param
        case None:
            return RecvParams()
        case _:
            warnings.warn("Yielding a flat number is deprecated. Use RecvParams instead.", DeprecationWarning, stacklevel=2)
            return RecvParams(timeout=param)
