# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
"""Low-level asynchronous datagram servers module"""

from __future__ import annotations

__all__ = ["AsyncDatagramServer", "DatagramClientContext"]

import contextlib
import contextvars
import dataclasses
import enum
import warnings
import weakref
from collections import deque
from collections.abc import AsyncGenerator, Callable, Hashable, Mapping
from contextlib import AsyncExitStack, ExitStack
from typing import Any, Generic, NoReturn, TypeVar

from .... import protocol as protocol_module
from ...._typevars import _T_Request, _T_Response
from ....exceptions import DatagramProtocolParseError
from ... import _utils, typed_attr
from ..._asyncgen import AsyncGenAction, SendAction, ThrowAction
from ..backend.abc import AsyncBackend, ICondition, ILock, TaskGroup
from ..transports import abc as transports

_T_Address = TypeVar("_T_Address", bound=Hashable)


# Python 3.12.3 regression for weakref slots on generics
# See https://github.com/python/cpython/issues/118033
# @dataclasses.dataclass(frozen=True, unsafe_hash=True, slots=True, weakref_slot=True)


@dataclasses.dataclass(frozen=True, unsafe_hash=True)
class DatagramClientContext(Generic[_T_Response, _T_Address]):
    __slots__ = (
        "address",
        "server",
        "__weakref__",
    )

    address: _T_Address
    server: AsyncDatagramServer[Any, _T_Response, _T_Address]


