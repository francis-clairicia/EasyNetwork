from __future__ import annotations

from easynetwork.clients.unix_stream import UnixStreamClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    address = "/var/run/app/app.sock"

    try:
        client = UnixStreamClient(address, protocol, connect_timeout=30)
    except TimeoutError:
        print(f"Could not connect to {address} after 30 seconds")
        return

    with client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    main()
