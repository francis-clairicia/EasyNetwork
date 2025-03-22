#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import logging
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any, Literal

from easynetwork.protocol import BufferedStreamProtocol, StreamProtocol
from easynetwork.serializers.abc import BufferedIncrementalPacketSerializer
from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler
from easynetwork.servers.standalone_unix_stream import StandaloneUnixStreamServer


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
        super().__init__(separator=b"\n", incremental_serialize_check_separator=False, limit=65536)

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data


class EchoRequestHandler(AsyncStreamRequestHandler[Any, Any]):
    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[None, Any]:
        request: Any = yield
        await client.send_packet(request)


class EchoRequestHandlerInnerLoop(AsyncStreamRequestHandler[Any, Any]):
    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[None, Any]:
        while True:
            request: Any = yield
            await client.send_packet(request)


def _get_runner_and_options_from_arg(
    runner: Literal["asyncio", "uvloop", "trio"],
) -> tuple[Literal["asyncio", "trio"], dict[str, Any]]:
    match runner:
        case "asyncio":
            print("using asyncio event loop")
            return ("asyncio", {})
        case "uvloop":
            import uvloop

            print("using uvloop")
            return ("asyncio", {"loop_factory": uvloop.new_event_loop})
        case "trio":
            print("using trio")
            return ("trio", {})


def create_unix_stream_server(
    *,
    path: str,
    runner: Literal["asyncio", "uvloop", "trio"],
    buffered: bool,
    readline: bool,
    context_reuse: bool,
) -> StandaloneUnixStreamServer[Any, Any]:
    backend, options = _get_runner_and_options_from_arg(runner)
    if buffered:
        print("with buffered serializer")
    if context_reuse:
        print("with context reuse")

    serializer: BufferedIncrementalPacketSerializer[Any, Any, Any]
    protocol: StreamProtocol[Any, Any] | BufferedStreamProtocol[Any, Any, Any]
    if readline:
        serializer = LineSerializer()
    else:
        serializer = NoSerializer()
    if buffered:
        protocol = BufferedStreamProtocol(serializer)
    else:
        protocol = StreamProtocol(serializer)
    return StandaloneUnixStreamServer(
        path,
        protocol,
        EchoRequestHandlerInnerLoop() if context_reuse else EchoRequestHandler(),
        backend=backend,
        runner_options=options,
        max_recv_size=65536,  # Default buffer limit of asyncio streams
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
        "--context-reuse",
        dest="context_reuse",
        action="store_true",
    )
    parser.add_argument(
        "--disable-gc",
        dest="gc_enabled",
        action="store_false",
    )

    runner_parser = parser.add_mutually_exclusive_group()
    runner_parser.add_argument("--uvloop", dest="runner", action="store_const", const="uvloop")
    runner_parser.add_argument("--trio", dest="runner", action="store_const", const="trio")
    runner_parser.set_defaults(runner="asyncio")

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")
    if not args.gc_enabled:
        gc.disable()

    print(f"Python version: {sys.version}")
    print(f"GC enabled: {gc.isenabled()}")

    with create_unix_stream_server(
        path=args.path,
        runner=args.runner,
        buffered=args.buffered,
        readline=args.readline,
        context_reuse=args.context_reuse,
    ) as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
