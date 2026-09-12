from __future__ import annotations

from easynetwork.servers import ThreadedUDPNetworkServer

from echo_request_handler_blocking import EchoRequestHandler
from json_protocol import JSONDatagramProtocol


def main() -> None:
    host = None
    port = 9000
    protocol = JSONDatagramProtocol()
    handler = EchoRequestHandler()

    with ThreadedUDPNetworkServer(host, port, protocol, handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except* KeyboardInterrupt:
        pass
