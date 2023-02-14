# -*- coding: Utf-8 -*-

from __future__ import annotations

from collections import deque
from contextlib import ExitStack
from functools import partial, wraps
from selectors import EVENT_READ, DefaultSelector
from socket import AF_INET, SOCK_DGRAM, SOCK_STREAM, socket as Socket
from threading import Event, Thread
from typing import Any, Callable, Iterator, ParamSpec

from easynetwork.tools.socket import MAX_DATAGRAM_BUFSIZE, MAX_STREAM_BUFSIZE

import pytest

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


@thread_factory(daemon=True)
def _launch_tcp_server(server_socket: Socket, shutdown_requested: Event) -> None:
    with ExitStack() as client_stack, DefaultSelector() as selector:
        selector.register(server_socket, EVENT_READ)
        server_socket.settimeout(0)
        clients: deque[Socket] = deque()
        try:
            while not shutdown_requested.is_set():
                for key, _ in selector.select(0.01):
                    sock: Socket = key.fileobj  # type: ignore[assignment]
                    if sock is server_socket:
                        sock = server_socket.accept()[0]
                        clients.append(sock)
                        selector.register(sock, EVENT_READ)
                        continue
                    try:
                        if not (data := sock.recv(MAX_STREAM_BUFSIZE)):
                            raise EOFError
                        sock.sendall(data)
                    except (EOFError, OSError):
                        selector.unregister(sock)
                        sock.close()
                        clients.remove(sock)
        finally:
            deque(client_stack.enter_context(s) for s in clients)


@pytest.fixture(scope="package")
def host_ip() -> str:
    import socket

    return socket.gethostbyname(socket.gethostname())


@pytest.fixture(scope="package")
def mirror_tcp_server(host_ip: str) -> Iterator[tuple[str, int]]:
    shutdown_requested = Event()

    with Socket(AF_INET, SOCK_STREAM) as s:
        s.bind((host_ip, 0))
        s.listen()
        server_thread = _launch_tcp_server(s, shutdown_requested)
        yield s.getsockname()
        shutdown_requested.set()
        server_thread.join()


@thread_factory(daemon=True)
def _launch_udp_server(socket: Socket, shutdown_requested: Event) -> None:
    with DefaultSelector() as selector:
        selector.register(socket, EVENT_READ)
        while not shutdown_requested.is_set():
            if selector.select(0.01):
                data, addr = socket.recvfrom(MAX_DATAGRAM_BUFSIZE)
                socket.sendto(data, addr)


@pytest.fixture(scope="package")
def mirror_udp_server(host_ip: str) -> Iterator[tuple[str, int]]:
    shutdown_requested = Event()

    with Socket(AF_INET, SOCK_DGRAM) as s:
        s.bind((host_ip, 0))
        server_thread = _launch_udp_server(s, shutdown_requested)
        yield s.getsockname()
        shutdown_requested.set()
        server_thread.join()


@pytest.fixture
def socket_factory() -> Iterator[Callable[[int], Socket]]:
    socket_stack = ExitStack()

    def socket_factory(type: int) -> Socket:
        return socket_stack.enter_context(Socket(AF_INET, type))

    with socket_stack:
        yield socket_factory


@pytest.fixture
def tcp_socket_factory(socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(socket_factory, SOCK_STREAM)


@pytest.fixture
def udp_socket_factory(socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(socket_factory, SOCK_DGRAM)
