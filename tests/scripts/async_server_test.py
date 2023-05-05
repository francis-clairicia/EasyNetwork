from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Callable

from easynetwork.api_async.server.abc import AbstractAsyncNetworkServer
from easynetwork.api_async.server.handler import AsyncBaseRequestHandler, AsyncClientInterface
from easynetwork.api_async.server.tcp import AsyncTCPNetworkServer
from easynetwork.api_async.server.udp import AsyncUDPNetworkServer
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer

PORT = 9000


class MyServerSerializer(AutoSeparatedPacketSerializer[str, str]):
    def __init__(self) -> None:
        super().__init__(separator=b"\n", keepends=False)

    def serialize(self, packet: str) -> bytes:
        return packet.encode("utf-8")

    def deserialize(self, data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeError as exc:
            from easynetwork.exceptions import DeserializeError

            raise DeserializeError(str(exc)) from exc


class MyAsyncRequestHandler(AsyncBaseRequestHandler[str, str]):
    async def handle(self, request: str, client: AsyncClientInterface[str]) -> None:
        await client.send_packet(request.upper())


def create_tcp_server() -> AsyncTCPNetworkServer[str, str]:
    return AsyncTCPNetworkServer(None, PORT, StreamProtocol(MyServerSerializer()), MyAsyncRequestHandler())


def create_udp_server() -> AsyncUDPNetworkServer[str, str]:
    return AsyncUDPNetworkServer(None, PORT, DatagramProtocol(MyServerSerializer()), MyAsyncRequestHandler())


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

    ipproto_group = parser.add_mutually_exclusive_group()
    ipproto_group.add_argument(
        "-t",
        "--tcp",
        dest="server_factory",
        action="store_const",
        const=create_tcp_server,
        help="launch TCP server (the default)",
    )
    ipproto_group.add_argument(
        "-u",
        "--udp",
        dest="server_factory",
        action="store_const",
        const=create_udp_server,
        help="launch UDP server",
    )
    parser.set_defaults(server_factory=create_tcp_server)

    args = parser.parse_args()

    server_factory: Callable[[], AbstractAsyncNetworkServer] = args.server_factory

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    async with server_factory() as server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
