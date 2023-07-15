from __future__ import annotations

import sys
from typing import Any

from easynetwork.api_sync.client.udp import UDPNetworkEndpoint

from json_protocol import JSONProtocol


def sender(endpoint: UDPNetworkEndpoint[Any, Any], address: tuple[str, int], to_send: list[str]) -> None:
    # Send data to the specified address
    sent_data = {"command-line arguments": to_send}
    endpoint.send_packet_to(sent_data, address)

    # Receive data and shut down
    received_data, sender_address = endpoint.recv_packet_from()

    print(f"Sent to {address[0]}:{address[1]}       : {sent_data}")
    print(f"Received from {sender_address.host}:{sender_address.port} : {received_data}")


def receiver(endpoint: UDPNetworkEndpoint[Any, Any]) -> None:
    # JSON data has been sent by "sender_address"
    received_data, sender_address = endpoint.recv_packet_from()

    print(f"{sender_address.host}:{sender_address.port} sent {received_data}")

    # Send back to the sender
    endpoint.send_packet_to(received_data, sender_address)


def main() -> None:
    with UDPNetworkEndpoint(JSONProtocol()) as endpoint:
        match sys.argv[1:]:
            case ["sender", address_string, *to_send]:
                host, port_string = address_string.split(":")
                port = int(port_string)

                sender(endpoint, (host, port), to_send)

            case ["receiver"]:
                print(f"Receiver available on port {endpoint.get_local_address().port}")

                receiver(endpoint)

            case _:
                raise ValueError("Invalid arguments")


if __name__ == "__main__":
    main()
