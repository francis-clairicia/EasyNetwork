#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import pathlib
import ssl
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any

from easynetwork.api_async.server.handler import AsyncStreamClient, AsyncStreamRequestHandler
from easynetwork.api_sync.server.tcp import StandaloneTCPNetworkServer
from easynetwork.exceptions import IncrementalDeserializeError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers.abc import AbstractIncrementalPacketSerializer, BufferedIncrementalPacketSerializer
from easynetwork.serializers.tools import GeneratorStreamReader

ROOT_DIR = pathlib.Path(__file__).parent


class LineSerializer(AbstractIncrementalPacketSerializer[bytes, bytes]):
    __slots__ = ()

    def incremental_serialize(self, packet: bytes) -> Generator[bytes, None, None]:
        if not packet.endswith(b"\n"):
            packet += b"\n"
        yield packet

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[bytes, bytes]]:
        reader = GeneratorStreamReader()
        packet = yield from reader.read_until(b"\n", limit=65536)
        remainder = reader.read_all()
        return packet, remainder


class BufferedLineSerializer(LineSerializer, BufferedIncrementalPacketSerializer[bytes, bytes, bytearray]):
    __slots__ = ()

    MIN_SIZE: int = 8 * 1024

    def create_deserializer_buffer(self, sizehint: int) -> bytearray:
        return bytearray(max(sizehint, self.MIN_SIZE))

    def buffered_incremental_deserialize(self, buffer: bytearray) -> Generator[int | None, int, tuple[bytes, memoryview]]:
        with memoryview(buffer) as buffer_view:
            buffer_size = len(buffer)
            nb_written_bytes: int = yield None

            while (index := buffer.find(b"\n", 0, nb_written_bytes)) < 0:
                start_idx: int = nb_written_bytes
                if start_idx > buffer_size - 1:
                    raise IncrementalDeserializeError("Too long line", remaining_data=b"")
                nb_written_bytes += yield start_idx

            offset = index + 1
            remainder: memoryview = buffer_view[offset:nb_written_bytes]
            data: bytes = bytes(buffer_view[:offset])
            return data, remainder


class EchoRequestHandler(AsyncStreamRequestHandler[Any, Any]):
    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[None, Any]:
        request: Any = yield
        await client.send_packet(request)


def create_tcp_server(
    *,
    port: int,
    over_ssl: bool,
    use_uvloop: bool,
    buffered: bool,
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
    return StandaloneTCPNetworkServer(
        None,
        port,
        StreamProtocol(BufferedLineSerializer() if buffered else LineSerializer()),
        EchoRequestHandler(),
        ssl=ssl_context,
        runner_options=asyncio_options,
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

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    print(f"Python version: {sys.version}")
    with create_tcp_server(
        port=args.port,
        use_uvloop=args.use_uvloop,
        over_ssl=args.over_ssl,
        buffered=args.buffered,
    ) as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
