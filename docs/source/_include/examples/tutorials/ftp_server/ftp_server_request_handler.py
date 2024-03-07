from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncGenerator
from typing import Any

from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler, INETClientAttribute

from ftp_command import FTPCommand
from ftp_reply import FTPReply
from ftp_request import FTPRequest


class FTPRequestHandler(AsyncStreamRequestHandler[FTPRequest, FTPReply]):
    async def service_init(
        self,
        exit_stack: contextlib.AsyncExitStack,
        server: Any,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    async def on_connection(self, client: AsyncStreamClient[FTPReply]) -> None:
        await client.send_packet(FTPReply.service_ready_for_new_user())

    async def on_disconnection(self, client: AsyncStreamClient[FTPReply]) -> None:
        with contextlib.suppress(ConnectionError):
            if not client.is_closing():
                await client.send_packet(FTPReply.connection_close(unexpected=True))

    async def handle(
        self,
        client: AsyncStreamClient[FTPReply],
    ) -> AsyncGenerator[None, FTPRequest]:
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
            await client.send_packet(FTPReply.syntax_error())
            return

        self.logger.info("Sent by client %s: %s", client_address, request)
        match request:
            case FTPRequest(FTPCommand.NOOP):
                await client.send_packet(FTPReply.ok())

            case FTPRequest(FTPCommand.QUIT):
                async with contextlib.aclosing(client):
                    await client.send_packet(FTPReply.connection_close())

            case _:
                await client.send_packet(FTPReply.not_implemented_error())
