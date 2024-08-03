from __future__ import annotations

from collections.abc import Sequence

from easynetwork.servers import AsyncTCPNetworkServer

from ftp_reply import FTPReply
from ftp_request import FTPRequest
from ftp_server_protocol import FTPServerProtocol
from ftp_server_request_handler import FTPRequestHandler


class AsyncFTPServer(AsyncTCPNetworkServer[FTPRequest, FTPReply]):
    def __init__(
        self,
        host: str | Sequence[str] | None = None,
        port: int = 21000,
    ) -> None:
        super().__init__(
            host,
            port,
            FTPServerProtocol(),
            FTPRequestHandler(),
        )


if __name__ == "__main__":
    import logging

    import trio

    async def main() -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="[ %(levelname)s ] [ %(name)s ] %(message)s",
        )
        async with AsyncFTPServer() as server:
            await server.serve_forever()

    try:
        trio.run(main)
    except* KeyboardInterrupt:
        pass
