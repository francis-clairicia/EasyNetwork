from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Callable

from easynetwork.clients import AsyncTCPNetworkClient, AsyncUDPNetworkClient
from easynetwork.clients.abc import AbstractAsyncNetworkClient
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

logger = logging.getLogger("app")


def create_tcp_client(port: int) -> AsyncTCPNetworkClient[str, str]:
    return AsyncTCPNetworkClient(("localhost", port), StreamProtocol(StringLineSerializer()), "asyncio")


def create_udp_client(port: int) -> AsyncUDPNetworkClient[str, str]:
    return AsyncUDPNetworkClient(("localhost", port), DatagramProtocol(StringLineSerializer()), "asyncio")


async def main() -> None:
    parser = argparse.ArgumentParser()

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
        dest="server_port",
        type=int,
        default=9000,
        help="Server port",
    )

    ipproto_group = parser.add_mutually_exclusive_group()
    ipproto_group.add_argument(
        "-t",
        "--tcp",
        dest="client_factory",
        action="store_const",
        const=create_tcp_client,
        help="launch TCP client (the default)",
    )
    ipproto_group.add_argument(
        "-u",
        "--udp",
        dest="client_factory",
        action="store_const",
        const=create_udp_client,
        help="launch UDP client",
    )
    parser.set_defaults(client_factory=create_tcp_client)

    args = parser.parse_args()

    client_factory: Callable[[int], AbstractAsyncNetworkClient[str, str]] = args.client_factory
    server_port: int = args.server_port

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[ %(asctime)s ] [ %(levelname)s ] [ %(name)s ] %(message)s",
    )

    async with client_factory(server_port) as client:
        task = asyncio.create_task(client.recv_packet())

        logger.info("client.recv_packet() in task")
        await asyncio.sleep(1.1)

        await client.aclose()
        logger.info("client.aclose() called")
        await asyncio.wait({task})
        logger.info("Returned exception: %r", task.exception())
        logger.info("successfully aborted")
        logger.info("End")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
