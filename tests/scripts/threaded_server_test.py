from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import socket
from collections.abc import Callable, Generator
from typing import Any, assert_never

from easynetwork.lowlevel.api_sync.servers.selector_datagram import DatagramClientContext, SelectorDatagramServer
from easynetwork.lowlevel.api_sync.servers.selector_stream import ConnectedStreamClient, SelectorStreamServer
from easynetwork.lowlevel.api_sync.transports.socket import SocketDatagramListener, SocketStreamListener
from easynetwork.lowlevel.constants import DEFAULT_STREAM_BUFSIZE
from easynetwork.lowlevel.request_handler import RecvParams
from easynetwork.lowlevel.socket import INETSocketAttribute
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.line import StringLineSerializer

PORT = 9000

logger = logging.getLogger("app")


def stream_handle(client: ConnectedStreamClient[str], server: SelectorStreamServer[str, str]) -> Generator[float | None, str]:
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
                case "self_kill:":
                    server.close()
                    client.send_packet("stop_listening() done")
                    continue
                case _:
                    pass
            client.send_packet(request.upper())
    finally:
        logger.info(f"{client_address} disconnected")


def dgram_handle(client: DatagramClientContext[str, str | bytes]) -> Generator[RecvParams | None, str]:
    request: str = yield None
    logger.debug(f"Received {request!r} from {client.address!r}")
    match request:
        case "error:":
            raise RuntimeError("requested error")
        case "wait:":
            request = (yield None) + " after wait"
        case _ if request.startswith("timeout:"):
            try:
                request = yield RecvParams(timeout=float(request.partition(":")[2]))
            except TimeoutError:
                logger.error(f"{client!r}: timed out")
                return
            else:
                request += " after timeout"
        case "self_kill:":
            client.server.close()
            client.server.send_packet_to("stop_listening() done", client.address)
            return
        case _:
            pass
    client.server.send_packet_to(request.upper(), client.address)


def create_tcp_server() -> SelectorStreamServer[str, str]:
    listener = SocketStreamListener(socket.create_server(("0.0.0.0", PORT), backlog=10))
    return SelectorStreamServer(listener, StreamProtocol(StringLineSerializer()), DEFAULT_STREAM_BUFSIZE)


def create_udp_server() -> SelectorDatagramServer[str, str, tuple[Any, ...]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    listener = SocketDatagramListener(sock)
    return SelectorDatagramServer(listener, DatagramProtocol(StringLineSerializer()))


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

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    server_factory: Callable[[], SelectorStreamServer[str, str] | SelectorDatagramServer[str, str, Any]] = args.server_factory

    with server_factory() as server, concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        logger.info("Start serving at %s:%d", "0.0.0.0", PORT)
        logger.info("-> PID: %r", os.getpid())
        logger.info("-> Number of workers: %r", executor._max_workers)
        logger.info("-> Worker strategy: %r", args.worker_strategy)
        try:
            match server:
                case SelectorStreamServer():
                    server.serve(
                        lambda client: stream_handle(client, server),
                        executor,
                        worker_strategy=args.worker_strategy,
                        disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
                    )
                case SelectorDatagramServer() if args.worker_strategy != "requests":
                    raise NotImplementedError(args.worker_strategy)
                case SelectorDatagramServer():
                    server.serve(dgram_handle, executor)
                case _:
                    assert_never(server)
        finally:
            logger.info("Server loop break, waiting for remaining tasks...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
