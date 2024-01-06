#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import AsyncGenerator
from typing import Any

from easynetwork.api_async.server.handler import AsyncDatagramClient, AsyncDatagramRequestHandler
from easynetwork.api_sync.server.udp import StandaloneUDPNetworkServer
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers.abc import AbstractPacketSerializer


class NoSerializer(AbstractPacketSerializer[bytes, bytes]):
    __slots__ = ()

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data


class EchoRequestHandler(AsyncDatagramRequestHandler[Any, Any]):
    async def handle(self, client: AsyncDatagramClient[Any]) -> AsyncGenerator[None, Any]:
        request: Any = yield
        await client.send_packet(request)

    # async def handle(self, client: AsyncDatagramClient[Any]) -> AsyncGenerator[None, Any]:
    #     import asyncio

    #     while True:
    #         try:
    #             async with asyncio.timeout(10):
    #                 request: Any = yield
    #         except TimeoutError:
    #             return
    #         await client.send_packet(request)


def create_udp_server(
    *,
    port: int,
    use_uvloop: bool,
) -> StandaloneUDPNetworkServer[Any, Any]:
    asyncio_options = {}
    if use_uvloop:
        import uvloop

        asyncio_options["loop_factory"] = uvloop.new_event_loop
        print("using uvloop")
    else:
        print("using asyncio event loop")
    return StandaloneUDPNetworkServer(
        None,
        port,
        DatagramProtocol(NoSerializer()),
        EchoRequestHandler(),
        runner_options=asyncio_options,
    )


def main() -> None:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument(
        "-v",
        "--verbose",
        dest="log_level",
        action="store_const",
        const="DEBUG",
        default="INFO",
        help="Increase verbose level",
    )
    parser.add_argument(
        "-p",
        "--port",
        dest="port",
        type=int,
        default=26000,
    )
    parser.add_argument(
        "--uvloop",
        dest="use_uvloop",
        action="store_true",
    )

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    print(f"Python version: {sys.version}")
    with create_udp_server(
        port=args.port,
        use_uvloop=args.use_uvloop,
    ) as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
