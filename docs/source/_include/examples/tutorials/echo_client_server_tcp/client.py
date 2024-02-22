from __future__ import annotations

import sys

from easynetwork.clients import TCPNetworkClient

from json_protocol import JSONProtocol


def main() -> None:
    host = "localhost"
    port = 9000

    # Connect to server
    with TCPNetworkClient((host, port), JSONProtocol()) as client:
        # Send data
        request = {"command-line arguments": sys.argv[1:]}
        client.send_packet(request)

        # Receive data from the server and shut down
        response = client.recv_packet()

    print(f"Sent:     {request}")
    print(f"Received: {response}")


if __name__ == "__main__":
    main()
