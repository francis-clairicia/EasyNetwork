#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gc
import logging
import pathlib
import socket
import ssl
import sys
from typing import Any, Final, NoReturn

import trio

LOGGER: Final[logging.Logger] = logging.getLogger("trio server")

ROOT_DIR: Final[pathlib.Path] = pathlib.Path(__file__).parent


async def echo_server(address: tuple[str, int]) -> NoReturn:
    sock = trio.socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    await sock.bind(address)
    sock.listen(256)
    LOGGER.info(f"Server listening at {address}")
    with sock:
        async with trio.open_nursery() as nursery:
            while True:
                client, addr = await sock.accept()
                LOGGER.info(f"Connection from {addr}")
                nursery.start_soon(_echo_client, client, addr)


async def _echo_client(client: trio.socket.SocketType, addr: Any) -> None:
    try:
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    except (OSError, NameError):
        pass

    lock = trio.Lock()
    with client:
        while True:
            data = await client.recv(102400)
            if not data:
                break
            async with lock:
                while data:
                    sent = await client.send(data)
                    data = data[sent:]
    LOGGER.info(f"{addr}: Connection closed")


async def echo_stream_server(port: int, ssl_context: ssl.SSLContext | None) -> NoReturn:
    listeners: list[trio.SocketListener] = await trio.open_tcp_listeners(port)

    LOGGER.info(f"Server listening at {', '.join(str(listener.socket.getsockname()) for listener in listeners)}")

    if ssl_context:
        await trio.serve_listeners(echo_client_streams, [trio.SSLListener(listener, ssl_context) for listener in listeners])
    else:
        await trio.serve_listeners(echo_client_streams, listeners)


def _getaddr_from_stream(stream: trio.SocketStream | trio.SSLStream[trio.SocketStream]) -> tuple[Any, ...]:
    match stream:
        case trio.SSLStream(transport_stream=socket_stream):
            return socket_stream.socket.getpeername()
        case _:
            return stream.socket.getpeername()


async def echo_client_streams(stream: trio.SocketStream | trio.SSLStream[trio.SocketStream]) -> None:
    addr = _getaddr_from_stream(stream)
    LOGGER.info(f"Connection from {addr}")

    lock = trio.Lock()
    async with stream:
        while True:
            try:
                data = await stream.receive_some(102400)
            except trio.BrokenResourceError:
                break
            if not data:
                break
            async with lock:
                await stream.send_all(data)
    LOGGER.info(f"{addr}: Connection closed")


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

    parser.add_argument(
        "-p",
        "--port",
        dest="port",
        type=int,
        default=25000,
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
        raise NotImplementedError("readline server model is not implemented")
    elif args.streams:
        trio.run(echo_stream_server, port, ssl_context)
    else:
        if ssl_context:
            raise OSError("bare sockets do not support SSL")
        trio.run(echo_server, ("0.0.0.0", port))


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
