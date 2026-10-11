from __future__ import annotations

from collections.abc import Sequence

from easynetwork.servers import ThreadedTCPNetworkServer

from ftp_reply import FTPReply
from ftp_request import FTPRequest
from ftp_server_protocol import FTPServerProtocol
from ftp_server_request_handler import BlockingFTPRequestHandler


class FTPServer(ThreadedTCPNetworkServer[FTPRequest, FTPReply]):
    def __init__(
        self,
        host: str | Sequence[str] | None = None,
        port: int = 21000,
    ) -> None:
        super().__init__(
            host,
            port,
            FTPServerProtocol(),
            BlockingFTPRequestHandler(),
        )


if __name__ == "__main__":
    import logging

    def main() -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="[ %(levelname)s ] [ %(name)s ] %(message)s",
        )
        with FTPServer() as server:
            try:
                server.serve_forever()
            except* KeyboardInterrupt:
                pass

    main()
