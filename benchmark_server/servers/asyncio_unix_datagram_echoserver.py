#!/usr/bin/env python3
# mypy: disable-error-code=unused-awaitable

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import logging
import os
import socket
import stat
import sys
from collections.abc import Iterator
from typing import Any, Final, NoReturn, cast

import asyncio_dgram

LOGGER: Final[logging.Logger] = logging.getLogger("asyncio server")


@contextlib.contextmanager
def _cleanup_socket_at_end(path: str) -> Iterator[None]:
    try:
        yield
    finally:
        try:
            if stat.S_ISSOCK(os.stat(path).st_mode):
                os.remove(path)
        except OSError:
            pass


def _make_unix_datagram_socket(local_path: str) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(local_path)
    sock.setblocking(False)
    return sock


async def echo_server(path: str) -> NoReturn:
    loop = asyncio.get_running_loop()
    sock = _make_unix_datagram_socket(path)
    LOGGER.info(f"Server listening at {sock.getsockname()}")

    async with contextlib.AsyncExitStack() as stack:
        stack.enter_context(_cleanup_socket_at_end(path))
        stack.enter_context(sock)
        task_group = await stack.enter_async_context(asyncio.TaskGroup())

        lock = asyncio.Lock()
        while True:
            datagram, addr = await loop.sock_recvfrom(sock, 65536)
            if addr:
                task_group.create_task(_echo_datagram_client(loop, lock, sock, datagram, addr))
            else:
                LOGGER.warning("A datagram received from an unbound UNIX datagram socket was dropped.")

    raise AssertionError("unreachable")


async def _echo_datagram_client(
    loop: asyncio.AbstractEventLoop,
    lock: asyncio.Lock,
    server: socket.socket,
    datagram: bytes,
    addr: Any,
) -> None:
    async with lock:
        await loop.sock_sendto(server, datagram, addr)


async def echo_server_stream(path: str) -> NoReturn:
    stream = await asyncio_dgram.from_socket(_make_unix_datagram_socket(path))
    assert isinstance(stream, asyncio_dgram.aio.DatagramServer)
    LOGGER.info(f"Server listening at {stream.sockname}")

    async with contextlib.AsyncExitStack() as stack:
        stack.enter_context(_cleanup_socket_at_end(path))
        stack.enter_context(contextlib.closing(stream))
        task_group = await stack.enter_async_context(asyncio.TaskGroup())
        while True:
            datagram, addr = await stream.recv()
            if addr:
                task_group.create_task(_echo_datagram_client_stream(stream, datagram, addr))
            else:
                LOGGER.warning("A datagram received from an unbound UNIX datagram socket was dropped.")

    raise AssertionError("unreachable")


async def _echo_datagram_client_stream(
    server: asyncio_dgram.DatagramServer,
    datagram: bytes,
    addr: Any,
) -> None:
    await server.send(datagram, addr)


class EchoProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.connection_lost_event = asyncio.Event()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport: asyncio.DatagramTransport = cast(asyncio.DatagramTransport, transport)
        self.connection_lost_event.clear()

    def connection_lost(self, exc: Exception | None) -> None:
        self.connection_lost_event.set()
        with contextlib.suppress(AttributeError):
            del self.transport

    def datagram_received(self, data: bytes, addr: Any) -> None:
        if not addr:
            LOGGER.warning("A datagram received from an unbound UNIX datagram socket was dropped.")
            return
        with contextlib.suppress(AttributeError):
            self.transport.sendto(data, addr)


def create_runner(
    *,
    use_uvloop: bool,
) -> asyncio.Runner:
    asyncio_options: dict[str, Any] = {}
    if use_uvloop:
        import uvloop

        asyncio_options["loop_factory"] = uvloop.new_event_loop
        print("using uvloop")
    else:
        print("using asyncio event loop")

    return asyncio.Runner(**asyncio_options)


def main() -> None:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    server_mode_parser_group = parser.add_mutually_exclusive_group()
    server_mode_parser_group.add_argument(
        "--streams",
        default=False,
        action="store_true",
    )
    server_mode_parser_group.add_argument(
        "--proto",
        default=False,
        action="store_true",
    )

    parser.add_argument(
        "-p",
        "--path",
        dest="path",
        default="/tmp/easynetwork.sock",
    )
    parser.add_argument(
        "--uvloop",
        dest="use_uvloop",
        action="store_true",
    )
    parser.add_argument(
        "--disable-gc",
        dest="gc_enabled",
        action="store_false",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[ %(levelname)s ] [ %(name)s ] %(message)s")
    if not args.gc_enabled:
        gc.disable()

    print(f"Python version: {sys.version}")
    print(f"GC enabled: {gc.isenabled()}")

    with create_runner(use_uvloop=args.use_uvloop) as runner:
        path: str = args.path
        if args.streams:
            runner.run(echo_server_stream(path))
        elif args.proto:
            transport, protocol = runner.run(
                runner.get_loop().create_datagram_endpoint(
                    EchoProtocol,
                    sock=_make_unix_datagram_socket(path),
                )
            )
            LOGGER.info(f"Server listening at {transport.get_extra_info('sockname')}")
            with _cleanup_socket_at_end(path):
                runner.run(protocol.connection_lost_event.wait())
        else:
            runner.run(echo_server(path))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
