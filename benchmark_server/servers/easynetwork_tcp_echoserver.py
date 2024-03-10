#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import pathlib
import ssl
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers.abc import BufferedIncrementalPacketSerializer
from easynetwork.serializers.base_stream import _buffered_readuntil
from easynetwork.serializers.tools import GeneratorStreamReader
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer

ROOT_DIR = pathlib.Path(__file__).parent


class NoSerializer(BufferedIncrementalPacketSerializer[bytes, bytes, memoryview]):
    __slots__ = ()

    def incremental_serialize(self, packet: bytes) -> Generator[bytes, None, None]:
        yield packet

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[bytes, bytes]]:
        return (yield), b""

    def create_deserializer_buffer(self, sizehint: int) -> memoryview:
        return memoryview(bytearray(sizehint))

    def buffered_incremental_deserialize(self, buffer: memoryview) -> Generator[int | None, int, tuple[bytes, bytes]]:
        offset = yield None
        return bytes(buffer[:offset]), b""


class LineSerializer(BufferedIncrementalPacketSerializer[bytes, bytes, bytearray]):
    __slots__ = ()

    def incremental_serialize(self, packet: bytes) -> Generator[bytes, None, None]:
        yield packet

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[bytes, bytes]]:
        reader = GeneratorStreamReader()
        packet = yield from reader.read_until(b"\n", limit=65536)
        remainder = reader.read_all()
        return packet, remainder

    def create_deserializer_buffer(self, sizehint: int) -> bytearray:
        return bytearray(sizehint)

    def buffered_incremental_deserialize(self, buffer: bytearray) -> Generator[int | None, int, tuple[bytes, memoryview]]:
        with memoryview(buffer) as buffer_view:
            _, offset, buflen = yield from _buffered_readuntil(buffer, b"\n")
            return bytes(buffer[:offset]), buffer_view[offset:buflen]


class EchoRequestHandler(AsyncStreamRequestHandler[Any, Any]):
    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[None, Any]:
        request: Any = yield
        await client.send_packet(request)


class EchoRequestHandlerInnerLoop(AsyncStreamRequestHandler[Any, Any]):
    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[None, Any]:
        while True:
            request: Any = yield
            await client.send_packet(request)


def create_tcp_server(
    *,
    port: int,
    over_ssl: bool,
    use_uvloop: bool,
    buffered: bool,
    readline: bool,
    context_reuse: bool,
) -> StandaloneTCPNetworkServer[Any, Any]:
    asyncio_options = {}
    if use_uvloop:
        import uvloop

        asyncio_options["loop_factory"] = uvloop.new_event_loop
        print("using uvloop")
    else:
        print("using asyncio event loop")
    ssl_context: ssl.SSLContext | None = None
    if over_ssl:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(
            ROOT_DIR / "certs" / "ssl_cert.pem",
            ROOT_DIR / "certs" / "ssl_key.pem",
        )
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    if buffered:
        print("with buffered serializer")
    if context_reuse:
        print("with context reuse")
    protocol: StreamProtocol[Any, Any]
    if readline:
        protocol = StreamProtocol(LineSerializer())
    else:
        protocol = StreamProtocol(NoSerializer())
    return StandaloneTCPNetworkServer(
        None,
        port,
        protocol,
        EchoRequestHandlerInnerLoop() if context_reuse else EchoRequestHandler(),
        ssl=ssl_context,
        runner_options=asyncio_options,
        manual_buffer_allocation="force" if buffered else "no",
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
        default=25000,
    )
    parser.add_argument(
        "--uvloop",
        dest="use_uvloop",
        action="store_true",
    )
    parser.add_argument(
        "--ssl",
        dest="over_ssl",
        action="store_true",
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
        "--context-reuse",
        dest="context_reuse",
        action="store_true",
    )

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    print(f"Python version: {sys.version}")
    with create_tcp_server(
        port=args.port,
        use_uvloop=args.use_uvloop,
        over_ssl=args.over_ssl,
        buffered=args.buffered,
        readline=args.readline,
        context_reuse=args.context_reuse,
    ) as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
