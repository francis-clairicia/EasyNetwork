# -*- coding: Utf-8 -*-

from __future__ import annotations

import time
from functools import wraps
from selectors import EVENT_READ, DefaultSelector
from socket import AF_INET, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM, socket as Socket
from threading import Event, Thread
from typing import TYPE_CHECKING, Any, Callable, Iterator, ParamSpec

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


_P = ParamSpec("_P")


def thread_factory(
    *,
    daemon: bool | None = None,
    auto_start: bool = True,
    name: str | None = None,
    **thread_cls_kwargs: Any,
) -> Callable[[Callable[_P, Any]], Callable[_P, Thread]]:
    if daemon is not None:
        daemon = bool(daemon)
    auto_start = bool(auto_start)

    def decorator(func: Callable[..., Any], /) -> Callable[..., Thread]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Thread:
            thread = Thread(group=None, target=func, args=args, kwargs=kwargs, name=name, daemon=daemon, **thread_cls_kwargs)
            if auto_start:
                thread.start()
            return thread

        return wrapper

    return decorator


@thread_factory()
def _tcp_client_loop(socket: Socket, shutdown_requested: Event) -> None:
    with socket, DefaultSelector() as selector:
        selector.register(socket, EVENT_READ)
        while not shutdown_requested.is_set():
            if selector.select(0.1):
                if not (data := socket.recv(8192)):
                    break
                socket.sendall(data)


@thread_factory(daemon=True)
def _launch_tcp_server(socket: Socket, shutdown_requested: Event) -> None:
    client_threads: list[Thread] = []
    try:
        with DefaultSelector() as selector:
            selector.register(socket, EVENT_READ)
            while not shutdown_requested.is_set():
                if selector.select(0.1):
                    client_threads.append(_tcp_client_loop(socket.accept()[0], shutdown_requested))
                client_threads = [t for t in client_threads if t.is_alive()]
    except BaseException:
        shutdown_requested.set()
        raise
    finally:
        for t in client_threads:
            t.join()


@pytest.fixture(scope="module")
def tcp_server() -> Iterator[tuple[str, int]]:
    shutdown_requested = Event()

    with Socket(AF_INET, SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        s.listen()
        server_thread = _launch_tcp_server(s, shutdown_requested)
        time.sleep(0.1)
        yield s.getsockname()
        shutdown_requested.set()
        server_thread.join()


@thread_factory(daemon=True)
def _launch_udp_server(socket: Socket, shutdown_requested: Event) -> None:
    with DefaultSelector() as selector:
        selector.register(socket, EVENT_READ)
        while not shutdown_requested.is_set():
            if selector.select(0.1):
                data, addr = socket.recvfrom(64 * 1024)
                socket.sendto(data, addr)


@pytest.fixture(scope="module")
def udp_server() -> Iterator[tuple[str, int]]:
    shutdown_requested = Event()

    with Socket(AF_INET, SOCK_DGRAM) as s:
        s.bind(("localhost", 0))
        server_thread = _launch_udp_server(s, shutdown_requested)
        time.sleep(0.1)
        yield s.getsockname()
        shutdown_requested.set()
        server_thread.join()


@pytest.fixture
def mock_socket_cls(mocker: MockerFixture) -> MagicMock:
    socket = mocker.patch("socket.socket", autospec=True)
    return socket


@pytest.fixture
def mock_tcp_socket(mocker: MockerFixture) -> MagicMock:
    mock_socket = mocker.MagicMock(spec=Socket())
    mock_socket.family = AF_INET
    mock_socket.type = SOCK_STREAM
    mock_socket.proto = IPPROTO_TCP
    return mock_socket


@pytest.fixture
def mock_udp_socket(mocker: MockerFixture) -> MagicMock:
    mock_socket = mocker.MagicMock(spec=Socket())
    mock_socket.family = AF_INET
    mock_socket.type = SOCK_DGRAM
    mock_socket.proto = IPPROTO_UDP
    return mock_socket
