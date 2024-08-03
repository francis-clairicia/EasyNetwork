from __future__ import annotations

from easynetwork.servers import StandaloneUDPNetworkServer

from echo_request_handler import EchoRequestHandler
from json_protocol import JSONDatagramProtocol


def main() -> None:
    host = None
    port = 9000
    protocol = JSONDatagramProtocol()
    handler = EchoRequestHandler()

    with StandaloneUDPNetworkServer(host, port, protocol, handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
