#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from typing import Any

from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers.abc import AbstractPacketSerializer
from easynetwork.servers.handlers import AsyncDatagramClient, AsyncDatagramRequestHandler
from easynetwork.servers.standalone_udp import StandaloneUDPNetworkServer


class NoSerializer(AbstractPacketSerializer[bytes, bytes]):
    __slots__ = ()

    def serialize(self, packet: bytes) -> bytes:
        return packet

    def deserialize(self, data: bytes) -> bytes:
        return data


class _BaseRequestHandler(AsyncDatagramRequestHandler[Any, Any]):
    def __init__(self, eager_tasks: bool) -> None:
        super().__init__()
        self._eager_tasks: bool = bool(eager_tasks)

    async def service_init(self, exit_stack: AsyncExitStack, server: Any) -> None:
        import asyncio

        if self._eager_tasks:
            loop = asyncio.get_running_loop()
            loop.set_task_factory(getattr(asyncio, "eager_task_factory"))


class EchoRequestHandlerNoTTL(_BaseRequestHandler):
    async def handle(self, client: AsyncDatagramClient[Any]) -> AsyncGenerator[None, Any]:
        request: Any = yield
        await client.send_packet(request)


class EchoRequestHandlerWithTTL(_BaseRequestHandler):
    def __init__(self, client_ttl: float, eager_tasks: bool) -> None:
        super().__init__(eager_tasks=eager_tasks)
        self._client_ttl: float = client_ttl

    async def handle(self, client: AsyncDatagramClient[Any]) -> AsyncGenerator[None, Any]:
        from asyncio import timeout

        client_ttl = self._client_ttl
        while True:
            try:
                async with timeout(client_ttl):
                    request = yield
            except TimeoutError:
                return
            await client.send_packet(request)


def create_udp_server(
    *,
    port: int,
    use_uvloop: bool,
    eager_tasks: bool,
    client_ttl: float,
) -> StandaloneUDPNetworkServer[Any, Any]:
    asyncio_options = {}
    if use_uvloop:
        import uvloop

        asyncio_options["loop_factory"] = uvloop.new_event_loop
        print("using uvloop")
    else:
        print("using asyncio event loop")
    if eager_tasks:
        print("with eager task start")
    if client_ttl > 0:
        print(f"Client TTL: {client_ttl:.1f} seconds")
    handler = (
        EchoRequestHandlerWithTTL(client_ttl=client_ttl, eager_tasks=eager_tasks)
        if client_ttl > 0
        else EchoRequestHandlerNoTTL(eager_tasks=eager_tasks)
    )
    return StandaloneUDPNetworkServer(
        None,
        port,
        DatagramProtocol(NoSerializer()),
        handler,
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
        "--eager-tasks",
        dest="eager_tasks",
        action="store_true",
    )
    parser.add_argument(
        "--client-ttl",
        dest="client_ttl",
        type=float,
        default=0.0,
    )

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    print(f"Python version: {sys.version}")
    with create_udp_server(
        port=args.port,
        use_uvloop=args.use_uvloop,
        eager_tasks=args.eager_tasks,
        client_ttl=args.client_ttl,
    ) as server:
        return server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
