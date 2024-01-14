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
"""Low-level asynchronous datagram servers module"""

from __future__ import annotations

__all__ = ["AsyncDatagramServer", "DatagramClientContext"]

import contextlib
import contextvars
import dataclasses
import enum
import weakref
from collections import deque
from collections.abc import AsyncGenerator, Callable, Hashable, Mapping
from types import TracebackType
from typing import Any, Generic, NamedTuple, NoReturn, TypeVar

from .... import protocol as protocol_module
from ...._typevars import _T_Request, _T_Response
from ....exceptions import DatagramProtocolParseError
from ... import _asyncgen, _utils, typed_attr
from ..backend.abc import AsyncBackend, ICondition, ILock, TaskGroup
from ..backend.factory import current_async_backend
from ..transports import abc as transports

_T_Address = TypeVar("_T_Address", bound=Hashable)


@dataclasses.dataclass(kw_only=True, frozen=True, unsafe_hash=True, slots=True, weakref_slot=True)
class DatagramClientContext(Generic[_T_Response, _T_Address]):
    address: _T_Address
    server: AsyncDatagramServer[Any, _T_Response, _T_Address]

    async def send_packet(self, packet: _T_Response) -> None:
        await self.server.send_packet_to(packet, self.address)


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
        self.__sendto_lock: ILock = current_async_backend().create_lock()
        self.__serve_guard: _utils.ResourceGuard = _utils.ResourceGuard("another task is currently receiving datagrams")

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

    async def send_packet_to(self, packet: _T_Response, address: _T_Address) -> None:
        """
        Sends `packet` to the remote endpoint `address`.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
            address: the remote endpoint address.
        """
        listener = self.__listener
        protocol = self.__protocol

        try:
            datagram: bytes = protocol.make_datagram(packet)
        except Exception as exc:
            raise RuntimeError("protocol.make_datagram() crashed") from exc
        finally:
            del packet
        try:
            async with self.__sendto_lock:
                await listener.send_to(datagram, address)
        finally:
            del datagram

    async def serve(
        self,
        datagram_received_cb: Callable[[DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[None, _T_Request]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        with self.__serve_guard:
            client_coroutine = self.__client_coroutine
            listener = self.__listener

            client_manager: _ClientManager[_T_Response, _T_Address] = _ClientManager(self, current_async_backend())

            async def receive_datagram(task_group: TaskGroup, /) -> None:
                datagram, address = await listener.recv_from()
                if not datagram:
                    return

                client_context = client_manager.client_context(address)
                client_data = client_manager.client_data(client_context)

                if client_data.state is None:
                    client_data.mark_pending()
                    task_group.start_soon(
                        client_coroutine,
                        datagram_received_cb,
                        datagram,
                        _ClientToken(client_context, client_data),
                        task_group,
                    )
                    return

                await client_data.push_datagram(datagram)

            async with contextlib.AsyncExitStack() as stack:
                if task_group is None:
                    task_group = await stack.enter_async_context(current_async_backend().create_task_group())
                while True:
                    await receive_datagram(task_group)

            raise AssertionError("Expected code to be unreachable.")

    async def __client_coroutine(
        self,
        datagram_received_cb: Callable[[DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[None, _T_Request]],
        datagram: bytes,
        client: _ClientToken[_T_Response, _T_Address],
        task_group: TaskGroup,
    ) -> None:
        async with client.data.task_lock:
            with contextlib.ExitStack() as critical_section_stack:
                #####################################################################################################
                # CRITICAL SECTION
                # This block must not have any asynchronous function calls
                # or add any asynchronous callbacks/contexts to the exit stack.
                client.data.mark_running()
                critical_section_stack.callback(
                    self.__enqueue_task_at_end,
                    datagram_received_cb=datagram_received_cb,
                    client=client,
                    task_group=task_group,
                    default_context=contextvars.copy_context(),
                )
                critical_section_stack.push(_utils.prepend_argument(client, self.__clear_queue_on_error))
                del critical_section_stack
                #####################################################################################################

                request_handler_generator = datagram_received_cb(client.ctx)

                del datagram_received_cb

                try:
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    return

                protocol = self.__protocol
                parse_datagram = self.__parse_datagram
                action: _asyncgen.AsyncGenAction[None, _T_Request]

                action = parse_datagram(datagram, protocol)
                del datagram
                try:
                    await action.asend(request_handler_generator)
                except StopAsyncIteration:
                    return
                finally:
                    del action

                while True:
                    try:
                        datagram = await client.data.pop_datagram()
                    except BaseException as exc:
                        action = _asyncgen.ThrowAction(exc)
                    else:
                        action = parse_datagram(datagram, protocol)
                        del datagram
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        break
                    finally:
                        del action

    def __enqueue_task_at_end(
        self,
        datagram_received_cb: Callable[[DatagramClientContext[_T_Response, _T_Address]], AsyncGenerator[None, _T_Request]],
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
        )

    @staticmethod
    def __clear_queue_on_error(
        client: _ClientToken[_T_Response, _T_Address],
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
        /,
    ) -> None:
        if exc_type is not None:
            client.data.clear_datagram_queue()

    @staticmethod
    def __parse_datagram(
        datagram: bytes,
        protocol: protocol_module.DatagramProtocol[_T_Response, _T_Request],
    ) -> _asyncgen.AsyncGenAction[None, _T_Request]:
        try:
            try:
                request = protocol.build_packet_from_datagram(datagram)
            except DatagramProtocolParseError:
                raise
            except Exception as exc:
                raise RuntimeError("protocol.build_packet_from_datagram() crashed") from exc
        except BaseException as exc:
            return _asyncgen.ThrowAction(exc)
        else:
            return _asyncgen.SendAction(request)
        finally:
            del datagram

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@enum.unique
class _ClientState(enum.Enum):
    TASK_PENDING = enum.auto()
    TASK_RUNNING = enum.auto()


class _ClientManager(Generic[_T_Response, _T_Address]):
    __slots__ = (
        "__server",
        "__backend",
        "__client_ctx",
        "__client_data",
        "__weakref__",
    )

    def __init__(self, server: AsyncDatagramServer[Any, _T_Response, _T_Address], backend: AsyncBackend) -> None:
        super().__init__()

        self.__server: AsyncDatagramServer[Any, _T_Response, _T_Address] = server
        self.__backend: AsyncBackend = backend
        self.__client_ctx: weakref.WeakValueDictionary[_T_Address, DatagramClientContext[_T_Response, _T_Address]]
        self.__client_ctx = weakref.WeakValueDictionary()

        self.__client_data: weakref.WeakKeyDictionary[DatagramClientContext[_T_Response, _T_Address], _ClientData]
        self.__client_data = weakref.WeakKeyDictionary()

    def client_context(self, address: _T_Address) -> DatagramClientContext[_T_Response, _T_Address]:
        try:
            return self.__client_ctx[address]
        except KeyError:
            self.__client_ctx[address] = client = DatagramClientContext(address=address, server=self.__server)
            return client

    def client_data(self, client: DatagramClientContext[_T_Response, _T_Address]) -> _ClientData:
        try:
            return self.__client_data[client]
        except KeyError:
            self.__client_data[client] = client_data = _ClientData(self.__backend)
            return client_data

    @staticmethod
    def handle_inconsistent_state_error() -> NoReturn:
        msg = "The server has created too many tasks and ends up in an inconsistent state."
        note = "Please fill an issue (https://github.com/francis-clairicia/EasyNetwork/issues)"
        raise _utils.exception_with_notes(RuntimeError(msg), note)


class _ClientToken(NamedTuple, Generic[_T_Response, _T_Address]):
    ctx: DatagramClientContext[_T_Response, _T_Address]
    data: _ClientData


class _ClientData:
    __slots__ = (
        "__task_lock",
        "__state",
        "_queue_condition",
        "_datagram_queue",
        "__weakref__",
    )

    def __init__(self, backend: AsyncBackend) -> None:
        self.__task_lock: ILock = backend.create_lock()
        self.__state: _ClientState | None = None
        self._queue_condition: ICondition = backend.create_condition_var()
        self._datagram_queue: deque[bytes] | None = None

    @property
    def task_lock(self) -> ILock:
        return self.__task_lock

    @property
    def state(self) -> _ClientState | None:
        return self.__state

    def clear_datagram_queue(self) -> None:
        self._datagram_queue = None

    async def push_datagram(self, datagram: bytes) -> None:
        self.__ensure_queue().append(datagram)
        async with self._queue_condition:
            self._queue_condition.notify()

    def pop_datagram_no_wait(self) -> bytes:
        if (queue := self._datagram_queue) is None:
            raise IndexError("pop from an empty deque")
        return queue.popleft()

    async def pop_datagram(self) -> bytes:
        async with self._queue_condition:
            queue = self.__ensure_queue()
            while not queue:
                await self._queue_condition.wait()
            return queue.popleft()

    def mark_pending(self) -> None:
        self.__set_state(_ClientState.TASK_PENDING)

    def mark_done(self) -> None:
        self.__set_state(None)

    def mark_running(self) -> None:
        self.__set_state(_ClientState.TASK_RUNNING)

    def __set_state(self, state: _ClientState | None) -> None:
        old_state: _ClientState | None = self.__state
        match state:
            case _ClientState.TASK_PENDING if old_state is None:
                pass
            case _ClientState.TASK_RUNNING if old_state is _ClientState.TASK_PENDING:
                pass
            case None if old_state is _ClientState.TASK_RUNNING:
                pass
            case _:
                _ClientManager.handle_inconsistent_state_error()

        self.__state = state

    def __ensure_queue(self) -> deque[bytes]:
        if (queue := self._datagram_queue) is None:
            self._datagram_queue = queue = deque()
        return queue
