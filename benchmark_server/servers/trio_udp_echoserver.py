#!/usr/bin/env python3

from __future__ import annotations

import argparse
import logging
import pathlib
import socket
import sys
from typing import Any, Final, NoReturn

import trio

LOGGER: Final[logging.Logger] = logging.getLogger("trio server")

ROOT_DIR: Final[pathlib.Path] = pathlib.Path(__file__).parent


async def echo_server(address: tuple[str, int]) -> NoReturn:
    sock = trio.socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    await sock.bind(address)
    LOGGER.info(f"Server listening at {address}")

    lock = trio.Lock()
    with sock:
        async with trio.open_nursery() as nursery:
            while True:
                datagram, addr = await sock.recvfrom(65536)
                nursery.start_soon(_echo_client, sock, datagram, addr, lock)


async def _echo_client(sock: trio.socket.SocketType, datagram: bytes, addr: Any, lock: trio.Lock) -> None:
    async with lock:
        await sock.sendto(datagram, addr)


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

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    print(f"Python version: {sys.version}")

    port: int = args.port

    trio.run(echo_server, ("0.0.0.0", port))


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
