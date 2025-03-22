#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gc
import logging
import socket
import sys
from typing import Any, Final, NoReturn

import trio

LOGGER: Final[logging.Logger] = logging.getLogger("trio server")


async def echo_server(address: tuple[str, int]) -> NoReturn:
    sock = trio.socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    await sock.bind(address)
    LOGGER.info(f"Server listening at {sock.getsockname()}")

    with sock:
        async with trio.open_nursery() as nursery:
            lock = trio.Lock()
            while True:
                datagram, addr = await sock.recvfrom(65536)
                nursery.start_soon(_echo_client, lock, sock, datagram, addr)


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
        "--port",
        dest="port",
        type=int,
        default=25000,
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

    port: int = args.port

    trio.run(echo_server, ("0.0.0.0", port))


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
