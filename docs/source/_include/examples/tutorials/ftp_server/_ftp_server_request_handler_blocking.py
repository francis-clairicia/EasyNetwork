from __future__ import annotations

import contextlib
import logging
from collections.abc import Generator
from typing import Any

from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.servers.handlers import BlockingStreamClient, BlockingStreamRequestHandler, INETClientAttribute

from ftp_command import FTPCommand
from ftp_reply import FTPReply
from ftp_request import FTPRequest


class BlockingFTPRequestHandler(BlockingStreamRequestHandler[FTPRequest, FTPReply]):
    def service_init(
        self,
        exit_stack: contextlib.ExitStack,
        server: Any,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    def on_connection(self, client: BlockingStreamClient[FTPReply]) -> None:
        client.send_packet(FTPReply.service_ready_for_new_user())

    def on_disconnection(self, client: BlockingStreamClient[FTPReply]) -> None:
        with contextlib.suppress(ConnectionError):
            if not client.is_closing():
                client.send_packet(FTPReply.connection_close(unexpected=True))

    def handle(
        self,
        client: BlockingStreamClient[FTPReply],
    ) -> Generator[None, FTPRequest]:
        client_address = client.extra(INETClientAttribute.remote_address)
        try:
            request: FTPRequest = yield
        except StreamProtocolParseError as exc:
            self.logger.warning(
                "%s: %s: %s",
                client_address,
                type(exc.error).__name__,
                exc.error,
            )
            client.send_packet(FTPReply.syntax_error())
            return

        self.logger.info("Sent by client %s: %s", client_address, request)
        match request:
            case FTPRequest(FTPCommand.NOOP):
                client.send_packet(FTPReply.ok())

            case FTPRequest(FTPCommand.QUIT):
                with contextlib.closing(client):
                    client.send_packet(FTPReply.connection_close())

            case _:
                client.send_packet(FTPReply.not_implemented_error())
