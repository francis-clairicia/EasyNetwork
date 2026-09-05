#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import logging
import pathlib
import ssl
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any, Literal, assert_never

from easynetwork.protocol import BufferedStreamProtocol, StreamProtocol
from easynetwork.serializers.abc import BufferedIncrementalPacketSerializer
from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer
from easynetwork.servers.handlers import (
    AsyncStreamClient,
    AsyncStreamRequestHandler,
    BlockingStreamClient,
    BlockingStreamRequestHandler,
)
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer
from easynetwork.servers.threaded_tcp import ThreadedTCPNetworkServer

ROOT_DIR = pathlib.Path(__file__).parent


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


class AsyncEchoRequestHandler(AsyncStreamRequestHandler[Any, Any]):
    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[None, Any]:
        request: Any = yield
        await client.send_packet(request)


class AsyncEchoRequestHandlerInnerLoop(AsyncStreamRequestHandler[Any, Any]):
    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[None, Any]:
        while True:
            request: Any = yield
            await client.send_packet(request)


class BlockingEchoRequestHandler(BlockingStreamRequestHandler[Any, Any]):
    def handle(self, client: BlockingStreamClient[Any]) -> Generator[None, Any]:
        while True:
            request: Any = yield
            client.send_packet(request)


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
        case _:
            assert_never(runner)


def _get_worker_strategy_from_arg(
    runner: Literal["threaded_clients", "threaded_requests"],
) -> Literal["clients", "requests"]:
    match runner:
        case "threaded_clients":
            print("using thread pool (clients)")
            return "clients"
        case "threaded_requests":
            print("using thread pool (requests)")
            return "requests"
        case _:
            assert_never(runner)


def create_tcp_server(
    *,
    port: int,
    over_ssl: bool,
    runner: Literal["asyncio", "uvloop", "trio", "threaded_clients", "threaded_requests"],
    buffered: bool,
    readline: bool,
    context_reuse: bool,
    concurrency: int | None,
) -> StandaloneTCPNetworkServer[Any, Any] | ThreadedTCPNetworkServer[Any, Any]:
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

    context_reuse |= runner.startswith("threaded_")
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

    max_recv_size: int = 65536  # Default buffer limit of asyncio streams
    match runner:
        case "threaded_clients" | "threaded_requests":
            if concurrency:
                print(f"with concurrency : {concurrency}")
            return ThreadedTCPNetworkServer(
                None,
                port,
                protocol,
                BlockingEchoRequestHandler(),
                ssl=ssl_context,
                max_nb_workers=concurrency,
                worker_strategy=_get_worker_strategy_from_arg(runner),
                max_recv_size=max_recv_size,
            )
        case _:
            if concurrency is not None:
                sys.exit("'concurrency' parameter not handled by asynchronous servers.")
            backend, options = _get_runner_and_options_from_arg(runner)
            return StandaloneTCPNetworkServer(
                None,
                port,
                protocol,
                AsyncEchoRequestHandlerInnerLoop() if context_reuse else AsyncEchoRequestHandler(),
                ssl=ssl_context,
                backend=backend,
                runner_options=options,
                max_recv_size=max_recv_size,
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
        default=None,
        help="Maximum number of concurrent threads",
    )

    runner_parser = parser.add_mutually_exclusive_group()
    runner_parser.add_argument("--uvloop", dest="runner", action="store_const", const="uvloop")
    runner_parser.add_argument("--trio", dest="runner", action="store_const", const="trio")
    runner_parser.add_argument("--threaded-clients", dest="runner", action="store_const", const="threaded_clients")
    runner_parser.add_argument("--threaded-requests", dest="runner", action="store_const", const="threaded_requests")
    runner_parser.set_defaults(runner="asyncio")

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")
    if not args.gc_enabled:
        gc.disable()

    print(f"Python version: {sys.version}")
    print(f"GC enabled: {gc.isenabled()}")
    print(f"GIL enabled: {getattr(sys, "_is_gil_enabled", lambda: True)()}")

    with create_tcp_server(
        port=args.port,
        runner=args.runner,
        over_ssl=args.over_ssl,
        buffered=args.buffered,
        readline=args.readline,
        context_reuse=args.context_reuse,
        concurrency=args.concurrency,
    ) as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
