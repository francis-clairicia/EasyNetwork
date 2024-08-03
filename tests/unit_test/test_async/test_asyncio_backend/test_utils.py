from __future__ import annotations

import asyncio
import asyncio.trsock
from collections.abc import Callable
from socket import SocketType
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._asyncio._asyncio_utils import wait_until_readable, wait_until_writable

import pytest

from ....tools import is_proactor_event_loop

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ["waiter", "event_loop_add_event_func_name", "event_loop_remove_event_func_name"],
    [
        pytest.param(wait_until_readable, "add_reader", "remove_reader", id="read"),
        pytest.param(wait_until_writable, "add_writer", "remove_writer", id="write"),
    ],
)
@pytest.mark.parametrize("future_cancelled", [False, True], ids=lambda p: f"future_cancelled=={p}")
async def test____wait_until___event_wakeup(
    waiter: Callable[[SocketType, asyncio.AbstractEventLoop], asyncio.Future[None]],
    event_loop_add_event_func_name: str,
    event_loop_remove_event_func_name: str,
    future_cancelled: bool,
    mock_socket_factory: Callable[[], MagicMock],
    mocker: MockerFixture,
) -> None:
    # Arrange
    event_loop = asyncio.get_running_loop()
    if is_proactor_event_loop(event_loop):
        pytest.skip(f"event_loop.{event_loop_add_event_func_name}() is not supported on asyncio.ProactorEventLoop")

    event_loop_add_event = mocker.patch.object(
        event_loop,
        event_loop_add_event_func_name,
        side_effect=lambda sock, cb, *args: event_loop.call_soon(cb, *args),
    )
    event_loop_remove_event = mocker.patch.object(event_loop, event_loop_remove_event_func_name)
    mock_socket = mock_socket_factory()

    # Act
    fut = waiter(mock_socket, event_loop)
    if future_cancelled:
        fut.cancel()
        await asyncio.sleep(0)
    else:
        await fut

    # Assert
    event_loop_add_event.assert_called_once_with(mock_socket, mocker.ANY, mocker.ANY)
    event_loop_remove_event.assert_called_once_with(mock_socket)
