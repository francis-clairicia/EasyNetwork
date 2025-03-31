from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import socket
from collections.abc import Generator

from easynetwork.lowlevel.api_sync.servers.selector_stream import ConnectedStreamClient, SelectorStreamServer
from easynetwork.lowlevel.api_sync.transports.socket import SocketStreamListener
from easynetwork.lowlevel.constants import DEFAULT_STREAM_BUFSIZE
from easynetwork.lowlevel.socket import INETSocketAttribute
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

PORT = 9000

logger = logging.getLogger("app")


def handle(client: ConnectedStreamClient[str]) -> Generator[float | None, str]:
    if not (client_address := client.extra(INETSocketAttribute.peername, None)):
        return
    logger.info(f"{client_address} connected")
    try:
        while not client.is_closing():
            request: str = yield None
            logger.debug(f"Received {request!r} from {client_address!r}")
            match request:
                case "error:":
                    raise RuntimeError("requested error")
                case "wait:":
                    request = (yield None) + " after wait"
                case _ if request.startswith("timeout:"):
                    try:
                        request = yield float(request.partition(":")[2])
                    except TimeoutError:
                        logger.error(f"{client!r}: timed out")
                        return
                    else:
                        request += " after timeout"
            client.send_packet(request.upper())
    finally:
        logger.info(f"{client_address} disconnected")


def create_tcp_server() -> SelectorStreamServer[str, str]:
    listener = SocketStreamListener(socket.create_server(("0.0.0.0", PORT), backlog=10))
    return SelectorStreamServer(listener, StreamProtocol(StringLineSerializer()), DEFAULT_STREAM_BUFSIZE)


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
        "-c",
        "--concurrency",
        dest="concurrency",
        type=int,
        default=10,
        help="Maximum number of concurrent threads",
    )
    parser.add_argument(
        "-s",
        "--strategy",
        dest="worker_strategy",
        choices=["clients", "requests"],
        default="requests",
        help="Server's worker strategy",
    )

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    with create_tcp_server() as server, concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        logger.info("Start serving at %s:%d", "0.0.0.0", PORT)
        logger.info("-> PID: %r", os.getpid())
        logger.info("-> Number of workers: %r", executor._max_workers)
        logger.info("-> Worker strategy: %r", args.worker_strategy)
        try:
            return server.serve(
                handle,
                executor,
                worker_strategy=args.worker_strategy,
                disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
            )
        finally:
            logger.info("Server loop break, waiting for remaining tasks...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
