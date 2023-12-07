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
from collections import Counter, defaultdict, deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Hashable, Iterator, Mapping
from types import TracebackType
from typing import Any, Generic, NoReturn, Self, TypeVar, assert_never

from .... import protocol as protocol_module
from ...._typevars import _RequestT, _ResponseT
from ....exceptions import DatagramProtocolParseError
from ... import _asyncgen, _utils, typed_attr
from ..backend.abc import AsyncBackend, ICondition, ILock, TaskGroup
from ..transports import abc as transports

_T_Address = TypeVar("_T_Address", bound=Hashable)
_KT = TypeVar("_KT")
_VT = TypeVar("_VT")


class AsyncDatagramServer(typed_attr.TypedAttributeProvider, Generic[_RequestT, _ResponseT, _T_Address]):
    __slots__ = (
        "__listener",
        "__protocol",
        "__backend",
        "__client_manager",
        "__sendto_lock",
        "__serve_guard",
        "__weakref__",
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
        self.__sendto_lock: ILock = self.__backend.create_lock()
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

    async def send_packet_to(self, packet: _ResponseT, address: _T_Address) -> None:
        """
        Sends `packet` to the remote endpoint `address`.

        Warning:
            In the case of a cancellation, it is impossible to know if all the packet data has been sent.

        Parameters:
            packet: the Python object to send.
            address: the remote endpoint address.
        """
        with self.__client_manager.send_guard(address):
            async with self.__sendto_lock:
                listener = self.__listener
                protocol = self.__protocol

                try:
                    datagram: bytes = protocol.make_datagram(packet)
                except Exception as exc:
                    raise RuntimeError("protocol.make_datagram() crashed") from exc
                finally:
                    del packet
                try:
                    await listener.send_to(datagram, address)
                finally:
                    del datagram

    async def serve(
        self,
        datagram_received_cb: Callable[[_T_Address, Self], AsyncGenerator[None, _RequestT]],
        task_group: TaskGroup,
    ) -> NoReturn:
        with self.__serve_guard:
            client_coroutine = self.__client_coroutine
            client_manager = self.__client_manager
            backend = self.__backend
            listener = self.__listener

            async def handler(datagram: bytes, address: _T_Address, /) -> None:
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
                        # Start a new task
                        await client_coroutine(datagram_received_cb, address, task_group)
                    case _ClientState.TASK_WAITING:
                        # Wake up the idle task
                        async with client_manager.lock(address) as condition:
                            condition.notify()
                    case _ClientState.TASK_RUNNING:
                        # Do nothing
                        pass
                    case _:  # pragma: no cover
                        assert_never(client_state)

            while True:
                datagram, address = await listener.recv_from()
                task_group.start_soon(handler, datagram, address)
                del datagram, address
                await backend.cancel_shielded_coro_yield()

    def get_backend(self) -> AsyncBackend:
        """
        Return the underlying backend interface.
        """
        return self.__backend

    async def __client_coroutine(
        self,
        datagram_received_cb: Callable[[_T_Address, Self], AsyncGenerator[None, _RequestT]],
        address: _T_Address,
        task_group: TaskGroup,
    ) -> None:
        client_manager = self.__client_manager

        async with contextlib.AsyncExitStack() as client_exit_stack:
            condition = await client_exit_stack.enter_async_context(client_manager.lock(address))

            datagram_queue: deque[bytes] = client_exit_stack.enter_context(client_manager.datagram_queue(address))
            self.__check_datagram_queue_not_empty(datagram_queue)

            # This block must not have any asynchronous function calls or add any asynchronous callbacks/contexts to the exit stack.
            client_exit_stack.enter_context(client_manager.set_client_state(address, _ClientState.TASK_RUNNING))
            client_exit_stack.callback(
                self.__enqueue_task_at_end,
                datagram_received_cb=datagram_received_cb,
                address=address,
                task_group=task_group,
                datagram_queue=datagram_queue,
                default_context=contextvars.copy_context(),
            )
            client_exit_stack.push(_utils.prepend_argument(datagram_queue)(self.__clear_queue_on_error))
            ########################################################################################################################

            request_handler_generator = datagram_received_cb(address, self)

            del client_exit_stack, datagram_received_cb

            async with contextlib.aclosing(request_handler_generator):
                try:
                    await anext(request_handler_generator)
                except StopAsyncIteration:
                    del datagram_queue[0]
                    return

                protocol = self.__protocol
                action: _asyncgen.AsyncGenAction[None, _RequestT]
                while True:
                    try:
                        if not datagram_queue:
                            with client_manager.set_client_state(address, _ClientState.TASK_WAITING):
                                await condition.wait()
                            self.__check_datagram_queue_not_empty(datagram_queue)
                        datagram = datagram_queue.popleft()
                        try:
                            request = protocol.build_packet_from_datagram(datagram)
                        except DatagramProtocolParseError:
                            raise
                        except Exception as exc:
                            raise RuntimeError("protocol.build_packet_from_datagram() crashed") from exc
                        else:
                            action = _asyncgen.SendAction(request)
                            del request
                        finally:
                            del datagram
                    except BaseException as exc:
                        action = _asyncgen.ThrowAction(exc)
                    try:
                        await action.asend(request_handler_generator)
                    except StopAsyncIteration:
                        break
                    finally:
                        del action

    def __enqueue_task_at_end(
        self,
        datagram_received_cb: Callable[[_T_Address, Self], AsyncGenerator[None, _RequestT]],
        address: _T_Address,
        task_group: TaskGroup,
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

    def __clear_queue_on_error(
        self,
        datagram_queue: deque[bytes],
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
        /,
    ) -> None:
        if exc_type is not None:
            datagram_queue.clear()

    @staticmethod
    def __check_datagram_queue_not_empty(datagram_queue: deque[bytes]) -> None:
        if len(datagram_queue) == 0:
            _ClientManager.handle_inconsistent_state_error()  # pragma: no cover

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
        "__send_guard",
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
        self.__send_guard: _TemporaryValue[_T_Address, _utils.ResourceGuard] = _TemporaryValue(
            lambda: _utils.ResourceGuard("another task is currently sending data for this address")
        )

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
            assert self.__client_state[address] is state  # nosec assert_used
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

    @contextlib.contextmanager
    def send_guard(self, address: _T_Address) -> Iterator[None]:
        with self.__send_guard.get(address) as send_guard:
            with send_guard:
                yield

    @staticmethod
    def handle_inconsistent_state_error() -> NoReturn:
        msg = "The server has created too many tasks and ends up in an inconsistent state."
        note = "Please fill an issue (https://github.com/francis-clairicia/EasyNetwork/issues)"
        raise _utils.exception_with_notes(RuntimeError(msg), note)


class _TemporaryValue(Generic[_KT, _VT]):
    __slots__ = ("__values", "__counter", "__must_delete_value")

    def __init__(self, value_factory: Callable[[], _VT], must_delete_value: Callable[[_VT], bool] | None = None) -> None:
        super().__init__()

        if must_delete_value is None:
            must_delete_value = lambda _: True

        self.__values: defaultdict[_KT, _VT] = defaultdict(value_factory)
        self.__counter: Counter[_KT] = Counter()
        self.__must_delete_value: Callable[[_VT], bool] = must_delete_value

    def __contains__(self, obj: _KT, /) -> bool:  # pragma: no cover  # This method exists for testing purposes
        return obj in self.__values

    @contextlib.contextmanager
    def get(self, key: _KT) -> Iterator[_VT]:
        value: _VT = self.__values[key]
        self.__counter[key] += 1
        try:
            yield value
        finally:
            self.__counter[key] -= 1
            assert self.__counter[key] >= 0, f"{self.__counter[key]=}"  # nosec assert_used
            if self.__counter[key] == 0 and self.__must_delete_value(value):
                del self.__counter[key], self.__values[key]
            del key, value
