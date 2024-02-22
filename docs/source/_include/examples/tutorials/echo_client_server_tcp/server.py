from __future__ import annotations

from easynetwork.servers import StandaloneTCPNetworkServer

from echo_request_handler import EchoRequestHandler
from json_protocol import JSONProtocol


def main() -> None:
    host = None
    port = 9000
    protocol = JSONProtocol()
    handler = EchoRequestHandler()

    with StandaloneTCPNetworkServer(host, port, protocol, handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
