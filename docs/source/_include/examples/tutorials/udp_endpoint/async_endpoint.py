from __future__ import annotations

import asyncio
import sys
from typing import Any

from easynetwork.api_async.client.udp import AsyncUDPNetworkEndpoint

from json_protocol import JSONProtocol


async def sender(
    endpoint: AsyncUDPNetworkEndpoint[Any, Any],
    address: tuple[str, int],
    to_send: list[str],
) -> None:
    # Send data to the specified address
    sent_data = {"command-line arguments": to_send}
    await endpoint.send_packet_to(sent_data, address)

    # Receive data and shut down
    received_data, sender_address = await endpoint.recv_packet_from()

    print(f"Sent to {address[:2]}       : {sent_data}")
    print(f"Received from {sender_address} : {received_data}")


async def receiver(endpoint: AsyncUDPNetworkEndpoint[Any, Any]) -> None:
    # JSON data has been sent by "sender_address"
    received_data, sender_address = await endpoint.recv_packet_from()

    print(f"From {sender_address}: {received_data}")

    # Send back to the sender
    await endpoint.send_packet_to(received_data, sender_address)


async def main() -> None:
    async with AsyncUDPNetworkEndpoint(JSONProtocol()) as endpoint:
        match sys.argv[1:]:
            case ["sender", address_string, *to_send]:
                host, port_string = address_string.split(":")
                port = int(port_string)

                await sender(endpoint, (host, port), to_send)

            case ["receiver"]:
                receiver_port = endpoint.get_local_address().port
                print(f"Receiver available on port {receiver_port}")

                await receiver(endpoint)

            case _:
                raise ValueError("Invalid arguments")


if __name__ == "__main__":
    asyncio.run(main())
