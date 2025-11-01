# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine, Iterator
from socket import socket as Socket
from typing import TYPE_CHECKING, Any, TypedDict, TypeVar

import pytest
import pytest_asyncio

from ..._utils import restore_mock_side_effect

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

_T = TypeVar("_T")


class MockedEventLoopSockMethods(TypedDict):
    sock_accept: AsyncMock
    sock_recv: AsyncMock
    sock_recv_into: AsyncMock
    sock_recvfrom: AsyncMock
    sock_sendall: AsyncMock
    sock_sendto: AsyncMock


@pytest.mark.asyncio
class BaseTestAsyncSocket:
    @pytest_asyncio.fixture(autouse=True)
    @classmethod
    async def mock_event_loop_sock_method(cls, mocker: MockerFixture) -> MockedEventLoopSockMethods:
        event_loop = asyncio.get_running_loop()
        return {
            "sock_accept": cls.__patch_async_sock_method(event_loop, "sock_accept", "accept", mocker),
            "sock_recv": cls.__patch_async_sock_method(event_loop, "sock_recv", "recv", mocker),
            "sock_recv_into": cls.__patch_async_sock_method(event_loop, "sock_recv_into", "recv_into", mocker),
            "sock_recvfrom": cls.__patch_async_sock_method(event_loop, "sock_recvfrom", "recvfrom", mocker),
            "sock_sendall": cls.__patch_async_sock_method(event_loop, "sock_sendall", "sendall", mocker),
            "sock_sendto": cls.__patch_async_sock_method(event_loop, "sock_sendto", "sendto", mocker),
        }

    @staticmethod
    def __patch_async_sock_method(
        event_loop: asyncio.AbstractEventLoop,
        event_loop_method: str,
        sock_method: str,
        mocker: MockerFixture,
    ) -> MagicMock:
        async def sock_method_patch(sock: Socket, *args: Any, **kwargs: Any) -> Any:
            method: Callable[..., Any] = getattr(sock, sock_method)
            while True:
                try:
                    return method(*args, **kwargs)
                except BlockingIOError:
                    await asyncio.sleep(0)

        return mocker.patch.object(event_loop, event_loop_method, side_effect=sock_method_patch)

    @pytest_asyncio.fixture(autouse=True)
    @classmethod
    async def event_loop_mock_event_handlers(cls, mocker: MockerFixture) -> dict[str, MagicMock]:
        event_loop = asyncio.get_running_loop()
        to_patch = [
            ("add_reader", "remove_reader"),
            ("add_writer", "remove_writer"),
        ]
        patched: dict[str, MagicMock] = {}
        for add_event_func_name, remove_event_func_name in to_patch:
            patched.update(cls.__patch_event_handler_method(event_loop, add_event_func_name, remove_event_func_name, mocker))
        return patched

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_event_loop_add_reader(event_loop_mock_event_handlers: dict[str, MagicMock]) -> MagicMock:
        return event_loop_mock_event_handlers["add_reader"]

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_event_loop_remove_reader(event_loop_mock_event_handlers: dict[str, MagicMock]) -> MagicMock:
        return event_loop_mock_event_handlers["remove_reader"]

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_event_loop_add_writer(event_loop_mock_event_handlers: dict[str, MagicMock]) -> MagicMock:
        return event_loop_mock_event_handlers["add_writer"]

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_event_loop_remove_writer(event_loop_mock_event_handlers: dict[str, MagicMock]) -> MagicMock:
        return event_loop_mock_event_handlers["remove_writer"]

    @staticmethod
    def __patch_event_handler_method(
        event_loop: asyncio.AbstractEventLoop,
        add_event_func_name: str,
        remove_event_func_name: str,
        mocker: MockerFixture,
    ) -> dict[str, MagicMock]:
        registered_fds: dict[object, asyncio.Handle] = {}

        def ready_for_event(fileobj: object, cb: Callable[..., Any], args: tuple[Any, ...]) -> None:
            former_cb_handle = registered_fds.pop(fileobj, None)
            if former_cb_handle is None or not former_cb_handle.cancelled():
                registered_fds[fileobj] = event_loop.call_soon(ready_for_event, fileobj, cb, args)
            cb(*args)

        def add_event_side_effect(fileobj: object, cb: Callable[..., Any], *args: Any) -> None:
            try:
                registered_fds[fileobj].cancel()
            except KeyError:
                pass

            registered_fds[fileobj] = event_loop.call_soon(ready_for_event, fileobj, cb, args)

        def remove_event_side_effect(fileobj: object) -> bool:
            try:
                former_cb_handle = registered_fds.pop(fileobj)
            except KeyError:
                return False
            else:
                former_cb_handle.cancel()
                return True

        return {
            add_event_func_name: mocker.patch.object(event_loop, add_event_func_name, side_effect=add_event_side_effect),
            remove_event_func_name: mocker.patch.object(event_loop, remove_event_func_name, side_effect=remove_event_side_effect),
        }

    @staticmethod
    @contextlib.contextmanager
    def _set_sock_method_in_blocking_state(
        mock_socket_method: MagicMock,
        exception: type[Exception] | Exception = BlockingIOError,
    ) -> Iterator[None]:
        with restore_mock_side_effect(mock_socket_method):
            mock_socket_method.side_effect = exception
            yield

    @staticmethod
    async def _busy_socket_task(
        coroutine: Coroutine[Any, Any, _T],
        mock_socket_method: MagicMock,
    ) -> asyncio.Task[_T]:
        mock_socket_method.reset_mock()
        task = asyncio.create_task(coroutine)
        await asyncio.sleep(0)
        async with asyncio.timeout(5):
            while not task.done() and len(mock_socket_method.call_args_list) == 0:
                await asyncio.sleep(0)
        mock_socket_method.reset_mock()
        return task
