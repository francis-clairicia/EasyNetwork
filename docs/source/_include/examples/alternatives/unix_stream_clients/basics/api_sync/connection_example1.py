from __future__ import annotations

from easynetwork.clients.unix_stream import UnixStreamClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


def main() -> None:
    protocol = StreamProtocol(JSONSerializer())
    address = "/var/run/app/app.sock"

    with UnixStreamClient(address, protocol) as client:
        print(f"Remote address: {client.get_peer_name()}")

        ...


if __name__ == "__main__":
    main()
