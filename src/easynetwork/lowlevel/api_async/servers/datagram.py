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

__all__ = ["AsyncDatagramServer"]

import contextlib
import contextvars
import enum
import operator
from collections import Counter, deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Hashable, Iterator, Mapping
from typing import Any, Generic, NoReturn, TypeVar, assert_never

from .... import protocol as protocol_module
from ...._typevars import _RequestT, _ResponseT
from ... import _utils, typed_attr
from ..backend.abc import AsyncBackend, ICondition, TaskGroup
from ..transports import abc as transports
from ._tools.actions import ActionIterator as _ActionIterator

_T_Address = TypeVar("_T_Address", bound=Hashable)
_KT = TypeVar("_KT")
_VT = TypeVar("_VT")


class AsyncDatagramServer(typed_attr.TypedAttributeProvider, Generic[_RequestT, _ResponseT, _T_Address]):
    __slots__ = (
        "__listener",
        "__protocol",
        "__backend",
        "__client_manager",
    )

    def __init__(
        self,
        listener: transports.AsyncDatagramListener[_T_Address],
        protocol: protocol_module.DatagramProtocol[_ResponseT, _RequestT],
        *,
        backend: str | AsyncBackend | None = None,
        backend_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(listener, transports.AsyncDatagramListener):
            raise TypeError(f"Expected an AsyncDatagramListener object, got {listener!r}")
        if not isinstance(protocol, protocol_module.DatagramProtocol):
            raise TypeError(f"Expected a DatagramProtocol object, got {protocol!r}")

        from ..backend.factory import AsyncBackendFactory

        backend = AsyncBackendFactory.ensure(backend, backend_kwargs)

        self.__listener: transports.AsyncDatagramListener[_T_Address] = listener
        self.__protocol: protocol_module.DatagramProtocol[_ResponseT, _RequestT] = protocol
        self.__backend: AsyncBackend = backend
        self.__client_manager: _ClientManager[_T_Address] = _ClientManager(self.__backend)

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

    async def send_packet_to(self, packet: _ResponseT, address: _T_Address) -> None:
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

        await listener.send_to(protocol.make_datagram(packet), address)

    async def serve(
        self,
        datagram_received_cb: Callable[[_T_Address], AsyncGenerator[None, _RequestT]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        client_coroutine = self.__client_coroutine
        client_manager = self.__client_manager

        async with self.__ensure_task_group(task_group) as task_group:

            @_utils.prepend_argument(task_group)
            async def handler(task_group: TaskGroup, datagram: bytes, address: _T_Address, /) -> None:
                with client_manager.datagram_queue(address) as datagram_queue:
                    datagram_queue.append(datagram)

                    # client_coroutine() is running (or will be run) if datagram_queue was not empty
                    # Therefore, start a new task only if there was no previous datagrams
                    if len(datagram_queue) > 1:
                        return

                del datagram_queue, datagram

                client_state = client_manager.client_state(address)
                match client_state:
                    case None:
                        # Spawn a new task
                        task_group.start_soon(client_coroutine, datagram_received_cb, address, task_group)
                    case _ClientState.TASK_WAITING:
                        # Wake up the idle task
                        async with client_manager.lock(address) as condition:
                            condition.notify()
                    case _ClientState.TASK_RUNNING:
                        # Do nothing
                        pass
                    case _:  # pragma: no cover
                        assert_never(client_state)

            await self.__listener.serve(handler)

    def __ensure_task_group(self, task_group: TaskGroup | None) -> contextlib.AbstractAsyncContextManager[TaskGroup]:
        if task_group is None:
            return self.__backend.create_task_group()
        return contextlib.nullcontext(task_group)

    async def __client_coroutine(
        self,
        datagram_received_cb: Callable[[_T_Address], AsyncGenerator[None, _RequestT]],
        address: _T_Address,
        task_group: TaskGroup,
    ) -> None:
        backend = self.__backend
        client_manager = self.__client_manager

        async with contextlib.AsyncExitStack() as client_exit_stack:
            condition = await client_exit_stack.enter_async_context(client_manager.lock(address))

            def enqueue_task_at_end(
                datagram_received_cb: Callable[[_T_Address], AsyncGenerator[None, _RequestT]],
                datagram_queue: deque[bytes],
                default_context: contextvars.Context,
            ) -> None:
                if datagram_queue:
                    task_group.start_soon(
                        self.__client_coroutine,
                        datagram_received_cb,
                        address,
                        task_group,
                        context=default_context,
                    )

            datagram_queue: deque[bytes] = client_exit_stack.enter_context(client_manager.datagram_queue(address))
            self.__check_datagram_queue_not_empty(datagram_queue)

            # This block must not have any asynchronous function calls or add any asynchronous callbacks/contexts to the exit stack.
            client_exit_stack.enter_context(client_manager.set_client_state(address, _ClientState.TASK_RUNNING))
            client_exit_stack.callback(enqueue_task_at_end, datagram_received_cb, datagram_queue, contextvars.copy_context())
            ########################################################################################################################

            request_handler_generator = datagram_received_cb(address)

            del client_exit_stack, datagram_received_cb, enqueue_task_at_end

            async with contextlib.aclosing(request_handler_generator):
                try:
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    del datagram_queue[0]
                    return

                request_factory = _utils.make_callback(
                    self.__request_factory,
                    datagram_queue,
                    address,
                    client_manager,
                    condition,
                    self.__protocol,
                )
                async for action in _ActionIterator(request_factory):
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        return
                    finally:
                        del action
                    await backend.cancel_shielded_coro_yield()

    @classmethod
    async def __request_factory(
        cls,
        datagram_queue: deque[bytes],
        address: _T_Address,
        client_manager: _ClientManager[_T_Address],
        condition: ICondition,
        protocol: protocol_module.DatagramProtocol[_ResponseT, _RequestT],
        /,
    ) -> _RequestT:
        if not datagram_queue:
            with client_manager.set_client_state(address, _ClientState.TASK_WAITING):
                await condition.wait()
            cls.__check_datagram_queue_not_empty(datagram_queue)
        return protocol.build_packet_from_datagram(datagram_queue.popleft())

    @staticmethod
    def __check_datagram_queue_not_empty(datagram_queue: deque[bytes]) -> None:
        if len(datagram_queue) == 0:
            _ClientManager.handle_inconsistent_state_error()  # pragma: no cover

    def get_backend(self) -> AsyncBackend:
        """
        Return the underlying backend interface.
        """
        return self.__backend

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__listener.extra_attributes


@enum.unique
class _ClientState(enum.Enum):
    TASK_RUNNING = enum.auto()
    TASK_WAITING = enum.auto()


class _ClientManager(Generic[_T_Address]):
    __slots__ = (
        "__client_lock",
        "__client_queue",
        "__client_state",
        "__weakref__",
    )

    def __init__(self, backend: AsyncBackend) -> None:
        super().__init__()

        self.__client_lock: _TemporaryValue[_T_Address, ICondition] = _TemporaryValue(backend.create_condition_var)
        self.__client_queue: _TemporaryValue[_T_Address, deque[bytes]] = _TemporaryValue(
            deque,
            must_delete_value=operator.not_,  # delete if and only if the deque is empty
        )
        self.__client_state: dict[_T_Address, _ClientState] = {}

    def client_state(self, address: _T_Address) -> _ClientState | None:
        return self.__client_state.get(address)

    @contextlib.contextmanager
    def set_client_state(self, address: _T_Address, state: _ClientState) -> Iterator[None]:
        old_state: _ClientState | None = self.__client_state.get(address)
        match state:
            case _ClientState.TASK_RUNNING if old_state is None:
                pass
            case _ClientState.TASK_WAITING if old_state is _ClientState.TASK_RUNNING:
                pass
            case _:
                self.handle_inconsistent_state_error()

        self.__client_state[address] = state
        try:
            yield
        finally:
            if old_state is None:
                del self.__client_state[address]
            else:
                self.__client_state[address] = old_state

    @contextlib.asynccontextmanager
    async def lock(self, address: _T_Address) -> AsyncIterator[ICondition]:
        with self.__client_lock.get(address) as condition:
            async with condition:
                yield condition

    @contextlib.contextmanager
    def datagram_queue(self, address: _T_Address) -> Iterator[deque[bytes]]:
        with self.__client_queue.get(address) as datagram_queue:
            yield datagram_queue

    @staticmethod
    def handle_inconsistent_state_error() -> NoReturn:
        msg = "The server has created too many tasks and ends up in an inconsistent state."
        note = "Please fill an issue (https://github.com/francis-clairicia/EasyNetwork/issues)"
        raise _utils.exception_with_notes(RuntimeError(msg), note)


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

    @contextlib.contextmanager
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
