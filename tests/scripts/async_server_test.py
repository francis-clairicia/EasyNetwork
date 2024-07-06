from __future__ import annotations

import argparse
import contextlib
import logging
from collections.abc import AsyncGenerator, Callable

from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer
from easynetwork.servers.abc import AbstractAsyncNetworkServer, AbstractNetworkServer
from easynetwork.servers.handlers import AsyncBaseClientInterface, AsyncDatagramRequestHandler, AsyncStreamRequestHandler
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer
from easynetwork.servers.standalone_udp import StandaloneUDPNetworkServer

PORT = 9000

logger = logging.getLogger("app")


class MyAsyncRequestHandler(AsyncStreamRequestHandler[str, str], AsyncDatagramRequestHandler[str, str]):
    async def service_init(self, exit_stack: contextlib.AsyncExitStack, server: AbstractAsyncNetworkServer) -> None:
        self.server = server

    async def handle(self, client: AsyncBaseClientInterface[str]) -> AsyncGenerator[None, str]:
        request: str = yield
        logger.debug(f"Received {request!r} from {client!r}")
        match request:
            case "error:":
                raise RuntimeError("requested error")
            case "wait:":
                request = (yield) + " after wait"
            case "self_kill:":
                await self.server.server_close()
                await client.send_packet("stop_listening() done")
                return
        await client.send_packet(request.upper())


def create_tcp_server() -> StandaloneTCPNetworkServer[str, str]:
    return StandaloneTCPNetworkServer(None, PORT, StreamProtocol(StringLineSerializer()), MyAsyncRequestHandler())


def create_udp_server() -> StandaloneUDPNetworkServer[str, str]:
    return StandaloneUDPNetworkServer(None, PORT, DatagramProtocol(StringLineSerializer()), MyAsyncRequestHandler())


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

    server_factory: Callable[[], AbstractNetworkServer] = args.server_factory

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    with server_factory() as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
