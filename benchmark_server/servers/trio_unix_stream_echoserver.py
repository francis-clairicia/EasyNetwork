#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import gc
import logging
import os
import socket
import stat
import sys
from collections.abc import Iterator
from typing import Final, NoReturn

import trio

LOGGER: Final[logging.Logger] = logging.getLogger("trio server")


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
    sock = trio.socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    await sock.bind(path)
    sock.listen(256)
    LOGGER.info(f"Server listening at {path}")
    with _cleanup_socket_at_end(path), sock:
        async with trio.open_nursery() as nursery:
            while True:
                client, addr = await sock.accept()
                LOGGER.info(f"Connection from {addr!r}")
                nursery.start_soon(_echo_client, client, addr)


async def _echo_client(client: trio.socket.SocketType, addr: str) -> None:
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
    LOGGER.info(f"{addr!r}: Connection closed")


async def echo_stream_server(path: str) -> NoReturn:
    sock = trio.socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    await sock.bind(path)
    sock.listen(256)

    LOGGER.info(f"Server listening at {path}")

    with _cleanup_socket_at_end(path):
        await trio.serve_listeners(echo_client_streams, [trio.SocketListener(sock)])


async def echo_client_streams(stream: trio.SocketStream) -> None:
    addr: str = stream.socket.getpeername()
    LOGGER.info(f"Connection from {addr!r}")

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
    LOGGER.info(f"{addr!r}: Connection closed")


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
        "--path",
        dest="path",
        default="/tmp/easynetwork.sock",
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

    path: str = args.path
    if args.readline:
        raise NotImplementedError("readline server model is not implemented")
    elif args.streams:
        trio.run(echo_stream_server, path)
    else:
        trio.run(echo_server, path)


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
