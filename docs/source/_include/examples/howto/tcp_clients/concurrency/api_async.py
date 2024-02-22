from __future__ import annotations

import asyncio
import contextlib
import traceback
from typing import Any, TypeAlias

from easynetwork.clients import AsyncTCPNetworkClient
from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

RequestType: TypeAlias = dict[str, Any]
ResponseType: TypeAlias = dict[str, Any]


async def consumer(response: ResponseType) -> None:
    # Do some stuff...

    print(response)


async def receiver_worker(
    client: AsyncTCPNetworkClient[RequestType, ResponseType],
    task_group: asyncio.TaskGroup,
) -> None:
    while True:
        try:
            # Pass timeout=None to get an infinite iterator.
            # It will be terminated when the client.close() method has been called.
            async for response in client.iter_received_packets(timeout=None):
                _ = task_group.create_task(consumer(response))
        except StreamProtocolParseError:
            print("Parsing error")
            traceback.print_exc()
            continue


async def do_main_stuff(
    client: AsyncTCPNetworkClient[RequestType, ResponseType],
) -> None:
    while True:
        # Do some stuff...
        request = {"data": 42}

        await client.send_packet(request)


async def main() -> None:
    remote_address = ("localhost", 9000)
    protocol = StreamProtocol(JSONSerializer())

    async with contextlib.AsyncExitStack() as exit_stack:
        # task group setup
        task_group = await exit_stack.enter_async_context(asyncio.TaskGroup())

        # connect to remote
        client = AsyncTCPNetworkClient(remote_address, protocol)
        await exit_stack.enter_async_context(client)

        # receiver_worker task setup
        _ = task_group.create_task(receiver_worker(client, task_group))

        # Setup done, let's go
        await do_main_stuff(client)


if __name__ == "__main__":
    asyncio.run(main())
