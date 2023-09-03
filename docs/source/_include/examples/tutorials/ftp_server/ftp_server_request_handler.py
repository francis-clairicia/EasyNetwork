from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncGenerator

from easynetwork.api_async.server import AsyncStreamClient, AsyncStreamRequestHandler
from easynetwork.exceptions import StreamProtocolParseError

from ftp_command import FTPCommand
from ftp_reply import FTPReply
from ftp_request import FTPRequest


class FTPRequestHandler(AsyncStreamRequestHandler[FTPRequest, FTPReply]):
    async def service_init(self, exit_stack: contextlib.AsyncExitStack) -> None:
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
        request: FTPRequest = yield
        self.logger.info("Sent by client %s: %s", client.address, request)
        match request:
            case FTPRequest(FTPCommand.NOOP):
                await client.send_packet(FTPReply.ok())

            case FTPRequest(FTPCommand.QUIT):
                async with contextlib.aclosing(client):
                    await client.send_packet(FTPReply.connection_close())

            case _:
                await client.send_packet(FTPReply.not_implemented_error())

    async def bad_request(
        self,
        client: AsyncStreamClient[FTPReply],
        exc: StreamProtocolParseError,
    ) -> None:
        self.logger.warning(
            "%s: %s: %s",
            client.address,
            type(exc.error).__name__,
            exc.error,
        )
        await client.send_packet(FTPReply.syntax_error())
