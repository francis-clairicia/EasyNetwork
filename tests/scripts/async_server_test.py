from __future__ import annotations

import argparse
import logging
from collections.abc import AsyncGenerator, Callable

from easynetwork.api_async.server.handler import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler
from easynetwork.api_sync.server.abc import AbstractStandaloneNetworkServer
from easynetwork.api_sync.server.tcp import StandaloneTCPNetworkServer
from easynetwork.api_sync.server.udp import StandaloneUDPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

PORT = 9000

logger = logging.getLogger("app")


class MyAsyncRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def handle(self, client: AsyncBaseClientInterface[str]) -> AsyncGenerator[None, str]:
        request: str = yield
        logger.debug(f"Received {request!r}")
        if request == "wait:":
            request = (yield) + " after wait"
        await client.send_packet(request.upper())

    async def bad_request(self, client: AsyncBaseClientInterface[str], exc: BaseProtocolParseError) -> None:
        pass


def create_tcp_server() -> StandaloneTCPNetworkServer[str, str]:
    return StandaloneTCPNetworkServer(None, PORT, StreamProtocol(StringLineSerializer()), MyAsyncRequestHandler())


def create_udp_server() -> StandaloneUDPNetworkServer[str, str]:
    return StandaloneUDPNetworkServer("127.0.0.1", PORT, DatagramProtocol(StringLineSerializer()), MyAsyncRequestHandler())


def main() -> None:
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

    server_factory: Callable[[], AbstractStandaloneNetworkServer] = args.server_factory

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    with server_factory() as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
