# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine, Iterator
from socket import socket as Socket
from typing import TYPE_CHECKING, Any, TypeVar

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

_T = TypeVar("_T")


@pytest.mark.asyncio
class BaseTestAsyncSocket:
    @pytest.fixture(autouse=True)
    @classmethod
    def event_loop_sock_method_replace(cls, event_loop: asyncio.AbstractEventLoop, monkeypatch: pytest.MonkeyPatch) -> None:
        to_patch = [
            ("sock_accept", "accept"),
            ("sock_recv", "recv"),
            ("sock_recv_into", "recv_into"),
            ("sock_recvfrom", "recvfrom"),
            ("sock_sendall", "send"),
            ("sock_sendto", "sendto"),
        ]

        for event_loop_method, sock_method in to_patch:
            cls.__patch_async_sock_method(event_loop, event_loop_method, sock_method, monkeypatch)

    @staticmethod
    def __patch_async_sock_method(
        event_loop: asyncio.AbstractEventLoop,
        event_loop_method: str,
        sock_method: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def sock_method_patch(sock: Socket, *args: Any, **kwargs: Any) -> Any:
            method: Callable[..., Any] = getattr(sock, sock_method)
            while True:
                try:
                    return method(*args, **kwargs)
                except BlockingIOError:
                    await asyncio.sleep(0)

        monkeypatch.setattr(event_loop, event_loop_method, sock_method_patch)

    @pytest.fixture(autouse=True)
    @classmethod
    def event_loop_mock_event_handlers(cls, event_loop: asyncio.AbstractEventLoop, mocker: MockerFixture) -> None:
        to_patch = [
            ("add_reader", "remove_reader"),
            ("add_writer", "remove_writer"),
        ]

        for add_event_func_name, remove_event_func_name in to_patch:
            cls.__patch_event_handler_method(event_loop, add_event_func_name, remove_event_func_name, mocker)

    @staticmethod
    def __patch_event_handler_method(
        event_loop: asyncio.AbstractEventLoop,
        add_event_func_name: str,
        remove_event_func_name: str,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(
            event_loop,
            add_event_func_name,
            side_effect=lambda sock, cb, *args: event_loop.call_soon(cb, *args),
        )
        mocker.patch.object(event_loop, remove_event_func_name, return_value=False)

    @staticmethod
    @contextlib.contextmanager
    def _set_sock_method_in_blocking_state(
        mock_socket_method: MagicMock,
        exception: type[Exception] | Exception = BlockingIOError,
    ) -> Iterator[None]:
        default_side_effect = mock_socket_method.side_effect
        default_return_value = mock_socket_method.return_value
        try:
            mock_socket_method.side_effect = exception
            yield
        finally:
            mock_socket_method.configure_mock(side_effect=default_side_effect, return_value=default_return_value)

    @staticmethod
    async def _busy_socket_task(
        coroutine: Coroutine[Any, Any, _T],
        mock_socket_method: MagicMock,
    ) -> asyncio.Task[_T]:
        mock_socket_method.reset_mock()
        accept_task = asyncio.create_task(coroutine)
        await asyncio.sleep(0)
        async with asyncio.timeout(5):
            while len(mock_socket_method.call_args_list) == 0:
                await asyncio.sleep(0)
        mock_socket_method.reset_mock()
        return accept_task