class AsyncDatagramServer(typed_attr.TypedAttributeProvider, Generic[_T_Request, _T_Response, _T_Address]):
    __slots__ = (
        "__listener",
        "__protocol",
        "__sendto_lock",
        "__serve_guard",
        "__weakref__",
    )

    def __init__(
        self,
        listener: transports.AsyncDatagramListener[_T_Address],
        protocol: protocol_module.DatagramProtocol[_T_Response, _T_Request],
    ) -> None:
        if not isinstance(listener, transports.AsyncDatagramListener):
            raise TypeError(f"Expected an AsyncDatagramListener object, got {listener!r}")
        if not isinstance(protocol, protocol_module.DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        self.__listener: transports.AsyncDatagramListener[_T_Address] = listener
        self.__protocol: protocol_module.DatagramProtocol[_T_Response, _T_Request] = protocol
        self.__sendto_lock: ILock = listener.backend().create_lock()
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

    @_utils.inherit_doc(transports.AsyncBaseTransport)
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
        async with self.__sendto_lock:
            await self.__listener.send_to(datagram, address)

    async def serve(
        self,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | None, _T_Request]
        ],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        with self.__serve_guard:
            listener = self.__listener
            backend = listener.backend()
            client_cache: weakref.WeakValueDictionary[_T_Address, _ClientToken[_T_Response, _T_Address]]
            client_cache = weakref.WeakValueDictionary()
            default_context = contextvars.copy_context()

            async with AsyncExitStack() as stack:
                if task_group is None:
                    task_group = await stack.enter_async_context(backend.create_task_group())

                # The responsibility for ordering datagram reception is shifted to the listener.
                async def handler(datagram: bytes, address: _T_Address, /) -> None:
                    try:
                        client = client_cache[address]
                    except KeyError:
                        client_cache[address] = client = _ClientToken(DatagramClientContext(address, self), _ClientData(backend))
                        new_client_task = True
                    else:
                        new_client_task = client.data.state is None

                    if new_client_task:
                        client.data.mark_pending()
                        await self.__client_coroutine(datagram_received_cb, datagram, client, task_group, default_context)
                    else:
                        await client.data.push_datagram(datagram)

                await listener.serve(handler, task_group)

            raise AssertionError("Expected code to be unreachable.")

    async def __client_coroutine(
        self,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | None, _T_Request]
        ],
        datagram: bytes,
        client: _ClientToken[_T_Response, _T_Address],
        task_group: TaskGroup,
        default_context: contextvars.Context,
    ) -> None:
        client_data = client.data
        async with client_data.task_lock:
            with ExitStack() as exit_stack:
                #####################################################################################################
                # CRITICAL SECTION
                # This block must not have any asynchronous function calls
                # or add any asynchronous callbacks/contexts to the exit stack.
                client_data.mark_running()
                exit_stack.callback(
                    self.__on_task_done,
                    datagram_received_cb=datagram_received_cb,
                    client=client,
                    task_group=task_group,
                    default_context=default_context,
                )
                #####################################################################################################

                request_handler_generator = datagram_received_cb(client.ctx)
                timeout: float | None

                try:
                    # Ignore sent timeout here, we already have the datagram.
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    return
                else:
                    action: AsyncGenAction[_T_Request] = self.__parse_datagram(datagram, self.__protocol)
                    try:
                        timeout = await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        return
                    finally:
                        del action

                    del datagram
                    while True:
                        try:
                            with contextlib.nullcontext() if timeout is None else client_data.backend.timeout(timeout):
                                datagram = await client_data.pop_datagram()

                            action = self.__parse_datagram(datagram, self.__protocol)
                            del datagram
                        except BaseException as exc:
                            action = ThrowAction(exc)
                        try:
                            timeout = await action.asend(request_handler_generator)
                        except StopAsyncIteration:
                            break
                        finally:
                            del action
                finally:
                    await request_handler_generator.aclose()

    def __on_task_done(
        self,
        datagram_received_cb: Callable[
            [DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[float | None, _T_Request]
        ],
        client: _ClientToken[_T_Response, _T_Address],
        task_group: TaskGroup,
        default_context: contextvars.Context,
    ) -> None:
        client.data.mark_done()
        try:
            pending_datagram = client.data.pop_datagram_no_wait()
        except IndexError:
            return

        client.data.mark_pending()
        default_context.run(
            task_group.start_soon,
            self.__client_coroutine,
            datagram_received_cb,
            pending_datagram,
            client,
            task_group,
            default_context,
        )

    @staticmethod
    def __parse_datagram(
        datagram: bytes,
        protocol: protocol_module.DatagramProtocol[_T_Response, _T_Request],
    ) -> AsyncGenAction[_T_Request]:
        try:
            try:
                request = protocol.build_packet_from_datagram(datagram)
            except DatagramProtocolParseError:
                raise
            except Exception as exc:
                raise RuntimeError("protocol.build_packet_from_datagram() crashed") from exc
        except BaseException as exc:
            return ThrowAction(exc)
        else:
            return SendAction(request)

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@enum.unique
class _ClientState(enum.Enum):
    TASK_PENDING = enum.auto()
    TASK_RUNNING = enum.auto()


# Python 3.12.3 regression for weakref slots on generics
# See https://github.com/python/cpython/issues/118033
# @dataclasses.dataclass(slots=True, weakref_slot=True)


@dataclasses.dataclass()
class _ClientToken(Generic[_T_Response, _T_Address]):
    __slots__ = (
        "ctx",
        "data",
        "__weakref__",
    )

    ctx: DatagramClientContext[_T_Response, _T_Address]
    data: _ClientData


class _ClientData:
    __slots__ = (
        "__backend",
        "__task_lock",
        "__state",
        "_queue_condition",
        "_datagram_queue",
    )

    def __init__(self, backend: AsyncBackend) -> None:
        self.__backend: AsyncBackend = backend
        self.__task_lock: ILock = backend.create_lock()
        self.__state: _ClientState | None = None
        self._queue_condition: ICondition | None = None
        self._datagram_queue: deque[bytes] | None = None

    @property
    def backend(self) -> AsyncBackend:
        return self.__backend

    @property
    def task_lock(self) -> ILock:
        return self.__task_lock

    @property
    def state(self) -> _ClientState | None:
        return self.__state

    async def push_datagram(self, datagram: bytes) -> None:
        self.__ensure_queue().append(datagram)
        if (queue_condition := self._queue_condition) is not None:
            async with queue_condition:
                queue_condition.notify()

    def pop_datagram_no_wait(self) -> bytes:
        if not (queue := self._datagram_queue):
            raise IndexError("pop from an empty deque")
        return queue.popleft()

    async def pop_datagram(self) -> bytes:
        queue_condition = self.__ensure_queue_condition_var()
        async with queue_condition:
            queue = self.__ensure_queue()
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

    def __ensure_queue(self) -> deque[bytes]:
        if (queue := self._datagram_queue) is None:
            self._datagram_queue = queue = deque()
        return queue

    def __ensure_queue_condition_var(self) -> ICondition:
        if (cond := self._queue_condition) is None:
            self._queue_condition = cond = self.__backend.create_condition_var()
        return cond

    @staticmethod
    def handle_inconsistent_state_error() -> NoReturn:
        msg = "The server has created too many tasks and ends up in an inconsistent state."
        note = "Please fill an issue (https://github.com/francis-clairicia/EasyNetwork/issues)"
        raise _utils.exception_with_notes(RuntimeError(msg), note)
