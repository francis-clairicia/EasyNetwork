#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import gc
import logging
import socket
import sys
from collections.abc import Generator

from easynetwork.lowlevel.api_sync.servers.selector_datagram import DatagramClientContext, SelectorDatagramServer
from easynetwork.lowlevel.api_sync.transports.socket import SocketDatagramListener
from easynetwork.lowlevel.request_handler import RecvParams
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers.abc import AbstractPacketSerializer


class NoSerializer(AbstractPacketSerializer[bytes, bytes]):
    __slots__ = ()

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data


def request_handler_context_reuse(
    client: DatagramClientContext[bytes, str | bytes],
    client_ttl: float,
) -> Generator[RecvParams, bytes]:
    while True:
        try:
            request: bytes = yield RecvParams(timeout=client_ttl)
        except TimeoutError:
            print(f"{client.address!r}: timed out")
            return
        client.server.send_packet_to(request, client.address)


def request_handler(client: DatagramClientContext[bytes, str | bytes]) -> Generator[None, bytes]:
    request: bytes = yield
    client.server.send_packet_to(request, client.address)


def create_udp_server(
    *,
    port: int,
) -> SelectorDatagramServer[bytes, bytes, str | bytes]:
    protocol = DatagramProtocol(NoSerializer())

    listener_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener_sock.bind(("0.0.0.0", port))

    listener = SocketDatagramListener(listener_sock)

    return SelectorDatagramServer(listener, protocol)


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
        default=25000,
    )
    parser.add_argument(
        "--client-ttl",
        dest="client_ttl",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--disable-gc",
        dest="gc_enabled",
        action="store_false",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        dest="concurrency",
        type=int,
        default=10,
        help="Maximum number of concurrent threads",
    )

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")
    if not args.gc_enabled:
        gc.disable()

    print(f"Python version: {sys.version}")
    print(f"GC enabled: {gc.isenabled()}")
    print(f"GIL enabled: {getattr(sys, "_is_gil_enabled", lambda: True)()}")

    with (
        create_udp_server(port=args.port) as server,
        concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor,
    ):
        client_ttl: float = args.client_ttl
        print(f"Start serving at 0.0.0.0:{args.port}")
        print(f"-> Number of workers: {args.concurrency}")
        print(f"-> Client TTL: {client_ttl:.3f}s")
        if client_ttl > 0:
            return server.serve(lambda client: request_handler_context_reuse(client, client_ttl), executor)
        else:
            return server.serve(request_handler, executor)


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
