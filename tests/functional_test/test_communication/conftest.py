# -*- coding: Utf-8 -*-

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from socket import AF_INET, AF_INET6, SOCK_DGRAM, SOCK_STREAM, has_ipv6 as HAS_IPV6, socket as Socket
from typing import Any, Callable, Iterator

from easynetwork.protocol import DatagramProtocol, StreamProtocol

import pytest

from .serializer import StringSerializer

_FAMILY_TO_LOCALHOST: dict[int, str] = {
    AF_INET: "127.0.0.1",
    AF_INET6: "::1",
}

_SUPPORTED_FAMILIES = tuple(_FAMILY_TO_LOCALHOST)


@pytest.fixture(params=_SUPPORTED_FAMILIES)
def socket_family(request: Any) -> int:
    return request.param


@pytest.fixture
def localhost(socket_family: int) -> str:
    return _FAMILY_TO_LOCALHOST[socket_family]


@pytest.fixture
def socket_factory(socket_family: int) -> Iterator[Callable[[int], Socket]]:
    if not HAS_IPV6:
        pytest.skip("socket.has_ipv6 is False")

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


@pytest.fixture
def schedule_call_in_thread(request: pytest.FixtureRequest) -> Iterator[Callable[[float, Callable[[], Any]], None]]:
    with ThreadPoolExecutor(thread_name_prefix=f"pytest-easynetwork_{request.node.name}") as executor:
        monotonic = time.monotonic

        def task(time_to_sleep: float, callback: Callable[[], Any], submit_timestamp: float) -> None:
            time_to_sleep -= monotonic() - submit_timestamp
            if time_to_sleep > 0:
                time.sleep(time_to_sleep)
            callback()

        def schedule_call(time_to_sleep: float, callback: Callable[[], Any]) -> None:
            executor.submit(task, time_to_sleep, callback, monotonic())

        yield schedule_call


@pytest.fixture(scope="package")
def stream_protocol() -> StreamProtocol[str, str]:
    return StreamProtocol(StringSerializer())


@pytest.fixture(scope="package")
def datagram_protocol() -> DatagramProtocol[str, str]:
    return DatagramProtocol(StringSerializer())
