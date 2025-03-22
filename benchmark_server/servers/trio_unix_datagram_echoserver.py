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
from typing import Any, Final, NoReturn

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
    sock = trio.socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    await sock.bind(path)
    LOGGER.info(f"Server listening at {sock.getsockname()}")

    with _cleanup_socket_at_end(path), sock:
        async with trio.open_nursery() as nursery:
            lock = trio.Lock()
            while True:
                datagram, addr = await sock.recvfrom(65536)
                if addr:
                    nursery.start_soon(_echo_client, lock, sock, datagram, addr)
                else:
                    LOGGER.warning("A datagram received from an unbound UNIX datagram socket was dropped.")


async def _echo_client(lock: trio.Lock, server: trio.socket.SocketType, datagram: bytes, addr: Any) -> None:
    async with lock:
        await server.sendto(datagram, addr)


def main() -> None:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    server_mode_parser_group = parser.add_mutually_exclusive_group()
    server_mode_parser_group.add_argument(
        "--streams",
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

    trio.run(echo_server, path)


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
