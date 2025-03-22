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


async def echo_server(path: str) -> NoReturn:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    sock.listen(256)
    sock.setblocking(False)
    LOGGER.info(f"Server listening at {sock.getsockname()}")
    with _cleanup_socket_at_end(path), sock:
        while True:
            client, addr = await loop.sock_accept(sock)
            LOGGER.info(f"Connection from {addr!r}")
            loop.create_task(_echo_client(loop, client, addr))


async def _echo_client(loop: asyncio.AbstractEventLoop, client: socket.socket, addr: str) -> None:
    lock = asyncio.Lock()
    with client:
        while True:
            data = await loop.sock_recv(client, 102400)
            if not data:
                break
            async with lock:
                await loop.sock_sendall(client, data)
    LOGGER.info(f"{addr!r}: Connection closed")


async def echo_client_streams(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    addr: str = writer.get_extra_info("peername")
    writer.transport.set_write_buffer_limits(0)
    LOGGER.info(f"Connection from {addr!r}")

    lock = asyncio.Lock()
    with contextlib.closing(writer):
        while True:
            data = await reader.read(102400)
            if not data:
                break
            async with lock:
                writer.write(data)
                await writer.drain()
    LOGGER.info(f"{addr!r}: Connection closed")


async def readline_client_streams(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    addr: str = writer.get_extra_info("peername")
    writer.transport.set_write_buffer_limits(0)
    LOGGER.info(f"Connection from {addr!r}")

    lock = asyncio.Lock()
    with contextlib.closing(writer):
        while True:
            data = await reader.readline()
            if not data:
                break
            async with lock:
                writer.write(data)
                await writer.drain()
    LOGGER.info(f"{addr!r}: Connection closed")


class EchoProtocol(asyncio.Protocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport: asyncio.Transport = cast(asyncio.Transport, transport)
        self.addr: str = transport.get_extra_info("peername")
        LOGGER.info(f"Connection from {self.addr!r}")

    def connection_lost(self, exc: Exception | None) -> None:
        LOGGER.info(f"{self.addr!r}: Connection closed")
        with contextlib.suppress(AttributeError):
            del self.transport

    def data_received(self, data: bytes) -> None:
        with contextlib.suppress(AttributeError):
            self.transport.write(data)


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
        action="store_true",
    )
    server_mode_parser_group.add_argument(
        "--readline",
        action="store_true",
    )
    server_mode_parser_group.add_argument(
        "--proto",
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
        if args.readline:
            server = runner.run(asyncio.start_unix_server(readline_client_streams, path=path))
            LOGGER.info(f"Server listening at {', '.join(str(s.getsockname()) for s in server.sockets)}")
            with _cleanup_socket_at_end(path):
                runner.run(server.serve_forever())
        elif args.streams:
            server = runner.run(asyncio.start_unix_server(echo_client_streams, path=path))
            LOGGER.info(f"Server listening at {', '.join(str(s.getsockname()) for s in server.sockets)}")
            with _cleanup_socket_at_end(path):
                runner.run(server.serve_forever())
        elif args.proto:
            server = runner.run(runner.get_loop().create_unix_server(EchoProtocol, path=path))
            LOGGER.info(f"Server listening at {', '.join(str(s.getsockname()) for s in server.sockets)}")
            with _cleanup_socket_at_end(path):
                runner.run(server.serve_forever())
        else:
            runner.run(echo_server(path))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
