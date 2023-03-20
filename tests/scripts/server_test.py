from __future__ import annotations

import argparse
import logging
from typing import Callable

from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.base_stream import AutoSeparatedPacketSerializer
from easynetwork.sync.server.abc import AbstractNetworkServer
from easynetwork.sync.server.tcp import AbstractTCPNetworkServer, ConnectedClient
from easynetwork.sync.server.udp import AbstractUDPNetworkServer
from easynetwork.tools.socket import SocketAddress

PORT = 9000


class MyServerSerializer(AutoSeparatedPacketSerializer[str, str]):
    def __init__(self) -> None:
        super().__init__(separator=b"\n", keepends=False)

    def serialize(self, packet: str) -> bytes:
        return packet.encode("utf-8")

    def deserialize(self, data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeError as exc:
            from easynetwork.exceptions import DeserializeError

            raise DeserializeError(str(exc)) from exc


class MyTCPServer(AbstractTCPNetworkServer[str, str]):
    max_recv_size = 1024

    def __init__(self) -> None:
        super().__init__(host="", port=PORT, protocol=StreamProtocol(MyServerSerializer()))

    def process_request(self, request: str, client: ConnectedClient[str]) -> None:
        client.send_packet(request.upper())


class MyUDPServer(AbstractUDPNetworkServer[str, str]):
    def __init__(self) -> None:
        super().__init__(host="", port=PORT, protocol=DatagramProtocol(MyServerSerializer()))

    def process_request(self, request: str, client_address: SocketAddress) -> None:
        self.send_packet_to(request.upper(), client_address)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-v",
        "--verbose",
        dest="log_level",
        action="store_const",
        const="DEBUG",
        default="INFO",
        help="Increase verbose level",
    )

    ipproto_group = parser.add_mutually_exclusive_group()
    ipproto_group.add_argument(
        "-t",
        "--tcp",
        dest="server_factory",
        action="store_const",
        const=MyTCPServer,
        help="launch TCP server (the default)",
    )
    ipproto_group.add_argument(
        "-u",
        "--udp",
        dest="server_factory",
        action="store_const",
        const=MyUDPServer,
        help="launch UDP server",
    )
    parser.set_defaults(server_factory=MyTCPServer)

    args = parser.parse_args()

    server_factory: Callable[[], AbstractNetworkServer[str, str]] = args.server_factory

    logging.basicConfig(level=getattr(logging, args.log_level), format="[ %(levelname)s ] [ %(name)s ] %(message)s")

    with server_factory() as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
