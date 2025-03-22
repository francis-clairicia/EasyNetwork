#!/usr/bin/env python3
# mypy: disable-error-code=unused-awaitable

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import logging
import pathlib
import socket
import ssl
import sys
from typing import Any, Final, NoReturn, cast

LOGGER: Final[logging.Logger] = logging.getLogger("asyncio server")

ROOT_DIR: Final[pathlib.Path] = pathlib.Path(__file__).parent


async def echo_server(address: tuple[str, int]) -> NoReturn:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    sock.bind(address)
    sock.listen(256)
    sock.setblocking(False)
    LOGGER.info(f"Server listening at {address}")
    with sock:
        while True:
            client, addr = await loop.sock_accept(sock)
            LOGGER.info(f"Connection from {addr}")
            loop.create_task(_echo_client(loop, client, addr))


async def _echo_client(loop: asyncio.AbstractEventLoop, client: socket.socket, addr: Any) -> None:
    try:
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    except (OSError, NameError):
        pass

    lock = asyncio.Lock()
    with client:
        while True:
            data = await loop.sock_recv(client, 102400)
            if not data:
                break
            async with lock:
                await loop.sock_sendall(client, data)
    LOGGER.info(f"{addr}: Connection closed")


async def echo_client_streams(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    sock: socket.socket = writer.get_extra_info("socket")
    addr: Any = writer.get_extra_info("peername")
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    except (OSError, NameError):
        pass
    writer.transport.set_write_buffer_limits(0)
    LOGGER.info(f"Connection from {addr}")

    lock = asyncio.Lock()
    with contextlib.closing(writer):
        while True:
            data = await reader.read(102400)
            if not data:
                break
            async with lock:
                writer.write(data)
                await writer.drain()
    LOGGER.info(f"{addr}: Connection closed")


async def readline_client_streams(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    sock: socket.socket = writer.get_extra_info("socket")
    addr: Any = writer.get_extra_info("peername")
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    except (OSError, NameError):
        pass
    writer.transport.set_write_buffer_limits(0)
    LOGGER.info(f"Connection from {addr}")

    lock = asyncio.Lock()
    with contextlib.closing(writer):
        while True:
            data = await reader.readline()
            if not data:
                break
            async with lock:
                writer.write(data)
                await writer.drain()
    LOGGER.info(f"{addr}: Connection closed")


class EchoProtocol(asyncio.Protocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport: asyncio.Transport = cast(asyncio.Transport, transport)
        sock: socket.socket = transport.get_extra_info("socket")
        addr: Any = transport.get_extra_info("peername")
        self.addr = addr
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        except (OSError, NameError):
            pass
        LOGGER.info(f"Connection from {addr}")

    def connection_lost(self, exc: Exception | None) -> None:
        LOGGER.info(f"{self.addr}: Connection closed")
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
        "--port",
        dest="port",
        type=int,
        default=25000,
    )
    parser.add_argument(
        "--uvloop",
        dest="use_uvloop",
        action="store_true",
    )
    parser.add_argument(
        "--ssl",
        dest="over_ssl",
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
        ssl_context: ssl.SSLContext | None = None
        if args.over_ssl:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(
                ROOT_DIR / "certs" / "ssl_cert.pem",
                ROOT_DIR / "certs" / "ssl_key.pem",
            )
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        port: int = args.port
        if args.readline:
            server = runner.run(asyncio.start_server(readline_client_streams, port=port, ssl=ssl_context))
            LOGGER.info(f"Server listening at {', '.join(str(s.getsockname()) for s in server.sockets)}")
            runner.run(server.serve_forever())
        elif args.streams:
            server = runner.run(asyncio.start_server(echo_client_streams, port=port, ssl=ssl_context))
            LOGGER.info(f"Server listening at {', '.join(str(s.getsockname()) for s in server.sockets)}")
            runner.run(server.serve_forever())
        elif args.proto:
            server = runner.run(runner.get_loop().create_server(EchoProtocol, port=port, ssl=ssl_context))
            LOGGER.info(f"Server listening at {', '.join(str(s.getsockname()) for s in server.sockets)}")
            runner.run(server.serve_forever())
        else:
            if ssl_context:
                raise OSError("loop.sock_sendall() and loop.sock_recv() do not support SSL")
            runner.run(echo_server(("0.0.0.0", port)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
