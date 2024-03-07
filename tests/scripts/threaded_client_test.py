from __future__ import annotations

import argparse
import concurrent.futures
import logging
import time
from collections.abc import Callable

from easynetwork.clients import TCPNetworkClient, UDPNetworkClient
from easynetwork.clients.abc import AbstractNetworkClient
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

logger = logging.getLogger("app")


def create_tcp_client(port: int) -> TCPNetworkClient[str, str]:
    return TCPNetworkClient(("localhost", port), StreamProtocol(StringLineSerializer()))


def create_udp_client(port: int) -> UDPNetworkClient[str, str]:
    return UDPNetworkClient(("localhost", port), DatagramProtocol(StringLineSerializer()))


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

    client_factory: Callable[[int], AbstractNetworkClient[str, str]] = args.client_factory
    server_port: int = args.server_port

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[ %(asctime)s ] [ %(levelname)s ] [ %(name)s ] %(message)s",
    )

    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor,
        client_factory(server_port) as client,
    ):
        fut = executor.submit(client.recv_packet, timeout=None)
        # fut = executor.submit(client.recv_packet, timeout=3)

        logger.info("client.recv_packet() in thread")
        time.sleep(1.1)

        client.close()
        logger.info("client.close() called")
        logger.info("Returned exception: %r", fut.exception())
        logger.info("successfully aborted")
        logger.info("End")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
