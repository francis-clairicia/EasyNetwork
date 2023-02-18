# -*- coding: Utf-8 -*-

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from socket import AF_INET, AF_INET6, SOCK_DGRAM, SOCK_STREAM, socket as Socket
from typing import Any, Callable, Iterator

import pytest

_FAMILY_TO_LOCALHOST: dict[int, str] = {
    AF_INET: "127.0.0.1",
    AF_INET6: "::1",
}

_SUPPORTED_FAMILIES = tuple(_FAMILY_TO_LOCALHOST)


@pytest.fixture(params=_SUPPORTED_FAMILIES)
def socket_family(request: Any) -> int:
    return request.param


@pytest.fixture()
def localhost(socket_family: int) -> str:
    return _FAMILY_TO_LOCALHOST[socket_family]


@pytest.fixture
def socket_factory(socket_family: int) -> Iterator[Callable[[int], Socket]]:
    socket_stack = ExitStack()

    def socket_factory(type: int) -> Socket:
        return socket_stack.enter_context(Socket(socket_family, type))

    with socket_stack:
        yield socket_factory


@pytest.fixture
def tcp_socket_factory(socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(socket_factory, SOCK_STREAM)


@pytest.fixture
def udp_socket_factory(socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(socket_factory, SOCK_DGRAM)


@pytest.fixture(scope="package")
def schedule_call_in_thread() -> Iterator[Callable[[float, Callable[[], Any]], None]]:
    with ThreadPoolExecutor(thread_name_prefix="pytest-easynetwork") as executor:

        def task(time_to_sleep: float, callback: Callable[[], Any]) -> None:
            if time_to_sleep > 0:
                time.sleep(time_to_sleep)
            callback()

        def schedule_call(time_to_sleep: float, callback: Callable[[], Any]) -> None:
            executor.submit(task, time_to_sleep, callback)

        yield schedule_call
