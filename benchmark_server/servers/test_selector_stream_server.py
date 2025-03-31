#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import gc
import logging
import os
import socket
import stat
import sys
from collections.abc import Generator
from typing import Any

from easynetwork.lowlevel.api_sync.servers.selector_stream import ConnectedStreamClient, SelectorStreamServer
from easynetwork.lowlevel.api_sync.transports.socket import SocketStreamListener
from easynetwork.lowlevel.constants import DEFAULT_STREAM_BUFSIZE
from easynetwork.protocol import BufferedStreamProtocol, StreamProtocol
from easynetwork.serializers.abc import BufferedIncrementalPacketSerializer
from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer


@contextlib.contextmanager
def _cleanup_socket_at_end(path: str) -> Generator[None]:
    try:
        yield
    finally:
        try:
            if stat.S_ISSOCK(os.stat(path).st_mode):
                os.remove(path)
        except OSError:
            pass


class NoSerializer(BufferedIncrementalPacketSerializer[bytes, bytes, memoryview]):
    __slots__ = ()

    def incremental_serialize(self, packet: bytes) -> Generator[bytes]:
        yield packet

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[bytes, bytes]]:
        return (yield), b""

    def create_deserializer_buffer(self, sizehint: int) -> memoryview:
        return memoryview(bytearray(sizehint))

    def buffered_incremental_deserialize(self, buffer: memoryview) -> Generator[int | None, int, tuple[bytes, bytes]]:
        offset = yield None
        return bytes(buffer[:offset]), b""


class LineSerializer(AutoSeparatedPacketSerializer[bytes, bytes]):
    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(separator=b"\n", incremental_serialize_check_separator=False, limit=DEFAULT_STREAM_BUFSIZE)

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data


def request_handler(client: ConnectedStreamClient[bytes]) -> Generator[None, bytes]:
    while True:
        request: bytes = yield
        client.send_packet(request)


def create_unix_stream_server(
    *,
    path: str,
    buffered: bool,
    readline: bool,
) -> SelectorStreamServer[bytes, bytes]:
    if buffered:
        print("with buffered serializer")

    serializer: BufferedIncrementalPacketSerializer[bytes, bytes, Any]
    protocol: StreamProtocol[bytes, bytes] | BufferedStreamProtocol[bytes, bytes, Any]
    if readline:
        serializer = LineSerializer()
    else:
        serializer = NoSerializer()
    if buffered:
        protocol = BufferedStreamProtocol(serializer)
    else:
        protocol = StreamProtocol(serializer)

    listener_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener_sock.bind(path)
    listener_sock.listen(100)

    listener = SocketStreamListener(listener_sock)

    return SelectorStreamServer(
        listener,
        protocol,
        max_recv_size=DEFAULT_STREAM_BUFSIZE,
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
        "--path",
        dest="path",
        default="/tmp/easynetwork.sock",
    )
    parser.add_argument(
        "--buffered",
        dest="buffered",
        action="store_true",
    )
    parser.add_argument(
        "--readline",
        dest="readline",
        action="store_true",
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
    if not args.gc_enabled:
        gc.disable()

    print(f"Python version: {sys.version}")
    print(f"GC enabled: {gc.isenabled()}")

    with (
        _cleanup_socket_at_end(args.path),
        create_unix_stream_server(
            path=args.path,
            buffered=args.buffered,
            readline=args.readline,
        ) as server,
        concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor,
    ):
        print(f"Start serving at {args.path} (pathname)")
        print(f"-> Number of workers: {args.concurrency}")
        print(f"-> Worker strategy: {args.worker_strategy}")
        return server.serve(
            request_handler,
            executor,
            worker_strategy=args.worker_strategy,
            disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
        )


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
